#!/usr/bin/env python3
"""Open a native Chromium popup using the browser's own window.open action."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_io import capture


def hypr(*args):
    output = capture(["hyprctl", *args], timeout=3)
    if output.strip().startswith("error"):
        raise RuntimeError("Compositor operation failed")
    return output


def clients():
    data = hypr("clients", "-j")
    if len(data) > 262144:
        raise RuntimeError("Oversized compositor response")
    return json.loads(data)


def dispatch(command):
    hypr("dispatch", command)


def launch(info):
    token = secrets.token_hex(16)
    title = "X Panel Launch " + token
    page = ("<!doctype html><meta charset=utf-8><title>" + title + "</title>"
            "<button autofocus onclick=\"window.open('https://x.com/', '_blank',"
            "'popup,width=642,height=806')\">Open X</button>").encode()
    before = {c["address"] for c in clients()}

    # Generated static page only; no listener, credentials or user content.
    directory = tempfile.TemporaryDirectory(prefix=".x-panel-launch-", dir=os.environ["XDG_RUNTIME_DIR"])
    page_path = Path(directory.name) / "launch.html"
    fd = os.open(page_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(page)
    launcher = None
    try:
        url = page_path.as_uri()
        subprocess.Popen(["uwsm-app", "--", *info["baseCommand"], "--new-window", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            candidates = [c for c in clients() if c["address"] not in before and c["title"].startswith(title)
                          and re.search(info["class"], c.get("class", ""))]
            if len(candidates) == 1:
                launcher = candidates[0]
                break
            time.sleep(0.1)
        if launcher is None:
            raise RuntimeError("Chromium did not open its panel launcher")
        address = launcher["address"]
        if not re.fullmatch(r"0x[0-9a-fA-F]+", address):
            raise RuntimeError("Invalid launcher address")
        # This button belongs to our nonce-scoped, single-button page. Send
        # Enter only to that exact focused window, never to another user tab.
        dispatch('hl.dsp.focus({ window = "address:%s" })' % address)
        time.sleep(0.3)
        if json.loads(hypr("activewindow", "-j")).get("address") != address:
            raise RuntimeError("Panel launcher lost focus")
        for state in ("down", "up"):
            dispatch('hl.dsp.send_key_state({ mods = "", key = "Return", state = "%s", window = "address:%s" })' % (state, address))
        while time.monotonic() < deadline:
            candidates = [c for c in clients() if c["address"] not in before
                          and c["address"] != address
                          and re.search(info["class"], c.get("class", ""))
                          and re.search(info["title"], c.get("title", ""))]
            if len(candidates) == 1:
                panel = candidates[0]
                rundir = Path(os.environ["XDG_RUNTIME_DIR"])
                fd, name = tempfile.mkstemp(prefix=".x-panel-popup-", dir=rundir)
                try:
                    with os.fdopen(fd, "w") as output:
                        output.write("%s|%s\n" % (panel["address"], panel["pid"]))
                    os.replace(name, rundir / "x-panel.chromium-popup")
                finally:
                    Path(name).unlink(missing_ok=True)
                return
            time.sleep(0.1)
        raise RuntimeError("Chromium did not create a dedicated popup")
    finally:
        directory.cleanup()
        if launcher is not None:
            # Close only our exact nonce-titled launcher, never an X window.
            if any(c["address"] == launcher["address"] and c["title"].startswith(title) for c in clients()):
                dispatch('hl.dsp.window.close({ window = "address:%s" })' % launcher["address"])


if __name__ == "__main__":
    try:
        launch(json.loads(sys.stdin.read(262145)))
    except Exception as error:
        print("Cannot open Chromium popup: " + str(error), file=sys.stderr)
        sys.exit(1)
