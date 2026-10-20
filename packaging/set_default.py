#!/usr/bin/env python3
"""Make Image Viewer the default app for opening images (double-click in Finder).

Usage:
    set_default.py [BUNDLE_ID]
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys

BUNDLE_ID = "com.anujsahni.imageviewer"
# Keep in sync with CFBundleDocumentTypes in ImageViewer.spec.
IMAGE_TYPES = [
    "public.jpeg", "public.png", "com.compuserve.gif", "org.webmproject.webp",
    "public.heic", "public.heif", "public.tiff", "com.microsoft.bmp", "public.jpeg-2000",
]
K_LS_ROLES_ALL = 0xFFFFFFFF
K_CF_STRING_ENCODING_UTF8 = 0x08000100

cf = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation"))
cs = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreServices"))
cf.CFStringCreateWithCString.restype = ctypes.c_void_p
cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
cf.CFRelease.argtypes = [ctypes.c_void_p]
cs.LSSetDefaultRoleHandlerForContentType.restype = ctypes.c_int32
cs.LSSetDefaultRoleHandlerForContentType.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]


def cfstr(s: str) -> ctypes.c_void_p:
    return cf.CFStringCreateWithCString(None, s.encode(), K_CF_STRING_ENCODING_UTF8)


def main(argv: list[str]) -> int:
    bundle = cfstr(argv[0] if argv else BUNDLE_ID)
    failed = 0
    for uti in IMAGE_TYPES:
        t = cfstr(uti)
        err = cs.LSSetDefaultRoleHandlerForContentType(t, K_LS_ROLES_ALL, bundle)
        cf.CFRelease(t)
        if err:
            print(f"  could not set default for {uti} (error {err})", file=sys.stderr)
            failed += 1
    cf.CFRelease(bundle)
    print(f"Default image viewer set for {len(IMAGE_TYPES) - failed}/{len(IMAGE_TYPES)} image types")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
