"""Stand-ins for two desktop services, on the session bus, for devtools/tray_inner.py:

- a tray host (org.kde.StatusNotifierWatcher), as KDE Plasma's panel is: apps register their tray icons with it;
- a notification server (org.freedesktop.Notifications): notifications are written to $NOTIFICATIONS (one JSON object a
  line), and org.couriercollie.Test.Click(id, action) clicks one, as a person would.

Prints "ready" once both are on the bus.
"""

import json
import os

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
bus = dbus.SessionBus()
WATCHER = "org.kde.StatusNotifierWatcher"
PROPS = "org.freedesktop.DBus.Properties"


class Watcher(dbus.service.Object):
    def __init__(self):
        self.name = dbus.service.BusName(WATCHER, bus)
        super().__init__(self.name, "/StatusNotifierWatcher")
        self.items: list[str] = []
        bus.add_signal_receiver(self.owner_changed, "NameOwnerChanged", "org.freedesktop.DBus")

    def owner_changed(self, name, old, new):
        if not new:  # the app went away: its icon too
            gone = [i for i in self.items if i.split("/")[0] in (name, old)]
            for item in gone:
                self.items.remove(item)
                self.StatusNotifierItemUnregistered(item)

    @dbus.service.method(WATCHER, in_signature="s", sender_keyword="sender")
    def RegisterStatusNotifierItem(self, service, sender=None):
        # A bus name (Qt's "org.kde.StatusNotifierItem-<pid>-<n>"), or just an object path on the caller's.
        item = f"{sender}{service}" if service.startswith("/") else service
        if item not in self.items:
            self.items.append(item)
            self.StatusNotifierItemRegistered(item)

    @dbus.service.method(WATCHER, in_signature="s")
    def RegisterStatusNotifierHost(self, service):
        pass

    @dbus.service.signal(WATCHER, signature="s")
    def StatusNotifierItemRegistered(self, service):
        pass

    @dbus.service.signal(WATCHER, signature="s")
    def StatusNotifierItemUnregistered(self, service):
        pass

    def _props(self):
        return {"RegisteredStatusNotifierItems": dbus.Array(self.items, signature="s"),
                "IsStatusNotifierHostRegistered": dbus.Boolean(True), "ProtocolVersion": dbus.Int32(0)}

    @dbus.service.method(PROPS, in_signature="ss", out_signature="v")
    def Get(self, interface, name):
        return self._props()[name]

    @dbus.service.method(PROPS, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self._props()


NOTIFY = "org.freedesktop.Notifications"


class Notifications(dbus.service.Object):
    def __init__(self):
        self.name = dbus.service.BusName(NOTIFY, bus)
        super().__init__(self.name, "/org/freedesktop/Notifications")
        self.last = 0

    @dbus.service.method(NOTIFY, out_signature="as")
    def GetCapabilities(self):
        return ["actions", "body", "icon-static"]

    @dbus.service.method(NOTIFY, out_signature="ssss")
    def GetServerInformation(self):
        return "stand-in", "couriercollie tests", "1", "1.2"

    @dbus.service.method(NOTIFY, in_signature="susssasa{sv}i", out_signature="u")
    def Notify(self, app_name, replaces_id, app_icon, summary, body, actions, hints, timeout):
        self.last += 1
        record = {"id": self.last, "app_name": str(app_name), "icon": str(app_icon), "summary": str(summary),
                  "body": str(body), "actions": [str(a) for a in actions],
                  "desktop_entry": str(hints.get("desktop-entry", "")),
                  # (newer notify-send gives --icon as a hint, older as app_icon)
                  "image_path": str(hints.get("image-path", hints.get("image_path", "")))}
        with open(os.environ["NOTIFICATIONS"], "a") as f:
            f.write(json.dumps(record) + "\n")
        return self.last

    @dbus.service.method(NOTIFY, in_signature="u")
    def CloseNotification(self, notification_id):
        self.NotificationClosed(notification_id, 3)

    @dbus.service.signal(NOTIFY, signature="us")
    def ActionInvoked(self, notification_id, action):
        pass

    @dbus.service.signal(NOTIFY, signature="uu")
    def NotificationClosed(self, notification_id, reason):
        pass

    @dbus.service.method("org.couriercollie.Test", in_signature="us")
    def Click(self, notification_id, action):
        self.ActionInvoked(notification_id, action)
        self.NotificationClosed(notification_id, 2)


watcher = Watcher()
notifications = Notifications()
print("ready", flush=True)
GLib.MainLoop().run()
