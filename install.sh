#!/bin/bash
# Set up the virtualenv and put the `imgscrape` and `imgview` commands on
# your PATH.  Pass --app to also build and install Image Viewer.app.
# Safe to re-run.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
    echo "Creating virtualenv in $ROOT/.venv"
    python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -m pip install -q --upgrade pip
"$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/requirements.txt"

mkdir -p "$BIN_DIR"
for cmd in imgscrape imgview; do
    chmod +x "$ROOT/bin/$cmd"
    ln -sf "$ROOT/bin/$cmd" "$BIN_DIR/$cmd"
    echo "Installed: $BIN_DIR/$cmd -> $ROOT/bin/$cmd"
done

if [[ "${1:-}" == "--app" ]]; then
    "$ROOT/packaging/build_app.sh"
elif [[ ! -d "$HOME/Applications/Image Viewer.app" && ! -d "/Applications/Image Viewer.app" ]]; then
    echo "Note: Image Viewer.app is not installed; imgview needs it. Run: $0 --app"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "Note: $BIN_DIR is not on your PATH. Add this to ~/.zshrc:"
       echo "    export PATH=\"$BIN_DIR:\$PATH\"" ;;
esac
