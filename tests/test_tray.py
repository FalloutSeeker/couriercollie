import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from couriercollie import tray  # noqa: E402

app = QApplication.instance() or QApplication([])


class FakeBackend(QObject):
    settingsChanged = Signal()
    checksChanged = Signal()
    activateRequested = Signal()

    def __init__(self):
        super().__init__()
        self.tray_available, self.settings, self.checks = True, {"keepInTray": False}, {"updates": 0}

    def checkNow(self):
        pass


class FakeWindow(QObject):
    visibleChanged = Signal(bool)

    def __init__(self):
        super().__init__()
        self.visible = self.active = True

    def isVisible(self):
        return self.visible

    def isActive(self):
        return self.active

    def hide(self):
        self.visible = False
        self.visibleChanged.emit(False)


@unittest.skipUnless(isinstance(app, QApplication), "needs a QApplication")
class TrayTest(unittest.TestCase):
    def test_the_count_on_the_icon(self):
        icon = tray.app_icon()
        self.assertFalse(icon.isNull())
        self.assertIs(tray.with_count(icon, 0), icon)  # nothing to show
        self.assertEqual(len(tray.with_count(icon, 12).availableSizes()), len(tray._SIZES))
        self.assertEqual([tray.tooltip(n) for n in (0, 1, 3)],
                         ["couriercollie: up to date", "couriercollie: 1 update", "couriercollie: 3 updates"])

    def test_closing_the_window_quits_unless_kept_in_the_tray(self):
        backend, window = FakeBackend(), FakeWindow()
        self.addCleanup(app.setQuitOnLastWindowClosed, True)
        t = tray.Tray(app, backend, window)
        self.assertTrue(app.quitOnLastWindowClosed())
        backend.settings["keepInTray"] = True
        backend.settingsChanged.emit()
        self.assertFalse(app.quitOnLastWindowClosed())
        # A desktop without a tray: nothing would bring the window back, so closing it quits.
        backend.tray_available = False
        backend.settingsChanged.emit()
        self.assertTrue(app.quitOnLastWindowClosed())
        self.assertFalse(t.shown)

    def test_a_click_opens_or_puts_away(self):
        from PySide6.QtWidgets import QSystemTrayIcon

        backend, window = FakeBackend(), FakeWindow()
        self.addCleanup(app.setQuitOnLastWindowClosed, True)
        t = tray.Tray(app, backend, window)
        opened = []
        backend.activateRequested.connect(lambda: opened.append(1))
        t._clicked(QSystemTrayIcon.ActivationReason.Trigger)  # open and in front: put away
        self.assertEqual((window.visible, opened), (False, []))
        t._clicked(QSystemTrayIcon.ActivationReason.Trigger)  # closed: open
        self.assertEqual(opened, [1])
        t._clicked(QSystemTrayIcon.ActivationReason.Context)  # right-click: the menu, nothing else
        self.assertEqual(opened, [1])


if __name__ == "__main__":
    unittest.main()


class GiveBackMemoryTest(unittest.TestCase):
    def test_harmless_wherever_it_runs(self):
        tray._give_back_memory()  # glibc: memory handed back; elsewhere: nothing
