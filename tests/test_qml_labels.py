import os
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: E402

QML = Path(__file__).resolve().parent.parent / "couriercollie" / "qml"


class LabelsTest(unittest.TestCase):
    """Text from outside shows as written, and its links open only web pages."""

    @classmethod
    def setUpClass(cls):
        cls.app = QGuiApplication.instance() or QGuiApplication([])

    def evaluate(self, expression):
        engine = QQmlEngine()
        component = QQmlComponent(engine)
        component.setData(f'import QtQuick\nimport "{QML.as_uri()}"\nQtObject {{ property var out: {expression} }}'
                          .encode(), QUrl())
        obj = component.create()
        self.assertIsNotNone(obj, component.errorString())
        return obj.property("out")

    def test_plain_escapes_and_keeps_lines(self):
        self.assertEqual(self.evaluate('Labels.plain("Updated to <img/src=https://x.example/p>\\nDone & ok")'),
                         "<html>Updated to &lt;img/src=https://x.example/p&gt;<br>Done &amp; ok</html>")
        self.assertEqual(self.evaluate('Labels.plain("")'), "")

    def test_only_web_links_open(self):
        opens = {link: self.evaluate(f'Labels.isWebLink("{link}")')
                 for link in ("https://example.com/a", "HTTP://example.com/b", "file:///home/you/.bashrc", "smb://x/y",
                              "javascript:alert(1)")}
        self.assertEqual([link for link, ok in opens.items() if ok], ["https://example.com/a", "HTTP://example.com/b"])
