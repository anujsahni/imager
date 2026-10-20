#!/usr/bin/env python3
"""Browse a folder of images with the keyboard or on-screen arrows.

Usage:
    imgview.py [FOLDER_OR_IMAGE]

With no argument a folder picker opens. Passing an image file opens its folder
starting at that image.

Keys:
    Left / Right        previous / next image (wraps around)
    Home / End          first / last image
    F, Enter, dbl-click toggle fullscreen (back to the original window size)
    Esc                 leave fullscreen
    Space, Z            toggle fit-to-window / actual size (drag to pan)
    two-finger drag     down to zoom in, up to zoom out (at the pointer)
    O                   open another folder
    Q, Cmd+W            quit
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImageReader, QKeySequence,
                           QPainter, QPainterPath, QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QFileDialog, QHBoxLayout,
                               QLabel, QMainWindow, QPushButton, QWidget)

SUPPORTED = {"." + bytes(f).decode() for f in QImageReader.supportedImageFormats()} - {".pdf"}
HIDE_CONTROLS_MS = 2500
CACHE_SIZE = 5
ZOOM_STEP = 1.0015          # zoom factor per unit of scroll delta (120 = one wheel notch)
MAX_ZOOM = 32.0


def natural_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def list_images(folder: Path) -> list[Path]:
    return sorted((p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED
                   and not p.name.startswith(".")), key=natural_key)


# --------------------------------------------------------------------------- #
# Widgets
# --------------------------------------------------------------------------- #

class ArrowButton(QAbstractButton):
    """Round translucent button with a chevron pointing left or right."""

    def __init__(self, direction: str, parent: QWidget):
        super().__init__(parent)
        self.direction = direction
        self.setFixedSize(60, 60)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Previous (←)" if direction == "left" else "Next (→)")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        alpha = 200 if self.isDown() else 160 if self.underMouse() else 95
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 20, 20, alpha))
        p.drawEllipse(self.rect().adjusted(2, 2, -2, -2))

        pen = QPen(QColor(255, 255, 255, 235), 3.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        c = QPointF(self.width() / 2, self.height() / 2)
        dx, dy = 6, 12
        path = QPainterPath()
        if self.direction == "left":
            path.moveTo(c.x() + dx, c.y() - dy)
            path.lineTo(c.x() - dx, c.y())
            path.lineTo(c.x() + dx, c.y() + dy)
        else:
            path.moveTo(c.x() - dx, c.y() - dy)
            path.lineTo(c.x() + dx, c.y())
            path.lineTo(c.x() - dx, c.y() + dy)
        p.drawPath(path)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class ImageCanvas(QWidget):
    """Draws the current image, either fitted to the window or at a free zoom level."""

    zoomed = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.pixmap: QPixmap | None = None
        self.fit = True
        self.scale = 1.0                  # image px -> device px when not fitted (1 = actual size)
        self.offset = QPointF(0, 0)       # pan offset when not fitted
        self._drag_from: QPointF | None = None
        self._scaled: QPixmap | None = None
        self._scaled_for: tuple | None = None
        self.message = ""

    def set_pixmap(self, pixmap: QPixmap | None, message: str = ""):
        self.pixmap, self.message = pixmap, message
        self.offset = QPointF(0, 0)
        self._scaled = None
        self.update()

    def set_fit(self, fit: bool):
        self.fit = fit
        self.scale = 1.0
        self.offset = QPointF(0, 0)
        self.setCursor(Qt.ArrowCursor if fit else Qt.OpenHandCursor)
        self.update()

    def zoom_percent(self) -> int:
        if not self.pixmap:
            return 100
        return round((self._fit_scale() if self.fit else self.scale) * 100)

    def _fit_scale(self) -> float:
        pw, ph = self.pixmap.width(), self.pixmap.height()
        dpr = self.devicePixelRatioF()
        # Scale up or down so the image fills the window (letterboxed, aspect kept).
        return min(self.width() * dpr / pw, self.height() * dpr / ph)

    def _clamp_offset(self):
        k = self.scale / self.devicePixelRatioF()
        pw, ph = self.pixmap.width() * k, self.pixmap.height() * k
        mx, my = max(0.0, (pw - self.width()) / 2), max(0.0, (ph - self.height()) / 2)
        self.offset = QPointF(max(-mx, min(mx, self.offset.x())), max(-my, min(my, self.offset.y())))

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(18, 18, 18))
        if not self.pixmap:
            p.setPen(QColor(170, 170, 170))
            p.setFont(QFont(self.font().family(), 16))
            p.drawText(self.rect(), Qt.AlignCenter, self.message)
            return

        dpr = self.devicePixelRatioF()
        if self.fit:
            key = (self.width(), self.height(), dpr, self.pixmap.cacheKey())
            if self._scaled_for != key:
                s = self._fit_scale()
                size = QSize(round(self.pixmap.width() * s), round(self.pixmap.height() * s))
                self._scaled = self.pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self._scaled.setDevicePixelRatio(dpr)
                self._scaled_for = key
            img = self._scaled
            w, h = img.width() / dpr, img.height() / dpr
            p.drawPixmap(QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), img, QRectF(img.rect()))
        else:
            self._clamp_offset()
            if self.scale != 1.0:
                p.setRenderHint(QPainter.SmoothPixmapTransform)
            w, h = self.pixmap.width() * self.scale / dpr, self.pixmap.height() * self.scale / dpr
            x = (self.width() - w) / 2 + self.offset.x()
            y = (self.height() - h) / 2 + self.offset.y()
            p.drawPixmap(QRectF(x, y, w, h), self.pixmap, QRectF(self.pixmap.rect()))

    # Panning in actual-size mode
    def mousePressEvent(self, e):
        if not self.fit and e.button() == Qt.LeftButton:
            self._drag_from = e.position()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            self.offset += e.position() - self._drag_from
            self._drag_from = e.position()
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag_from is not None:
            self._drag_from = None
            self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(e)

    # Two-finger trackpad drag (or mouse wheel): fingers down zooms in, fingers up zooms out.
    def wheelEvent(self, e):
        dy = e.angleDelta().y()
        if not self.pixmap or dy == 0:
            return super().wheelEvent(e)
        # With macOS "natural scrolling" Qt flips the delta and sets inverted(); undo that so
        # the direction always follows the fingers, whatever the system setting.
        fingers_down = dy if e.inverted() else -dy
        self.zoom_by(ZOOM_STEP ** fingers_down, e.position())
        e.accept()

    def zoom_by(self, factor: float, anchor: QPointF):
        """Zoom keeping the image point under `anchor` (widget coords) where it is."""
        fit_scale = self._fit_scale()
        old = fit_scale if self.fit else self.scale
        new = max(min(fit_scale, 1.0) / 4, min(MAX_ZOOM, old * factor))
        if new == old:
            return
        if self.fit:
            self.fit = False
            self.offset = QPointF(0, 0)
            self.setCursor(Qt.OpenHandCursor)
        center = QPointF(self.width() / 2, self.height() / 2)
        rel = anchor - center - self.offset
        self.offset = anchor - center - rel * (new / old)
        self.scale = new
        self.update()
        self.zoomed.emit()


HUD_STYLE = """
QWidget#hud { background: rgba(15, 15, 15, 185); border-radius: 12px; }
QLabel { color: #eee; font-size: 13px; padding: 0 6px; }
QPushButton {
    color: #eee; background: rgba(255, 255, 255, 28); border: none;
    border-radius: 7px; padding: 6px 12px; font-size: 13px;
}
QPushButton:hover { background: rgba(255, 255, 255, 60); }
QPushButton:pressed { background: rgba(255, 255, 255, 90); }
"""


class Viewer(QMainWindow):
    def __init__(self, start: Path | None):
        super().__init__()
        self.setWindowTitle("Image Viewer")
        self.resize(1200, 820)
        self.images: list[Path] = []
        self.index = 0
        self.cache: dict[Path, QPixmap] = {}

        self.canvas = ImageCanvas(self)
        self.setCentralWidget(self.canvas)
        self.canvas.zoomed.connect(self._update_hud)

        self.prev_btn = ArrowButton("left", self.canvas)
        self.next_btn = ArrowButton("right", self.canvas)
        self.prev_btn.clicked.connect(self.prev)
        self.next_btn.clicked.connect(self.next)

        self.hud = QWidget(self.canvas, objectName="hud")
        self.hud.setAttribute(Qt.WA_StyledBackground)
        self.hud.setStyleSheet(HUD_STYLE)
        lay = QHBoxLayout(self.hud)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        self.open_btn = QPushButton("Open folder…")
        self.info = QLabel()
        self.zoom_btn = QPushButton()
        self.fs_btn = QPushButton()
        for b in (self.open_btn, self.zoom_btn, self.fs_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
        self.open_btn.clicked.connect(self.choose_folder)
        self.zoom_btn.clicked.connect(self.toggle_fit)
        self.fs_btn.clicked.connect(self.toggle_fullscreen)
        lay.addWidget(self.open_btn)
        lay.addWidget(self.info)
        lay.addWidget(self.zoom_btn)
        lay.addWidget(self.fs_btn)

        # Fade the controls out when the mouse sits still, like most photo viewers.
        self.hide_timer = QTimer(self, singleShot=True, interval=HIDE_CONTROLS_MS)
        self.hide_timer.timeout.connect(self._auto_hide)
        for w in (self.canvas, self.prev_btn, self.next_btn, self.hud):
            w.setMouseTracking(True)
        self.canvas.installEventFilter(self)

        self._bind_keys()
        self._update_hud()

        if start is not None:
            self.load(start)
        else:
            self.canvas.set_pixmap(None, "Press O or click “Open folder…” to choose a folder of images")

    # ----- setup -----------------------------------------------------------
    def _bind_keys(self):
        binds = {
            self.prev: ["Left", "Up", "PgUp", "Backspace"],
            self.next: ["Right", "Down", "PgDown"],
            self.first: ["Home"],
            self.last: ["End"],
            self.toggle_fullscreen: ["F", "Return", "Enter", "Ctrl+Meta+F"],
            self.exit_fullscreen: ["Escape"],
            self.toggle_fit: ["Space", "Z"],
            self.choose_folder: ["O", "Ctrl+O"],
            self.close: ["Q", QKeySequence.Close],
        }
        for slot, keys in binds.items():
            for k in keys:
                QShortcut(QKeySequence(k), self, slot, context=Qt.ApplicationShortcut)

    # ----- loading ---------------------------------------------------------
    def load(self, target: Path):
        target = target.expanduser().resolve()
        folder = target if target.is_dir() else target.parent
        if not folder.is_dir():
            self.canvas.set_pixmap(None, f"Not found: {target}")
            return
        self.images = list_images(folder)
        self.cache.clear()
        self.index = self.images.index(target) if target in self.images else 0
        self.setWindowTitle(f"{folder.name} — Image Viewer")
        if not self.images:
            self.canvas.set_pixmap(None, f"No images in {folder}")
            self._update_hud()
            return
        self.show_current()

    def choose_folder(self):
        start = str(self.images[0].parent) if self.images else str(Path.cwd())
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of images", start)
        if folder:
            self.load(Path(folder))

    def _pixmap(self, path: Path) -> QPixmap:
        pm = self.cache.get(path)
        if pm is None:
            reader = QImageReader(str(path))
            reader.setAutoTransform(True)       # honour EXIF rotation
            pm = QPixmap.fromImage(reader.read())
            self.cache[path] = pm
            while len(self.cache) > CACHE_SIZE:
                self.cache.pop(next(iter(self.cache)))
        return pm

    def show_current(self):
        if not self.images:
            return
        path = self.images[self.index]
        pm = self._pixmap(path)
        self.canvas.set_pixmap(pm if not pm.isNull() else None, f"Couldn't read {path.name}")
        self._update_hud()
        # Warm the cache for the neighbours so arrow presses feel instant.
        QTimer.singleShot(0, self._preload)

    def _preload(self):
        if len(self.images) > 1:
            for i in (self.index + 1, self.index - 1):
                self._pixmap(self.images[i % len(self.images)])

    # ----- navigation ------------------------------------------------------
    def _go(self, i: int):
        if self.images:
            self.index = i % len(self.images)
            self.show_current()
            self._poke_controls()

    def prev(self):
        self._go(self.index - 1)

    def next(self):
        self._go(self.index + 1)

    def first(self):
        self._go(0)

    def last(self):
        self._go(len(self.images) - 1)

    # ----- view modes ------------------------------------------------------
    def toggle_fit(self):
        self.canvas.set_fit(not self.canvas.fit)
        self._update_hud()

    def toggle_fullscreen(self):
        # showNormal() restores the window to the size/position it had before.
        if self.isFullScreen():
            self.showNormal()
        else:
            if not self.canvas.fit:
                self.canvas.set_fit(True)
            self.showFullScreen()

    def exit_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.WindowStateChange and hasattr(self, "hud"):
            self._update_hud()

    # ----- HUD / overlay ---------------------------------------------------
    def _update_hud(self):
        if self.images:
            path = self.images[self.index]
            pm = self.canvas.pixmap
            dims = f"{pm.width()}×{pm.height()}" if pm else "?"
            self.info.setText(f"{self.index + 1} / {len(self.images)}   ·   {path.name}   ·   "
                              f"{dims}   ·   {self.canvas.zoom_percent()}%")
        else:
            self.info.setText("No folder open")
        self.zoom_btn.setText("Actual size (Z)" if self.canvas.fit else "Fit to window (Z)")
        self.fs_btn.setText("Exit full screen (Esc)" if self.isFullScreen() else "Full screen (F)")
        many = len(self.images) > 1
        self.prev_btn.setVisible(many and self._controls_on())
        self.next_btn.setVisible(many and self._controls_on())
        self._layout_overlays()

    def _controls_on(self) -> bool:
        return getattr(self, "_controls_visible", True)

    def _set_controls_visible(self, visible: bool):
        self._controls_visible = visible
        many = len(self.images) > 1
        self.prev_btn.setVisible(visible and many)
        self.next_btn.setVisible(visible and many)
        self.hud.setVisible(visible)
        if self.canvas.fit:
            self.canvas.setCursor(Qt.ArrowCursor if visible else Qt.BlankCursor)

    def _auto_hide(self):
        hovering = any(w.isVisible() and w.underMouse() for w in (self.hud, self.prev_btn, self.next_btn))
        if hovering:
            self.hide_timer.start()
        else:
            self._set_controls_visible(False)

    def _poke_controls(self):
        if not self._controls_on():
            self._set_controls_visible(True)
        self.hide_timer.start()

    def _layout_overlays(self):
        w, h = self.canvas.width(), self.canvas.height()
        margin = 18
        y = (h - self.prev_btn.height()) // 2
        self.prev_btn.move(margin, y)
        self.next_btn.move(w - self.next_btn.width() - margin, y)
        self.hud.adjustSize()
        hud_w = min(self.hud.sizeHint().width(), w - 2 * margin)
        self.hud.resize(hud_w, self.hud.sizeHint().height())
        self.hud.move((w - hud_w) // 2, h - self.hud.height() - margin)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if hasattr(self, "hud"):
            self._update_hud()

    def eventFilter(self, obj, e):
        if obj is self.canvas:
            t = e.type()
            if t == e.Type.MouseMove:
                self._poke_controls()
            elif t == e.Type.MouseButtonDblClick:
                self.toggle_fullscreen()
                return True
            elif t == e.Type.Resize:
                self._update_hud()
        return super().eventFilter(obj, e)


class ViewerApp(QApplication):
    """Receives Finder "Open With" / drag-onto-icon requests (macOS FileOpen events)."""

    def __init__(self, argv):
        super().__init__(argv)
        self.viewer: Viewer | None = None
        self.got_file_event = False
        self._pending: Path | None = None
        # Selecting several images and opening them sends one event per file in
        # quick succession; open the folder at the first one only.
        self._debounce = QTimer(self, singleShot=True, interval=250)
        self._debounce.timeout.connect(self._open_pending)

    def event(self, e):
        if e.type() == e.Type.FileOpen and e.file():
            self.got_file_event = True
            if self._pending is None:
                self._pending = Path(e.file())
            self._debounce.start()
            return True
        return super().event(e)

    def _open_pending(self):
        path, self._pending = self._pending, None
        if path and self.viewer:
            self.viewer.load(path)
            if self.viewer.isMinimized():
                self.viewer.showNormal()
            self.viewer.raise_()
            self.viewer.activateWindow()


def run(target: str | Path | None = None) -> int:
    if not QApplication.instance():
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or ViewerApp(sys.argv[:1])
    app.setApplicationName("Image Viewer")
    viewer = Viewer(Path(target) if target else None)
    if isinstance(app, ViewerApp):
        app.viewer = viewer
    viewer.show()
    viewer.raise_()
    viewer.activateWindow()
    viewer._poke_controls()

    if target is None:
        # Launched with nothing to show: offer the folder picker, unless Finder
        # is about to hand us a file (its FileOpen event arrives just after launch).
        def maybe_pick():
            if not getattr(app, "got_file_event", False) and not viewer.images:
                viewer.choose_folder()
        QTimer.singleShot(600, maybe_pick)
    return app.exec()


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Browse a folder of images (← / → to navigate, F for full screen).")
    ap.add_argument("target", nargs="?", help="folder of images, or an image to start at (default: pick one)")
    # parse_known_args: macOS may append its own flags (e.g. -psn_0_12345) when launching an app.
    args, _ = ap.parse_known_args(argv)
    return run(args.target)


if __name__ == "__main__":
    sys.exit(main())
