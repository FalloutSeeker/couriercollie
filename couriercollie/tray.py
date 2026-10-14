"""The tray icon, while "Enable tray icon" is on (Settings): the number of updates, and Open, Check Now and
Quit. Closing the window then leaves couriercollie running here; with it off there's no tray icon, and closing the
window quits. Needs a desktop that shows tray icons (on GNOME, the AppIndicator extension).
"""

import ctypes

from PySide6.QtCore import QObject, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import integration

# Drawn at each size a tray may ask for, so the count stays sharp.
_SIZES = (16, 22, 24, 32, 48, 64)


def _give_back_memory():
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except (OSError, AttributeError):  # not glibc: nothing to do
        pass


def app_icon() -> QIcon:
    """couriercollie's icon: from the icon theme (installed with the package, or by a project folder's first run),
    else the file in the project."""
    icon = QIcon.fromTheme(integration.ICON)
    if icon.isNull():
        # Every size, not only the largest: a window's icon is handed to the desktop at its sizes, and the largest
        # alone is too big for some (X11 drops it, and the window has none).
        icon = QIcon()
        for file in integration.icon_files():
            icon.addFile(str(file))
    return icon


def with_count(icon: QIcon, count: int) -> QIcon:
    """The icon with the number of updates in a red circle at its lower right ("9+" for more), or as it is for none."""
    if count <= 0:
        return icon
    text = str(count) if count < 10 else "9+"
    badged = QIcon()
    for size in _SIZES:
        picture = icon.pixmap(size, size)
        if picture.isNull():
            picture = QPixmap(size, size)
            picture.fill(Qt.GlobalColor.transparent)
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QRectF(size * 0.4, size * 0.4, size * 0.6, size * 0.6)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#da4453"))  # Breeze's red, readable on light and dark panels
        painter.drawEllipse(circle)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(6, round(circle.height() * (0.7 if len(text) == 1 else 0.55))))
        painter.setFont(font)
        painter.setPen(QColor("white"))
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()
        badged.addPixmap(picture)
    return badged


def tooltip(count: int) -> str:
    return "couriercollie: " + ("up to date" if count == 0 else "1 update" if count == 1 else f"{count} updates")


class Tray(QObject):
    """Shown while "Enable tray icon" is on and the desktop has a tray; follows the settings and checks."""

    def __init__(self, app: QApplication, backend, window):
        super().__init__(app)
        self._app, self._backend, self._window = app, backend, window
        self._icon = app_icon()
        self._tray = QSystemTrayIcon(self)
        self._menu = QMenu()
        self._menu.addAction(QIcon.fromTheme("window"), "Open couriercollie", self._show)
        self._menu.addAction(QIcon.fromTheme("view-refresh"), "Check Now", backend.checkNow)
        self._menu.addSeparator()
        self._menu.addAction(QIcon.fromTheme("application-exit"), "Quit", app.quit)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._clicked)
        backend.settingsChanged.connect(self.refresh)
        backend.checksChanged.connect(self.refresh)
        window.visibleChanged.connect(self._visible)
        self.refresh()

    def _visible(self, visible: bool):
        # Put away in the tray, the app may sit there for days: give back the memory the window was using. (Freed
        # memory otherwise stays with the app, kept for reuse: about 40 MB after looking through a few pages.) A
        # moment later, once the window's own clean-up has run.
        if not visible:
            QTimer.singleShot(1000, _give_back_memory)

    def put_away(self):
        """Quitting: the icon goes at once (what's still updating finishes out of sight)."""
        self._tray.hide()

    @property
    def shown(self) -> bool:
        return self._tray.isVisible()

    def refresh(self):
        on = self._backend.tray_available and self._backend.settings["keepInTray"]
        # With the tray, closing the window leaves the app running; without, nothing would bring it back.
        self._app.setQuitOnLastWindowClosed(not on)
        if not on:
            self._tray.hide()
            return
        count = self._backend.checks.get("updates", 0)
        self._tray.setIcon(with_count(self._icon, count))
        self._tray.setToolTip(tooltip(count))
        self._tray.show()

    def _show(self):
        self._backend.activateRequested.emit()

    def _clicked(self, reason):
        if reason not in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            return  # the menu (right-click) opens by itself
        # Open; or, if it's already open and in front, put it away.
        if self._window.isVisible() and self._window.isActive():
            self._window.hide()
        else:
            self._show()
