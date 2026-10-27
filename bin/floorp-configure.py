#!/usr/bin/env python3
"""Prepare Floorp's native X Web App without editing a running prefs.js."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import importlib.util

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("panel_browser", Path(__file__).with_name("panel-browser.py"))
browser = importlib.util.module_from_spec(spec)
spec.loader.exec_module(browser)


def register(profile, app_id):
    directory = Path(profile) / "ssb"
    if directory.is_symlink() or not Path(profile).is_dir():
        raise ValueError("Unsafe Floorp app directory")
    directory.mkdir(mode=0o700, exist_ok=True)
    directory.chmod(0o700)
    if (directory / "ssb.json").exists():
        (directory / "ssb.json").chmod(0o600, follow_symlinks=False)
    path = directory / "ssb.json"
    original = browser.read_text(path) if path.exists() else None
    data = json.loads(original) if original is not None else {}
    if any(app.get("id") == app_id for app in data.values()):
        return
    # This is the native DataStore manifest contract, not a separate profile.
    data["https://x.com/:0"] = {
        "id": app_id, "name": "X", "short_name": "X", "start_url": "https://x.com/",
        "scope": "https://x.com/", "display": "standalone", "userContextId": 0,
        "icon": "https://abs.twimg.com/favicons/twitter.3.ico",
    }
    fd, name = tempfile.mkstemp(dir=directory, prefix=".x-panel-")
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(data, output)
            output.flush()
            os.fsync(output.fileno())
        current = browser.read_text(path) if path.exists() else None
        if current != original:
            raise ValueError("Floorp app registry changed; retry opening the panel")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def hide_toolbar(command, profile):
    import gi
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    def call(method, parameters):
        return bus.call_sync("org.a11y.Bus", "/org/a11y/bus", "org.freedesktop.DBus.Properties",
                             method, parameters, None, Gio.DBusCallFlags.NONE, 3000, None)
    previous = call("Get", GLib.Variant("(ss)", ("org.a11y.Status", "IsEnabled"))).unpack()[0]
    if not previous:
        call("Set", GLib.Variant("(ssv)", ("org.a11y.Status", "IsEnabled", GLib.Variant("b", True))))
    try:
        _hide_toolbar(command, profile)
    finally:
        if not previous:
            call("Set", GLib.Variant("(ssv)", ("org.a11y.Status", "IsEnabled", GLib.Variant("b", False))))


def _hide_toolbar(command, profile):
    # Floorp observes this preference live. Use its own settings control, never
    # overwrite prefs.js or restart the user's browser to apply the change.
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    Atspi.set_timeout(1000, 1000)

    budget = [0]
    def visit():
        budget[0] += 1
        if budget[0] > 2000:
            raise ValueError("Floorp accessibility tree exceeds budget")

    def tabs(node, depth=0):
        visit()
        if node is None or depth > 6:
            return
        if node.get_role_name() == "document web":
            return
        if node.get_role_name() == "page tab":
            yield node
            return
        for index in range(min(node.get_child_count(), 80)):
            yield from tabs(node.get_child_at_index(index), depth + 1)

    def apps():
        desktop = Atspi.get_desktop(0)
        for index in range(min(desktop.get_child_count(), 80)):
            app = desktop.get_child_at_index(index)
            if app is not None and app.get_name() == "Floorp":
                yield app

    previous = [tab for app in apps() for tab in tabs(app)]
    subprocess.Popen([*command, "--profile", profile, "--new-tab", "about:hub#/features/webapps"],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def controls(node, depth=0):
        visit()
        if node is None or depth > 22:
            return
        name = node.get_name()
        if name == "Show Toolbar" and node.get_role_name() == "toggle button":
            yield node
            return
        # Restrict document inspection to the settings page we just opened.
        if node.get_role_name() == "document web" and name != "Floorp Hub":
            return
        for index in range(min(node.get_child_count(), 80)):
            yield from controls(node.get_child_at_index(index), depth + 1)

    started = time.monotonic()
    deadline = started + 18
    retried = False
    while time.monotonic() < deadline:
        budget[0] = 0
        for app in apps():
            for control in controls(app):
                if control.get_state_set().contains(Atspi.StateType.CHECKED):
                    if not control.get_action_iface().do_action(0):
                        raise ValueError("Floorp refused the toolbar setting")
                    time.sleep(0.2)
                    break
                # Close only the settings tab this invocation created.
                for tab in list(tabs(app)):
                    if tab in previous or tab.get_name() != "Floorp Hub":
                        continue
                    for index in range(min(tab.get_child_count(), 80)):
                        close = tab.get_child_at_index(index)
                        if close is not None and "tab-close-button" in close.get_attributes().get("class", "").split():
                            close.get_action_iface().do_action(0)
                            break
                return
        # A first-run browser can create profiles.ini before its remote command
        # listener is ready. Retry once after startup, without spawning a loop.
        if not retried and time.monotonic() - started > 5:
            subprocess.Popen([*command, "--profile", profile, "--new-tab", "about:hub#/features/webapps"],
                             start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            retried = True
        time.sleep(0.2)
    raise ValueError("Floorp Web App toolbar setting could not be verified")


if __name__ == "__main__":
    try:
        info = json.loads(sys.stdin.read(262145))
        register(info["profile"], info["appId"])
        hide_toolbar(info["baseCommand"], info["profile"])
    except Exception as error:
        print(f"Cannot prepare Floorp X panel: {error}", file=sys.stderr)
        sys.exit(1)
