# PyInstaller spec for "Image Viewer.app".  Build with packaging/build_app.sh.
# -*- mode: python -*-

from pathlib import Path

ROOT = Path(SPECPATH).parent
APP_NAME = "Image Viewer"

a = Analysis(
    [str(ROOT / "imgview.py")],
    pathex=[str(ROOT)],
    excludes=["tkinter", "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick",
              "PySide6.QtWebEngineCore", "PySide6.QtMultimedia", "PySide6.Qt3DCore",
              "PySide6.QtTest", "curl_cffi", "bs4"],
)
pyz = PYZ(a.pure)

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=APP_NAME,
          console=False, argv_emulation=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=APP_NAME, upx=False)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ROOT / "packaging" / "ImageViewer.icns"),
    bundle_identifier="com.anujsahni.imageviewer",
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": "1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # Lets Finder offer this app under "Open With" for images, and accept
        # folders dropped onto the Dock/app icon.
        "CFBundleDocumentTypes": [
            {
                "CFBundleTypeName": "Image",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.image", "public.jpeg", "public.png",
                                       "org.webmproject.webp", "com.compuserve.gif",
                                       "public.heic", "public.heif", "public.tiff",
                                       "com.microsoft.bmp", "public.jpeg-2000"],
            },
            {
                "CFBundleTypeName": "Folder",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["public.folder"],
            },
        ],
    },
)
