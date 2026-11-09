"""
tray.py

System tray icon (the small icon near the clock).

Right-click menu:
  - Open UMT Companion : shows the main window
  - Sync Now           : runs a sync right away
  - Quit               : fully closes the app

Double-clicking the icon also opens the window.
"""

from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon


def create_tray(app: QApplication, window) -> QSystemTrayIcon:
    """Create the tray icon and connect its menu to the main window."""
    tray = QSystemTrayIcon(app)

    # Use a built-in Windows icon, so we don't need an image file yet
    tray.setIcon(app.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
    tray.setToolTip("UMT Companion")

    menu = QMenu()

    open_action = QAction("Open UMT Companion", menu)
    open_action.triggered.connect(lambda: show_window(window))
    menu.addAction(open_action)

    sync_action = QAction("Sync Now", menu)
    sync_action.triggered.connect(window.start_sync)
    menu.addAction(sync_action)

    menu.addSeparator()

    quit_action = QAction("Quit", menu)
    quit_action.triggered.connect(app.quit)
    menu.addAction(quit_action)

    tray.setContextMenu(menu)

    # Double-click opens the window
    tray.activated.connect(lambda reason: _on_activated(reason, window))

    tray.show()
    return tray


def show_window(window) -> None:
    """Bring the main window to the front."""
    window.show()
    window.raise_()
    window.activateWindow()


def _on_activated(reason, window) -> None:
    if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
        show_window(window)