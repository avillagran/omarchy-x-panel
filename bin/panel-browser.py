#!/usr/bin/env python3
"""Resolve the system browser without Omarchy's Chromium fallback or shell eval."""
import configparser
import fcntl
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from process_io import capture


def read_text(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 262144:
            raise ValueError("Unsafe or oversized browser metadata")
        data = os.read(fd, 262145)
        if len(data) > 262144:
            raise ValueError("Oversized browser metadata")
        return data.decode("utf-8")
    finally:
        os.close(fd)


def floorp_app(command):
    """Resolve the native profile, initializing a fresh installation if needed."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "floorp"
    profiles = configparser.ConfigParser(interpolation=None)
    ini = base / "profiles.ini"
    if ini.is_file():
        profiles.read_string(read_text(ini))
    if not profiles.sections() or (not any(s.startswith("Install") for s in profiles.sections())
                                   and not any(flag in command for flag in ("-P", "--profile", "-profile"))):
        # A cold browser remains running; subprocess.run(timeout=...) would kill
        # it. Let Floorp create and select its own installation-default profile.
        lock_path = Path(os.environ["XDG_RUNTIME_DIR"]) / f"x-panel-floorp-init-{os.getuid()}.lock"
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError("Unsafe Floorp initialization lock")
            deadline = time.monotonic() + 20
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ValueError("Floorp initialization is busy")
                    time.sleep(0.1)
            profiles = configparser.ConfigParser(interpolation=None)
            if ini.is_file():
                profiles.read_string(read_text(ini))
            if not any(s.startswith("Install") for s in profiles.sections()):
                subprocess.Popen([*command, "--new-tab", "about:blank"], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                while time.monotonic() < deadline:
                    profiles = configparser.ConfigParser(interpolation=None)
                    if ini.is_file():
                        profiles.read_string(read_text(ini))
                    if any(s.startswith("Install") for s in profiles.sections()):
                        break
                    time.sleep(0.1)
                else:
                    raise ValueError("Floorp did not initialize its default profile")
        finally:
            os.close(fd)
    profile = None
    for flag in ("--profile", "-profile"):
        if flag in command:
            profile = Path(command[command.index(flag) + 1])
    if profile is None and "-P" in command:
        name = command[command.index("-P") + 1]
        for section in profiles.sections():
            if section.startswith("Profile") and profiles[section].get("Name") == name:
                path = Path(profiles[section]["Path"])
                profile = base / path if profiles[section].get("IsRelative") == "1" else path
                break
        if profile is None:
            raise ValueError("Cannot find the selected Floorp profile")
    if profile is None:
        selected = next((profiles[s].get("Default") for s in profiles.sections()
                         if s.startswith("Install") and profiles[s].get("Default")), None)
        if selected:
            profile = base / selected
        else:
            for section in profiles.sections():
                if section.startswith("Profile") and profiles[section].get("Default") == "1":
                    path = Path(profiles[section]["Path"])
                    profile = base / path if profiles[section].get("IsRelative") == "1" else path
                    break
            if profile is None:
                sections = [s for s in profiles.sections() if s.startswith("Profile")]
                if len(sections) == 1:
                    entry = profiles[sections[0]]
                    path = Path(entry["Path"])
                    profile = base / path if entry.get("IsRelative") == "1" else path
    if profile is None:
        raise ValueError("Cannot find the default Floorp profile")
    store = profile / "ssb/ssb.json"
    data = json.loads(read_text(store)) if store.is_file() else {}
    for app in data.values():
        url = urlsplit(app.get("start_url", ""))
        if url.scheme == "https" and url.hostname == "x.com" and app.get("userContextId", 0) == 0:
            app_id = app["id"]
            token = re.sub(r"[^a-z0-9]+", "-", app_id.lower()).strip("-")[:64]
            return str(profile), app_id, "floorp-" + token
    app_id = "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "https://x.com/omarchy-x-panel")) + "}"
    token = app_id.strip("{}")
    return str(profile), app_id, "floorp-" + token


def browser():
    env = dict(os.environ)
    env.pop("BROWSER", None)
    desktop = ""
    for command in (["xdg-settings", "get", "default-web-browser"],
                    ["xdg-mime", "query", "default", "x-scheme-handler/https"]):
        try:
            desktop = capture(command, env=env, timeout=5, limit=4096).strip()
        except (OSError, ValueError, TimeoutError):
            desktop = ""
        if desktop:
            break
    if not desktop or "/" in desktop or not desktop.endswith(".desktop"):
        raise ValueError("No valid default browser desktop entry")
    roots = [os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))]
    roots += os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    roots.append(str(Path.home() / ".nix-profile/share"))
    entry = None
    for root in roots:
        path = Path(root) / "applications" / desktop
        if path.is_file():
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read_string(read_text(path))
            entry = config["Desktop Entry"]
            break
    if entry is None or entry.getboolean("Hidden", fallback=False):
        raise ValueError("Default browser desktop entry is unavailable")
    command = []
    for arg in shlex.split(entry["Exec"]):
        if arg in ("%u", "%U", "%f", "%F"):
            continue
        if arg == "%i":
            if entry.get("Icon"):
                command.extend(["--icon", entry["Icon"]])
            continue
        arg = arg.replace("%c", entry.get("Name", "")).replace("%k", str(path))
        if re.search(r"%(?!%)", arg.replace("%%", "")):
            raise ValueError("Unsupported desktop Exec field code")
        command.append(arg.replace("%%", "%"))
    if not command:
        raise ValueError("Default browser has no executable")
    # Inspect the executable/desktop identity, never the localized display name.
    identity = " ".join([desktop, *command]).lower()
    chromium = bool(re.search(r"chromium|google-chrome|brave|microsoft-edge|vivaldi|opera|helium", identity))
    if chromium:
        names = "chrome|chromium"
        for family, classes in (("brave", "brave"), ("microsoft-edge", "msedge|microsoft-edge"),
                                ("vivaldi", "vivaldi"), ("opera", "opera"), ("helium", "helium")):
            if family in identity:
                names = classes
                break
        # A native popup retains X's title count and sends new tabs to a normal
        # browser window. Hyprland hides its controls with client fullscreen.
        classes = names.split("|")
        if "google-chrome" in identity:
            classes = ["google-chrome", "chrome"]
        elif "chromium" in identity:
            classes = ["chromium", "chrome"]
        classes += [Path(command[0]).name, Path(desktop).stem]
        if entry.get("StartupWMClass"):
            classes.append(entry["StartupWMClass"])
        window_class = "(?i)^(" + "|".join(re.escape(name) for name in sorted(set(classes))) + ")$"
        title = r"(^| / )X( [—–-] .*)?$|^([(][0-9,]+[)] )?x\.com([/ ].*)?$"
        args = ["--new-window", "https://x.com/"]
    elif "floorp" in identity:
        profile, app_id, app_class = floorp_app(command)
        # Same launch contract as Floorp's own Linux Web App desktop entry.
        args = ["--name", app_class, "--profile", profile, "--start-ssb", app_id]
        # Floorp's Linux app-class integration is still an experiment. Some
        # versions expose only 'floorp'; claim only newly launched windows there.
        window_class = "(?i)^(floorp|" + re.escape(app_class) + ")$"
        title = r"(^| / )X( [—–-] .*)?$"
    else:
        names = {Path(command[0]).name, Path(desktop).stem}
        if entry.get("StartupWMClass"):
            names.add(entry["StartupWMClass"])
        # Native Mozilla windows use the executable name as their Wayland app ID.
        names.update(Path(arg).name for arg in command if "floorp" in arg.lower() or "firefox" in arg.lower())
        window_class = "(?i)^(" + "|".join(re.escape(name) for name in sorted(names)) + ")$"
        title = r"(^| / )X( [—–-] .*)?$|^([(][0-9,]+[)] )?x\.com([/ ].*)?$"
        args = ["--new-window", "https://x.com/"]
    result = {"command": command + args, "class": window_class, "title": title,
              "discover": not chromium and "floorp" not in identity,
              "clientFullscreen": chromium}
    if chromium:
        result.update(baseCommand=command, popup=True)
    if "floorp" in identity and not chromium:
        result.update(profile=profile, appId=app_id, baseCommand=command)
    return result


if __name__ == "__main__":
    try:
        result = browser()
        if sys.argv[1:] == ["prepare"]:
            if "appId" in result:
                subprocess.run([sys.executable, str(Path(__file__).with_name("floorp-configure.py"))],
                               input=json.dumps(result), text=True, check=True, timeout=30)
            sys.exit(0)
        if sys.argv[1:] == ["launch"]:
            if result.get("popup"):
                subprocess.run([sys.executable, str(Path(__file__).with_name("chromium-popup.py"))],
                               input=json.dumps(result), text=True, check=True, timeout=20)
                sys.exit(0)
            os.execvp("uwsm-app", ["uwsm-app", "--", *result["command"]])
        print(json.dumps(result))
    except (OSError, ValueError, KeyError, IndexError, configparser.Error, subprocess.SubprocessError) as error:
        print(f"Cannot resolve default browser: {error}", file=sys.stderr)
        sys.exit(1)
