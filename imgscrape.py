#!/usr/bin/env python3
"""Download all images from a web page into a folder named after the URL.

Usage:
    imgscrape [URL ...] [-o BASE_DIR] [-n NAME] [-w WORKERS] [--all] [--no-view]

With no URL, the URL on the clipboard is used. Output goes to ~/Pictures/Scraped
(or $IMGSCRAPE_DIR) and the folder opens in Image Viewer when done.

Zillow listing pages get special handling: only the listing's own photo
gallery is downloaded, at the largest uncropped resolution available.
Every other site uses a generic <img>/srcset/og:image extractor.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from curl_cffi import requests

# Impersonating a real Chrome TLS fingerprint gets past bot walls (e.g. Zillow's
# PerimeterX) that reject plain python-requests/curl with a 403.
IMPERSONATE = "chrome"
TIMEOUT = 30
DEFAULT_OUT = os.environ.get("IMGSCRAPE_DIR", "~/Pictures/Scraped")
VIEWER_APP = "Image Viewer"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".svg", ".tif", ".tiff"}

# Path segments that carry no meaning on their own and shouldn't name a folder.
GENERIC_SEGMENTS = {
    "homedetails", "homes", "home", "property", "properties", "listing", "listings",
    "details", "detail", "p", "dp", "item", "items", "product", "products", "b",
    "index", "index.html", "index.php", "page", "pages", "view", "en", "en-us", "us",
    "photos", "gallery", "images", "image", "post", "posts", "article", "articles",
}


# --------------------------------------------------------------------------- #
# Folder naming
# --------------------------------------------------------------------------- #

def _clean(text: str) -> str:
    text = unquote(text)
    text = re.sub(r"\.(html?|php|aspx?|jsp)$", "", text, flags=re.I)
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text)
    return re.sub(r"-{2,}", "-", text).strip("-._")


def _is_meaningful(seg: str) -> bool:
    s = seg.lower()
    if not s or s in GENERIC_SEGMENTS:
        return False
    if re.fullmatch(r"[\d_-]+", s):                       # pure numbers
        return False
    if re.fullmatch(r"\d+_[a-z]+", s):                    # ids like 29069691_zpid
        return False
    if re.fullmatch(r"[0-9a-f]{16,}", s):                 # hashes
        return False
    return sum(c.isalpha() for c in s) >= 3


def folder_name_from_url(url: str) -> str:
    """Pick the most descriptive path segment of the URL to use as a folder name.

    Generic words (homedetails, listing, ...), numeric ids and hashes are skipped;
    among what's left, the most slug-like segment (most words) wins.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.").split(":")[0]
    segments = [_clean(s) for s in parsed.path.split("/")]
    candidates = [s for s in segments if _is_meaningful(s)]

    if candidates:
        # Prefer slug-like segments (several words joined by '-'), then length.
        best = max(candidates, key=lambda s: (s.count("-") + s.count("_"), len(s)))
        name = best
    else:
        site = host.split(".")[-2] if host.count(".") >= 1 else host
        tail = next((s for s in reversed(segments) if s), "")
        name = f"{site}-{tail}" if tail else site

    return name[:120].strip("-._") or "images"


# --------------------------------------------------------------------------- #
# Fetching & extraction
# --------------------------------------------------------------------------- #

def fetch(url: str, **kw) -> requests.Response:
    resp = requests.get(url, impersonate=IMPERSONATE, timeout=TIMEOUT, allow_redirects=True, **kw)
    resp.raise_for_status()
    return resp


def _largest_from_srcset(srcset: str) -> str | None:
    best, best_w = None, -1.0
    for part in srcset.split(","):
        bits = part.strip().split()
        if not bits:
            continue
        w = 0.0
        if len(bits) > 1:
            m = re.match(r"([\d.]+)([wx])", bits[1])
            if m:
                w = float(m.group(1)) * (1000 if m.group(2) == "x" else 1)
        if w > best_w:
            best, best_w = bits[0], w
    return best


# Attributes carousels, sliders and lazy-loaders use to hold the real image URL
# (slick: data-lazy, swiper: data-src/data-background, flickity: data-flickity-lazyload,
# lightboxes: data-full/data-large/data-zoom-image, ...). Checked before `src`,
# which is often just a placeholder for slides that haven't been shown yet.
LAZY_ATTRS = (
    "data-src", "data-original", "data-lazy-src", "data-lazy", "data-full", "data-full-src",
    "data-large", "data-large-src", "data-zoom-image", "data-hi-res", "data-hires",
    "data-flickity-lazyload", "data-splide-lazy", "data-image", "data-img", "src",
)
BG_ATTRS = ("data-bg", "data-background", "data-background-image", "data-bg-src")
LINK_ATTRS = ("href", "data-src", "data-href", "data-full", "data-large", "data-image")
CSS_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]+?)['"]?\s*\)""", re.I)
# WordPress serves resized copies as name-768x461.ext next to the original name.ext.
WP_SIZE_RE = re.compile(r"-\d{2,5}x\d{2,5}(?=\.\w+$)")


def _looks_like_image(url: str) -> bool:
    return Path(urlparse(url).path).suffix.lower() in IMAGE_EXTS


def extract_generic(html: str, base_url: str) -> list[tuple[str, str | None]]:
    """Walk the page in document order, collecting every image a visitor could see,
    including off-screen carousel/lightbox slides that only appear via prev/next.

    Returns (url, fallback) pairs; fallback is set when url is a guessed
    full-size original of a resized image.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for meta in soup.find_all("meta", attrs={"property": ["og:image", "og:image:url"]}):
        urls.append(meta.get("content", ""))
    for meta in soup.find_all("meta", attrs={"name": ["twitter:image", "twitter:image:src"]}):
        urls.append(meta.get("content", ""))

    for tag in soup.body.find_all(True) if soup.body else soup.find_all(True):
        if tag.name in ("img", "source"):
            if tag.name == "source" and (tag.parent is None or tag.parent.name != "picture"):
                continue  # <source> inside <video>/<audio> isn't an image
            srcset = tag.get("data-srcset") or tag.get("data-lazy-srcset") or tag.get("srcset")
            if srcset:
                urls.append(_largest_from_srcset(srcset) or "")
            for attr in LAZY_ATTRS:
                if tag.get(attr):
                    urls.append(tag[attr])
                    break
            continue

        # Slides drawn as CSS backgrounds, inline or via lazy-load attributes.
        style = tag.get("style")
        if style and "url(" in style:
            urls.extend(CSS_URL_RE.findall(style))
        for attr in BG_ATTRS:
            if tag.get(attr):
                urls.extend(CSS_URL_RE.findall(tag[attr]) or [tag[attr]])

        # Lightbox / gallery links pointing straight at an image file.
        if tag.name == "a" or tag.has_attr("data-fancybox") or tag.has_attr("data-lightbox"):
            for attr in LINK_ATTRS:
                val = tag.get(attr)
                if val and _looks_like_image(val):
                    urls.append(val)

    out: list[tuple[str, str | None]] = []
    for u in urls:
        u = (u or "").strip()
        if not u or u.startswith("data:"):
            continue
        u = urljoin(base_url, u)
        if "/wp-content/uploads/" in u and WP_SIZE_RE.search(u):
            out.append((WP_SIZE_RE.sub("", u), u))  # original, resized copy as fallback
        else:
            out.append((u, None))
    return out


ZILLOW_PREFERRED = "uncropped_scaled_within_1536_1152.jpg"


def extract_zillow(html: str, base_url: str) -> list[tuple[str, str]]:
    """Return the listing's gallery photos at max uncropped resolution."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        cache = data["props"]["pageProps"]["componentProps"]["gdpClientCache"]
        cache = json.loads(cache) if isinstance(cache, str) else cache
    except (KeyError, ValueError, TypeError):
        return []

    photos = []
    for entry in cache.values():
        prop = entry.get("property") if isinstance(entry, dict) else None
        if prop and prop.get("responsivePhotos"):
            photos = prop["responsivePhotos"]
            break

    urls = []
    for ph in photos:
        jpegs = (ph.get("mixedSources") or {}).get("jpeg") or []
        src = max(jpegs, key=lambda j: j.get("width", 0))["url"] if jpegs else ph.get("url")
        if not src:
            continue
        # Swap the size suffix for the largest uncropped variant Zillow serves;
        # the fallback below keeps the original if that variant 404s.
        urls.append((re.sub(r"-[a-z_0-9]+\.\w+$", "-" + ZILLOW_PREFERRED, src), src))
    return urls


def collect_images(page_url: str, include_all: bool) -> list[tuple[str, str | None]]:
    """Return a list of (url, fallback_url) in page order, deduplicated."""
    html = fetch(page_url).text
    host = urlparse(page_url).netloc.lower()

    items: list[tuple[str, str | None]] = []
    if "zillow.com" in host and not include_all:
        items = extract_zillow(html, page_url)
        if not items:
            print("  ! Zillow photo data not found; falling back to generic extraction.")
    if not items:
        items = extract_generic(html, page_url)

    seen, unique = set(), []
    for url, fb in items:
        key = url.split("#")[0]
        if key not in seen:
            seen.add(key)
            unique.append((url, fb))
    return unique


# --------------------------------------------------------------------------- #
# Downloading
# --------------------------------------------------------------------------- #

def _ext_for(url: str, content_type: str) -> str:
    ext = Path(urlparse(url).path).suffix.lower()
    if ext in IMAGE_EXTS:
        return ".jpg" if ext == ".jpeg" else ext
    guessed = mimetypes.guess_extension((content_type or "").split(";")[0].strip())
    return {".jpe": ".jpg", ".jpeg": ".jpg"}.get(guessed or "", guessed or ".img")


def download_one(idx: int, url: str, fallback: str | None, dest: Path, referer: str,
                 pad: int) -> tuple[str, str]:
    stem = f"{idx:0{pad}d}"
    existing = list(dest.glob(stem + ".*"))
    if existing:
        return "skip", existing[0].name

    headers = {"Referer": referer}
    last_err = None
    for candidate in filter(None, (url, fallback)):
        try:
            resp = fetch(candidate, headers=headers)
        except Exception as e:  # noqa: BLE001 - report and try fallback
            last_err = e
            continue
        ctype = resp.headers.get("content-type", "")
        if not ctype.startswith("image/") and Path(urlparse(candidate).path).suffix.lower() not in IMAGE_EXTS:
            return "notimg", f"{candidate} ({ctype or 'unknown type'})"
        path = dest / (stem + _ext_for(candidate, ctype))
        path.write_bytes(resp.content)
        return "ok", f"{path.name} ({len(resp.content) // 1024} KB)"
    return "fail", f"{url} -> {last_err}"


def scrape(page_url: str, base_dir: Path, workers: int, include_all: bool, name: str | None) -> int:
    folder = base_dir / (name or folder_name_from_url(page_url))
    print(f"Page:   {page_url}")
    print(f"Folder: {folder}")

    try:
        images = collect_images(page_url, include_all)
    except Exception as e:  # noqa: BLE001
        print(f"  ! Could not load page: {e}")
        return 1

    if not images:
        print("  No images found.")
        return 1

    folder.mkdir(parents=True, exist_ok=True)
    pad = max(2, len(str(len(images))))
    print(f"Found {len(images)} images, downloading with {workers} workers...")

    counts = {"ok": 0, "skip": 0, "notimg": 0, "fail": 0}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(download_one, i, u, fb, folder, page_url, pad)
                   for i, (u, fb) in enumerate(images, 1)]
        for fut in as_completed(futures):
            status, msg = fut.result()
            counts[status] += 1
            if status != "notimg":
                mark = {"ok": "+", "skip": "=", "fail": "!"}[status]
                print(f"  {mark} {msg}")

    extra = f", {counts['notimg']} non-images ignored" if counts["notimg"] else ""
    print(f"Done: {counts['ok']} downloaded, {counts['skip']} already present, "
          f"{counts['fail']} failed{extra} -> {folder.resolve()}")
    return 0 if counts["fail"] == 0 else 2


def clipboard_url() -> str | None:
    """Return the clipboard contents if they look like a single web URL (macOS)."""
    try:
        text = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if re.fullmatch(r"(https?://)?[\w.-]+\.[a-z]{2,}(/\S*)?", text, re.I):
        return text
    return None


def open_viewer(folder: Path) -> None:
    """Show the folder in the installed Image Viewer app, else the in-process viewer."""
    app = Path.home() / "Applications" / f"{VIEWER_APP}.app"
    if sys.platform == "darwin" and (app.exists() or Path("/Applications", app.name).exists()):
        subprocess.run(["open", "-a", VIEWER_APP, str(folder)], check=False)
        return
    import imgview  # imported lazily so scraping works without PySide6
    imgview.run(folder)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="imgscrape",
        description="Download every image on a web page into a folder named from the URL.",
        epilog="With no URL, the URL on the clipboard is used.")
    ap.add_argument("urls", nargs="*", metavar="URL", help="page URL(s) to scrape (default: clipboard)")
    ap.add_argument("-o", "--out", default=DEFAULT_OUT,
                    help="base directory for output folders (default: $IMGSCRAPE_DIR or %(default)s)")
    ap.add_argument("-n", "--name", help="override the folder name (single URL only)")
    ap.add_argument("-w", "--workers", type=int, default=8, help="parallel downloads (default: 8)")
    ap.add_argument("--all", action="store_true",
                    help="on Zillow, grab every image on the page instead of just the listing photos")
    ap.add_argument("--no-view", dest="view", action="store_false",
                    help="don't open the image viewer when done")
    args = ap.parse_args(argv)

    if not args.urls:
        url = clipboard_url()
        if not url:
            ap.error("no URL given and the clipboard doesn't hold one")
        print(f"Using URL from clipboard: {url}")
        args.urls = [url]

    if args.name and len(args.urls) > 1:
        ap.error("--name can only be used with a single URL")

    rc = 0
    base = Path(args.out).expanduser()
    folders = []
    for url in args.urls:
        if not urlparse(url).scheme:
            url = "https://" + url
        rc = max(rc, scrape(url, base, args.workers, args.all, args.name))
        folders.append(base / (args.name or folder_name_from_url(url)))
        print()

    if args.view:
        existing = [f for f in folders if f.is_dir()]
        if existing:
            open_viewer(existing[0])
    return rc


if __name__ == "__main__":
    sys.exit(main())
