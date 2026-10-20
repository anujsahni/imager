"""Render the app icon at every size macOS wants and pack it into an .icns."""

import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen)


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 1024

    # macOS-style rounded square tile
    tile = QRectF(100 * s, 100 * s, 824 * s, 824 * s)
    bg = QLinearGradient(tile.topLeft(), tile.bottomLeft())
    bg.setColorAt(0, QColor("#3b3f4a"))
    bg.setColorAt(1, QColor("#16181d"))
    p.setPen(Qt.NoPen)
    p.setBrush(bg)
    p.drawRoundedRect(tile, 185 * s, 185 * s)

    # Photo "card"
    card = QRectF(230 * s, 270 * s, 564 * s, 430 * s)
    sky = QLinearGradient(card.topLeft(), card.bottomLeft())
    sky.setColorAt(0, QColor("#5aa9ff"))
    sky.setColorAt(1, QColor("#bfe0ff"))
    clip = QPainterPath()
    clip.addRoundedRect(card, 40 * s, 40 * s)
    p.setClipPath(clip)
    p.fillRect(card, sky)
    p.setBrush(QColor("#ffd257"))
    p.drawEllipse(QPointF(640 * s, 380 * s), 52 * s, 52 * s)
    hills = QPainterPath(QPointF(230 * s, 700 * s))
    hills.lineTo(230 * s, 600 * s)
    hills.lineTo(400 * s, 440 * s)
    hills.lineTo(530 * s, 570 * s)
    hills.lineTo(610 * s, 500 * s)
    hills.lineTo(794 * s, 650 * s)
    hills.lineTo(794 * s, 700 * s)
    p.setBrush(QColor("#2f9e6e"))
    p.drawPath(hills)
    p.setClipping(False)

    # Navigation chevrons
    pen = QPen(QColor(255, 255, 255, 235), 34 * s, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    cy, dx, dy = 820 * s, 26 * s, 44 * s
    for cx, d in ((400 * s, -1), (624 * s, 1)):
        path = QPainterPath(QPointF(cx - d * dx, cy - dy))
        path.lineTo(cx + d * dx, cy)
        path.lineTo(cx - d * dx, cy + dy)
        p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 150))
    for i in range(3):
        p.drawEllipse(QPointF((470 + i * 42) * s, cy), 11 * s, 11 * s)
    p.end()
    return img


def main(out: str):
    QGuiApplication(sys.argv[:1])
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for base in (16, 32, 128, 256, 512):
            draw(base).save(str(iconset / f"icon_{base}x{base}.png"))
            draw(base * 2).save(str(iconset / f"icon_{base}x{base}@2x.png"))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", out], check=True)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "ImageViewer.icns")
