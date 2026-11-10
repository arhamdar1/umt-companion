"""
app.py

The starting point of UMT Companion. Run this file to start the whole app:

    python src\\app.py

Startup:
  1. a crisp splash screen fades in, with a loading bar
  2. it fades out and the main window fades in
  3. the tray icon and background jobs start

The UC icon is set for the whole app, so the window title bars, the Logins
window and the tray icon all show the same logo.

Closing the window keeps the app running in the tray. Use "Quit" in the
tray menu to fully close it.
"""

import sys

from PyQt6.QtCore import QPropertyAnimation, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon, QWidget

import db
from app_icon import make_app_icon
from gui import APP_VERSION, DEVELOPER, MainWindow
from scheduler import start_background_sync
from tray import create_tray

APP_NAME = "UMT Companion"
TAGLINE = "Deadlines, attendance and reminders in one place"

SPLASH_W = 520              # size in normal (100%) units; Windows scales it for you
SPLASH_H = 320
SPLASH_MS = 2600            # how long the splash stays fully visible
FADE_MS = 450               # how long each fade (in or out) takes
TICK_MS = 20                # how often the loading bar moves


class SplashScreen(QWidget):
    """A frameless, rounded, see-through window that paints the splash itself."""

    def __init__(self):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(SPLASH_W, SPLASH_H)
        self.progress = 0.0     # 0.0 to 1.0, moves the loading bar

        self._center_on_screen()

        self.bar_timer = QTimer(self)
        self.bar_timer.timeout.connect(self._advance_bar)
        self.bar_timer.start(TICK_MS)

    def _center_on_screen(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center() - self.rect().center())

    def _advance_bar(self):
        self.progress = min(1.0, self.progress + TICK_MS / SPLASH_MS)
        self.update()
        if self.progress >= 1.0:
            self.bar_timer.stop()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w, h = self.width(), self.height()

        # The rounded card shape. Everything below is clipped to it.
        card = QPainterPath()
        card.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 24, 24)

        # Background: dark gradient, same as the main window
        background = QLinearGradient(0, 0, w, h)
        background.setColorAt(0.0, QColor("#0d1322"))
        background.setColorAt(0.5, QColor("#141a33"))
        background.setColorAt(1.0, QColor("#24173f"))
        painter.fillPath(card, background)

        # Soft glowing spots, clipped inside the card
        painter.save()
        painter.setClipPath(card)
        painter.setPen(Qt.PenStyle.NoPen)
        self._glow(painter, w * 0.9, h * 0.05, w * 0.6, QColor(79, 124, 255, 80))
        self._glow(painter, w * 0.05, h * 0.95, w * 0.55, QColor(160, 90, 255, 60))
        painter.restore()

        # Thin light border
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(card)

        # Logo tile: blue to purple square with "UC"
        logo = QRectF(w / 2 - 44, 40, 88, 88)
        logo_gradient = QLinearGradient(logo.topLeft(), logo.bottomRight())
        logo_gradient.setColorAt(0.0, QColor("#4f7cff"))
        logo_gradient.setColorAt(1.0, QColor("#9b5cff"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(logo_gradient)
        painter.drawRoundedRect(logo, 22, 22)

        painter.setPen(QColor("#ffffff"))
        painter.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        painter.drawText(logo, Qt.AlignmentFlag.AlignCenter, "UC")

        # App name
        painter.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        painter.drawText(QRectF(0, 146, w, 40), Qt.AlignmentFlag.AlignCenter, APP_NAME)

        # Tagline
        painter.setPen(QColor("#8fb8ff"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRectF(0, 186, w, 24), Qt.AlignmentFlag.AlignCenter, TAGLINE)

        # Developer name
        painter.setPen(QColor("#e8ecf5"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.drawText(QRectF(0, 226, w, 26), Qt.AlignmentFlag.AlignCenter, DEVELOPER)

        # Loading bar near the bottom
        bar_left, bar_right, bar_y = 90.0, w - 90.0, h - 40.0
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 25))
        painter.drawRoundedRect(QRectF(bar_left, bar_y, bar_right - bar_left, 4), 2, 2)

        fill_width = (bar_right - bar_left) * self.progress
        if fill_width > 0:
            fill_gradient = QLinearGradient(bar_left, 0, bar_right, 0)
            fill_gradient.setColorAt(0.0, QColor("#4f7cff"))
            fill_gradient.setColorAt(1.0, QColor("#9b5cff"))
            painter.setBrush(fill_gradient)
            painter.drawRoundedRect(QRectF(bar_left, bar_y, fill_width, 4), 2, 2)

        # Version, top-right corner
        painter.setPen(QColor("#7d8899"))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            QRectF(w - 110, 14, 96, 20),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"v{APP_VERSION}",
        )

        painter.end()

    @staticmethod
    def _glow(painter, cx, cy, radius, color):
        """A soft round light that fades to nothing at its edge."""
        glow = QRadialGradient(cx, cy, radius)
        glow.setColorAt(0.0, color)
        fade_out = QColor(color)
        fade_out.setAlpha(0)
        glow.setColorAt(1.0, fade_out)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))


def make_fade(target, start: float, end: float) -> QPropertyAnimation:
    """A smooth change of window opacity from `start` to `end`."""
    animation = QPropertyAnimation(target, b"windowOpacity", target)
    animation.setDuration(FADE_MS)
    animation.setStartValue(start)
    animation.setEndValue(end)
    return animation


def main() -> int:
    # Make Windows scaling (125%, 150%...) look crisp instead of blurry.
    # This must be set BEFORE the QApplication is created.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Closing the last window must NOT quit the app. The tray keeps it alive.
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # One icon for the whole app: window title bars, dialogs and the tray
    app.setWindowIcon(make_app_icon())

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, "System tray is not available on this computer.")
        return 1

    # Splash fades in right away
    splash = SplashScreen()
    splash.setWindowOpacity(0.0)
    splash.show()
    splash.fade_in = make_fade(splash, 0.0, 1.0)
    splash.fade_in.start()
    app.processEvents()

    db.init_db()

    window = MainWindow()                # its own fade-in runs when it is shown
    tray = create_tray(app, window)      # keep a reference so it is not garbage-collected
    scheduler = start_background_sync()

    # When the app quits, stop the background jobs cleanly
    app.aboutToQuit.connect(lambda: scheduler.shutdown(wait=False))

    def finish_startup():
        """Show the main window and close the splash."""
        window.show()
        splash.close()

    def fade_out_splash():
        """Fade the splash out, then open the main window."""
        splash.fade_out = make_fade(splash, 1.0, 0.0)
        splash.fade_out.finished.connect(finish_startup)
        splash.fade_out.start()

    QTimer.singleShot(SPLASH_MS, fade_out_splash)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())