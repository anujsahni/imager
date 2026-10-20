# Image Scraper & Viewer

Two small macOS command-line tools:

- **`imgscrape`** downloads every image on a web page into a folder named after the page, then opens it in the viewer.
- **`imgview`** opens a folder of images in **Image Viewer**, a fast, keyboard-driven Mac app for flipping through photos.

## Setup

Requires macOS and Python 3.10+ (used only to install and build; you never run Python yourself).

```sh
./install.sh --app
```

This:

1. creates `.venv` and installs `requirements.txt`
2. puts the `imgscrape` and `imgview` commands in `~/.local/bin`
3. builds **Image Viewer.app** into `~/Applications` (because of `--app`)

Leave off `--app` to skip rebuilding the app, e.g. when you've only changed the scraper. If `~/.local/bin` isn't on your `PATH`, the script prints the line to add to `~/.zshrc`. It's safe to re-run.

## Using `imgscrape`

The quickest way: copy a page's URL in your browser, then run

```sh
imgscrape
```

With no URL, it uses the one on the clipboard. You can also pass one or more URLs:

```sh
imgscrape https://www.arhomes.com/model/lumina/
imgscrape URL1 URL2 URL3
```

Images are saved to `~/Pictures/Scraped/<folder>/` as `01.webp`, `02.jpg`, … in page order. The folder name is taken from the most descriptive part of the URL, e.g. `.../model/lumina/` becomes `lumina`. When it finishes, the first folder opens in Image Viewer.

| Option | Description |
| --- | --- |
| `-o DIR` | Base output directory (default `~/Pictures/Scraped`, or `$IMGSCRAPE_DIR`) |
| `-n NAME` | Use this folder name instead of one derived from the URL (single URL only) |
| `-w N` | Parallel downloads (default 8) |
| `--all` | On Zillow, grab every image on the page, not just the listing photos |
| `--no-view` | Don't open the viewer when done |

Re-running on the same page skips files that are already downloaded.

### What it picks up

- `<img>` and `<picture>` sources, choosing the largest `srcset` candidate
- Lazy-loaded and carousel/slider images that aren't on screen yet: `data-src`, `data-lazy` (slick), `data-flickity-lazyload`, `data-splide-lazy`, and similar attributes
- Slides drawn as CSS backgrounds (`style="background-image:url(...)"`, `data-bg`, `data-background`)
- Lightbox / gallery links that point straight at an image file
- `og:image` and `twitter:image`
- **WordPress:** resized copies like `photo-768x461.webp` are swapped for the full-size original, falling back to the resized copy if the original isn't there
- **Zillow:** only the listing's own photo gallery, at the largest uncropped size

It doesn't run JavaScript. A carousel that only fetches more slides from the server when you click "next" won't be fully captured.

Requests impersonate Chrome's TLS fingerprint (via `curl_cffi`), which gets past most bot walls that block plain `requests`.

## Using `imgview`

```sh
imgview                        # the current folder
imgview ~/Pictures/Scraped/lumina
imgview photo.jpg              # that photo's folder, starting at photo.jpg
```

It opens the folder in Image Viewer.app. Images are sorted by name in natural order, so `2.jpg` comes before `10.jpg`. A folder with no images shows a "No images" message; press **O** to pick another folder.

### Keys

| Key | Action |
| --- | --- |
| ← / → | Previous / next image (wraps around) |
| Home / End | First / last image |
| F, Enter, double-click | Toggle fullscreen |
| Esc | Leave fullscreen |
| Space, Z | Toggle fit-to-window / actual size (drag to pan) |
| Two-finger drag | Zoom in (down) / out (up) at the pointer |
| O | Open another folder |
| Q, ⌘W | Quit |

The on-screen arrows and controls fade out after a couple of seconds and come back when you move the mouse.

### Other ways to open it

`install.sh --app` also sets Image Viewer up in Finder:

- **Double-click an image.** Image Viewer becomes the default app for JPEG, PNG, GIF, WebP, HEIC, TIFF and BMP. To keep your current default, build with `SET_DEFAULT=0 ./install.sh --app`.
- **Right-click a folder → Quick Actions → Open in Image Viewer.**
- **Drag** a folder or image onto the app's Dock icon.

## Project layout

```
imgscrape.py          scraper (CLI)
imgview.py            Image Viewer source (PySide6, packaged as an app by packaging/)
bin/imgscrape         `imgscrape` command: runs imgscrape.py with the project's .venv
bin/imgview           `imgview` command: opens a folder in Image Viewer.app
install.sh            sets up .venv, installs both commands, builds the app with --app
requirements.txt
packaging/            PyInstaller spec, icon, build script, Finder Quick Action
```
