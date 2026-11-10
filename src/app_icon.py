"""
app_icon.py

The UMT Companion icon: a blue-to-purple tile with "UC" in it.
It is drawn in code, so no image file is needed. The same look as the splash.
"""

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)   # Windows uses different sizes in different places


def _draw_tile(size: int) -> QPixmap:
    """Draw the UC tile at one size."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    rect = QRectF(0, 0, size, size)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0.0, QColor("#4f7cff"))
    gradient.setColorAt(1.0, QColor("#9b5cff"))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, size * 0.24, size * 0.24)

    font = QFont("Segoe UI")
    font.setBold(True)
    font.setPixelSize(max(8, int(size * 0.42)))   # text size scales with the tile
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "UC")

    painter.end()
    return pixmap


def make_app_icon() -> QIcon:
    """The icon in every size Windows might need. Call it after QApplication is created."""
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(_draw_tile(size))
    return icon