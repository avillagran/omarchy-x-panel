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
import tempfile
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


DESKTOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.desktop$")


def data_roots():
    roots = [os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))]
    roots += os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")
    roots.append(str(Path.home() / ".nix-profile/share"))
    return roots


def desktop_entry(desktop):
    """First entry with this id in XDG precedence order, or None."""
    for root in data_roots():
        path = Path(root) / "applications" / desktop
        if path.is_file():
            config = configparser.ConfigParser(interpolation=None, strict=False)
            config.read_string(read_text(path))
            return config["Desktop Entry"], path
    return None, None


def is_browser(entry):
    return (entry is not None and entry.get("Exec")
            and "WebBrowser" in entry.get("Categories", "").split(";")
            and not entry.getboolean("Hidden", fallback=False)
            and not entry.getboolean("NoDisplay", fallback=False))


def default_desktop():
    env = dict(os.environ)
    env.pop("BROWSER", None)
    for command in (["xdg-settings", "get", "default-web-browser"],
                    ["xdg-mime", "query", "default", "x-scheme-handler/https"]):
        try:
            desktop = capture(command, env=env, timeout=5, limit=4096).strip()
        except (OSError, ValueError, TimeoutError):
            desktop = ""
        if desktop:
            return desktop
    return ""


def list_browsers():
    """Installed, visible web browsers: the only choices the panel accepts."""
    found, budget = {}, 1000  # entries read across all data directories
    for root in data_roots():
        folder = Path(root) / "applications"
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.desktop")):
            if path.name in found or not DESKTOP_ID.match(path.name):
                continue
            budget -= 1
            if budget < 0:
                break
            try:
                entry, _ = desktop_entry(path.name)
            except (OSError, ValueError, KeyError, configparser.Error):
                continue
            found[path.name] = entry.get("Name", path.stem) if is_browser(entry) else None
    browsers = [{"id": key, "name": name} for key, name in found.items() if name]
    return sorted(browsers, key=lambda b: b["name"].lower())


FIREFOX_CLASS = "omarchy-x-panel"
FIREFOX_PREFS = {
    # Our own profile: allow its userChrome.css and skip every first-run page.
    "toolkit.legacyUserProfileCustomizations.stylesheets": True,
    "browser.shell.checkDefaultBrowser": False,
    "browser.aboutwelcome.enabled": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "startup.homepage_welcome_url": "",
    "startup.homepage_welcome_url.additional": "",
    "datareporting.policy.firstRunURL": "",
    "datareporting.policy.dataSubmissionPolicyBypassNotification": True,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    # A closed panel starts clean; nothing to restore or confirm.
    "browser.sessionstore.resume_from_crash": False,
    "browser.startup.page": 0,
    "browser.tabs.warnOnClose": False,
    "browser.warnOnQuit": False,
}
# Browser controls stay hidden while X is the only tab. A link that opens a
# second tab brings them back, so that tab can be seen and closed.
FIREFOX_CSS = (":root:not(:has(.tabbrowser-tab ~ .tabbrowser-tab)) #navigator-toolbox "
               "{ visibility: collapse !important; }\n")


def firefox_profile():
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "omarchy-x-panel/firefox"


def write_private(path, text):
    """Atomically replace a file in a directory prepare_firefox checked."""
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def prepare_firefox(profile):
    """The panel's own Firefox profile; X login lives here, not in the user's."""
    profile = Path(profile)
    for folder in (profile.parent, profile, profile / "chrome"):
        folder.mkdir(mode=0o700, exist_ok=True)
        info = os.lstat(folder)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError("Unsafe panel profile directory")
        os.chmod(folder, 0o700)
    prefs = "".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in FIREFOX_PREFS.items())
    write_private(profile / "user.js", prefs)
    write_private(profile / "chrome/userChrome.css", FIREFOX_CSS)


def without_profile(command):
    """Drop profile selection from a desktop Exec line."""
    out, skip = [], False
    for arg in command:
        if skip:
            skip = False
        elif arg in ("-P", "--profile", "-profile"):
            skip = True
        elif arg not in ("--ProfileManager", "-ProfileManager", "--no-remote", "-no-remote", "--new-instance"):
            out.append(arg)
    return out


def browser(choice=None, lowmem=False):
    """Launch contract for the chosen browser (None = the system default).

    In low-memory mode the window is closed on hide, so X's title count does
    not matter there: Chromium uses its lighter app mode instead of the popup.
    """
    if choice:
        # Only an installed browser entry may be chosen, never an arbitrary file.
        if not DESKTOP_ID.match(choice) or choice not in {b["id"] for b in list_browsers()}:
            raise ValueError("The chosen panel browser is not an installed browser")
        desktop = choice
    else:
        desktop = default_desktop()
    if not desktop or "/" in desktop or not desktop.endswith(".desktop"):
        raise ValueError("No valid default browser desktop entry")
    entry, path = desktop_entry(desktop)
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
        title = r"(^| / )X( [—–-] .*)?$|^([(][0-9,]+[)] )?x\.com([/ ].*)?$"
        if lowmem:
            # App windows get a class from their start URL,
            # "<browser>-x.com__home-<profile>", and no browser controls. The
            # /home path keeps it apart from a user's own x.com app, so a
            # compositor rule can open it as the panel from its first frame.
            prefixes = sorted(set(names.split("|") + ["chrome", "chromium"]))
            rule_class = "^(" + "|".join(re.escape(n) for n in prefixes) + r")-x\.com__home-.*$"
            window_class = "(?i)" + rule_class
            args = ["--app=https://x.com/home"]
        else:
            classes += [Path(command[0]).name, Path(desktop).stem]
            if entry.get("StartupWMClass"):
                classes.append(entry["StartupWMClass"])
            window_class = "(?i)^(" + "|".join(re.escape(name) for name in sorted(set(classes))) + ")$"
            args = ["--new-window", "https://x.com/"]
    elif "floorp" in identity:
        profile, app_id, app_class = floorp_app(command)
        # Same launch contract as Floorp's own Linux Web App desktop entry.
        args = ["--name", app_class, "--profile", profile, "--start-ssb", app_id]
        # Floorp's Linux app-class integration is still an experiment. Some
        # versions expose only 'floorp'; claim only newly launched windows there.
        window_class = "(?i)^(floorp|" + re.escape(app_class) + ")$"
        title = r"(^| / )X( [—–-] .*)?$"
    elif re.search(r"firefox|librewolf|waterfox|zen-browser|zen\.desktop", identity):
        # A Firefox profile of its own: a separate process with a class only
        # the panel uses, so a compositor rule opens it as the panel from its
        # first frame, a userChrome.css hides the controls, and closing the
        # last panel window ends the whole process.
        command = without_profile(command)
        profile = str(firefox_profile())
        args = ["--profile", profile, "--name", FIREFOX_CLASS, "--new-window", "https://x.com/home"]
        window_class = "(?i)^" + FIREFOX_CLASS + "$"
        title = ".*"
    else:
        names = {Path(command[0]).name, Path(desktop).stem}
        if entry.get("StartupWMClass"):
            names.add(entry["StartupWMClass"])
        # Native Mozilla windows use the executable name as their Wayland app ID.
        names.update(Path(arg).name for arg in command if "floorp" in arg.lower() or "firefox" in arg.lower())
        window_class = "(?i)^(" + "|".join(re.escape(name) for name in sorted(names)) + ")$"
        title = r"(^| / )X( [—–-] .*)?$|^([(][0-9,]+[)] )?x\.com([/ ].*)?$"
        args = ["--new-window", "https://x.com/"]
    firefox = window_class == "(?i)^" + FIREFOX_CLASS + "$"
    result = {"command": command + args, "class": window_class, "title": title,
              # Never adopt a window the user opened; the panel's own Firefox
              # class is safe to adopt.
              "discover": firefox or (not chromium and "floorp" not in identity and not lowmem),
              "clientFullscreen": chromium and not lowmem,
              "chromium": chromium, "desktop": desktop,
              "name": entry.get("Name", Path(desktop).stem)}
    if firefox:
        result.update(ruleClass="^" + FIREFOX_CLASS + "$", firefoxProfile=profile)
    if chromium and not lowmem:
        result.update(baseCommand=command, popup=True)
    if chromium and lowmem:
        result.update(ruleClass=rule_class)
    if "floorp" in identity and not chromium:
        result.update(profile=profile, appId=app_id, baseCommand=command)
    return result


def parse_args(argv):
    choice, lowmem, action = None, False, []
    while argv:
        arg = argv.pop(0)
        if arg == "--browser" and argv:
            value = argv.pop(0)
            choice = None if value in ("", "default") else value
        elif arg == "--lowmem":
            lowmem = True
        else:
            action.append(arg)
    return choice, lowmem, action


if __name__ == "__main__":
    try:
        choice, lowmem, action = parse_args(sys.argv[1:])
        if action == ["list"]:
            print(json.dumps({"default": default_desktop(), "browsers": list_browsers()}))
            sys.exit(0)
        result = browser(choice, lowmem)
        sys.argv[1:] = action
        if sys.argv[1:] == ["prepare"]:
            if "firefoxProfile" in result:
                prepare_firefox(result["firefoxProfile"])
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
