#!/bin/bash
# Build "Image Viewer.app", install it to ~/Applications, make it the default
# app for opening images, and add the "Open in Image Viewer" Finder Quick Action
# for folders.  Run with SET_DEFAULT=0 to leave the default image app alone.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
APP="Image Viewer.app"
DEST="$HOME/Applications"
WORKFLOW="$HOME/Library/Services/Open in Image Viewer.workflow"

"$PY" -m pip install -q pyinstaller
QT_QPA_PLATFORM=offscreen "$PY" "$ROOT/packaging/make_icon.py" "$ROOT/packaging/ImageViewer.icns"

"$PY" -m PyInstaller --noconfirm --clean \
    --distpath "$ROOT/build/dist" --workpath "$ROOT/build/work" \
    "$ROOT/packaging/ImageViewer.spec"

mkdir -p "$DEST"
rm -rf "$DEST/$APP"
cp -R "$ROOT/build/dist/$APP" "$DEST/"
# Ad-hoc sign so Gatekeeper/LaunchServices treat the bundle as intact after copying.
codesign --force --deep --sign - "$DEST/$APP" >/dev/null 2>&1 || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST/$APP"

# Finder has no "Open With" for folders, so install a right-click Quick Action.
# The installed bundle name is the label Finder shows in the menu.
rm -rf "$WORKFLOW"
mkdir -p "$(dirname "$WORKFLOW")"
cp -R "$ROOT/packaging/open-in-imgview.workflow" "$WORKFLOW"
/System/Library/CoreServices/pbs -update >/dev/null 2>&1 || true

if [[ "${SET_DEFAULT:-1}" != 0 ]]; then
    "$PY" "$ROOT/packaging/set_default.py" com.anujsahni.imageviewer || true
fi

echo
echo "Installed: $DEST/$APP"
echo "Installed: $WORKFLOW"
