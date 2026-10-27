import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("panel_browser", ROOT / "bin/panel-browser.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "applications").mkdir()
        self.env = patch.dict(os.environ, XDG_DATA_HOME=str(self.root),
                              XDG_DATA_DIRS=str(self.root / "empty"))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = self.root / "config"
        floorp = self.config / "floorp"
        profile = floorp / "default"
        (profile / "ssb").mkdir(parents=True)
        (floorp / "profiles.ini").write_text("[InstallTest]\nDefault=default\n")
        (profile / "ssb/ssb.json").write_text(json.dumps({"https://x.com/:0": {
            "id": "{test-x}", "name": "X", "start_url": "https://x.com/", "userContextId": 0}}))
        self.env_config = patch.dict(os.environ, XDG_CONFIG_HOME=str(self.config))
        self.env_config.start()
        self.addCleanup(self.env_config.stop)

    def resolve(self, desktop, executable, fallback=False):
        (self.root / "applications" / desktop).write_text(
            f"[Desktop Entry]\nName=Firefox\nType=Application\nExec={executable}\n")
        responses = [desktop]
        if fallback:
            responses.insert(0, ValueError("unavailable"))
        with patch.object(module, "capture", side_effect=responses):
            return module.browser()

    def test_custom_floorp_entry_keeps_quoted_path_and_profile(self):
        info = self.resolve("userapp-Firefox.desktop", '"/opt/Floorp Browser/floorp" %u')
        self.assertEqual(info["command"], ["/opt/Floorp Browser/floorp", "--name", "floorp-test-x",
                         "--profile", str(self.config / "floorp/default"), "--start-ssb", "{test-x}"])
        self.assert_matches(info, "floorp-test-x", "Home / X — Ablaze Floorp", True)
        self.assertFalse(info["discover"])
        self.assert_matches(info, "floorp", "Privacy Policy | Floorp — Ablaze Floorp", False)
        self.assert_matches(info, "chrome-x.com__-Default", "Home / X", False)

    def test_chromium_normal_window_keeps_count_and_profile(self):
        info = self.resolve("chromium.desktop", "/usr/bin/chromium --profile-directory=Work %U")
        self.assertEqual(info["command"][-2:], ["--new-window", "https://x.com/"])
        self.assertIn("--profile-directory=Work", info["command"])
        self.assertTrue(info["clientFullscreen"])
        self.assertTrue(info["popup"])
        self.assertEqual(info["baseCommand"], ["/usr/bin/chromium", "--profile-directory=Work"])
        self.assertFalse(info["discover"])
        self.assert_matches(info, "chromium", "(8) Home / X - Chromium", True)
        self.assert_matches(info, "chrome-x.com__-Work", "Home / X", False)
        self.assert_matches(info, "chromium", "Unrelated tab", False)

    def test_google_chrome_normal_class(self):
        info = self.resolve("google-chrome.desktop", "/usr/bin/google-chrome-stable %U")
        self.assert_matches(info, "google-chrome", "(8) Home / X - Google Chrome", True)
        self.assert_matches(info, "google-chrome", "Unrelated tab - Google Chrome", False)

    def test_chromium_family_change_does_not_adopt_other_browser(self):
        info = self.resolve("brave-browser.desktop", "/usr/bin/brave-browser %U")
        self.assert_matches(info, "brave", "(8) Home / X - Brave", True)
        self.assert_matches(info, "google-chrome", "(8) Home / X - Google Chrome", False)

    def test_chromeless_state_targets_only_panel_and_is_idempotent(self):
        script = (ROOT / "bin/omarchy-x-panel").read_text()
        function = script[script.index("ensure_client_fullscreen() {"):].split("\n}", 1)[0] + "\n}"
        for enabled, current, expected_call in [("true", "0", True),
                                                 ("true", "2", False),
                                                 ("false", "0", False)]:
            calls = self.root / "calls"
            calls.write_text("")
            code = function + '''
window_field() { echo "$CURRENT"; }
hyprctl() { printf '%s\\n' "$*" >> "$CALLS"; }
ensure_client_fullscreen '0x123'
'''
            result = subprocess.run(["bash", "-c", code], capture_output=True, text=True,
                                    env={**os.environ, "X_CLIENT_FULLSCREEN": enabled, "CURRENT": current,
                                         "CALLS": str(calls)})
            self.assertEqual(result.returncode, 0)
            recorded = calls.read_text()
            self.assertEqual(bool(recorded), expected_call)
            if expected_call:
                self.assertIn('internal = 0, client = 2, action = "set"', recorded)
                self.assertIn('window = "address:0x123"', recorded)

    def test_https_fallback(self):
        info = self.resolve("floorp.desktop", "floorp %u", fallback=True)
        self.assertEqual(info["command"][0], "floorp")

    def test_fresh_install_uses_native_default_profile_initialization(self):
        ini = self.config / "floorp/profiles.ini"
        ini.unlink()
        def initialize(*args, **kwargs):
            ini.write_text("[InstallTest]\nDefault=default\n")
        with patch.dict(os.environ, XDG_RUNTIME_DIR=str(self.root)), \
             patch.object(module.subprocess, "Popen", side_effect=initialize) as launch:
            profile, app_id, app_class = module.floorp_app(["floorp"])
        self.assertEqual(profile, str(self.config / "floorp/default"))
        self.assertEqual(launch.call_args.args[0], ["floorp", "--new-tab", "about:blank"])

    def test_missing_floorp_app_gets_stable_native_registration(self):
        (self.config / "floorp/default/ssb/ssb.json").write_text("{}")
        info = self.resolve("floorp.desktop", "floorp %u")
        self.assertIn("--start-ssb", info["command"])
        self.assertNotIn("--new-window", info["command"])
        self.assertEqual(info["appId"], self.resolve("floorp.desktop", "floorp %u")["appId"])

    def test_missing_default_never_falls_back_to_chromium(self):
        with patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            with self.assertRaises(ValueError):
                module.browser()

    def test_desktop_arguments_are_not_shell_code(self):
        info = self.resolve("floorp.desktop", 'floorp "$(touch SHOULD_NOT_EXIST)" %u')
        self.assertEqual(info["command"][1], "$(touch SHOULD_NOT_EXIST)")


    def test_native_registration_preserves_existing_apps_and_is_idempotent(self):
        spec = importlib.util.spec_from_file_location("floorp_setup", ROOT / "bin/floorp-configure.py")
        setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(setup)
        profile = self.config / "floorp/default"
        store = profile / "ssb/ssb.json"
        store.write_text(json.dumps({"https://other.example/:0": {"id": "other", "name": "Other"}}))
        setup.register(str(profile), "{new-native-app}")
        data = json.loads(store.read_text())
        self.assertEqual(data["https://x.com/:0"]["id"], "{new-native-app}")
        # Existing registrations under different URLs remain byte-for-byte data.
        data["https://other.example/:0"] = {"id": "other", "name": "Other"}
        store.write_text(json.dumps(data))
        setup.register(str(profile), "{new-native-app}")
        self.assertEqual(json.loads(store.read_text()), data)

    def install(self, desktop, executable, name, categories="Network;WebBrowser;", extra=""):
        (self.root / "applications" / desktop).write_text(
            f"[Desktop Entry]\nName={name}\nType=Application\nExec={executable}\n"
            f"Categories={categories}\n{extra}")

    def test_lowmem_chromium_uses_app_mode_with_its_own_class(self):
        self.install("google-chrome.desktop", "/usr/bin/google-chrome-stable --profile-directory=Work %U",
                     "Google Chrome")
        info = module.browser("google-chrome.desktop", lowmem=True)
        self.assertEqual(info["command"][-1], "--app=https://x.com/home")
        self.assertEqual(info["ruleClass"], r"^(chrome|chromium)-x\.com__home-.*$")
        self.assertIn("--profile-directory=Work", info["command"])
        self.assertFalse(info["clientFullscreen"])
        self.assertNotIn("popup", info)
        self.assertTrue(info["chromium"])
        self.assert_matches(info, "chrome-x.com__home-Profile_1", "Home / X", True)
        # Not a user's own x.com app either.
        self.assert_matches(info, "chrome-x.com__-Default", "Home / X", False)
        # Never a normal browser window, nor another site's app.
        self.assert_matches(info, "google-chrome", "(8) Home / X - Google Chrome", False)
        self.assert_matches(info, "chrome-mail.google.com__-Default", "Home / X", False)

    def test_chosen_firefox_gets_its_own_profile_and_class(self):
        self.install("firefox.desktop", "/usr/lib/firefox/firefox -P Personal %u", "Firefox")
        profile = str(self.root / "omarchy-x-panel/firefox")
        for lowmem in (False, True):
            info = module.browser("firefox.desktop", lowmem=lowmem)
            # The user's profile selection is replaced by the panel's own.
            self.assertEqual(info["command"], ["/usr/lib/firefox/firefox", "--profile", profile,
                             "--name", "omarchy-x-panel", "--new-window", "https://x.com/home"])
            self.assertEqual(info["ruleClass"], "^omarchy-x-panel$")
            self.assertFalse(info["clientFullscreen"])
            self.assertTrue(info["discover"])
            self.assert_matches(info, "omarchy-x-panel", "Mozilla Firefox", True)
            self.assert_matches(info, "firefox", "Home / X — Mozilla Firefox", False)

    def test_firefox_profile_is_private_and_chromeless(self):
        profile = self.root / "omarchy-x-panel/firefox"
        module.prepare_firefox(profile)
        module.prepare_firefox(profile)  # idempotent
        self.assertEqual(os.stat(profile).st_mode & 0o777, 0o700)
        prefs = (profile / "user.js").read_text()
        self.assertIn('user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);', prefs)
        self.assertIn('user_pref("browser.startup.page", 0);', prefs)
        self.assertIn("#navigator-toolbox", (profile / "chrome/userChrome.css").read_text())

    def test_firefox_profile_refuses_a_symlinked_directory(self):
        (self.root / "elsewhere").mkdir()
        (self.root / "omarchy-x-panel").mkdir()
        (self.root / "omarchy-x-panel/firefox").symlink_to(self.root / "elsewhere")
        with self.assertRaises(ValueError):
            module.prepare_firefox(self.root / "omarchy-x-panel/firefox")
        self.assertEqual(list((self.root / "elsewhere").iterdir()), [])

    def test_only_visible_installed_browsers_can_be_chosen(self):
        self.install("firefox.desktop", "/usr/lib/firefox/firefox %u", "Firefox")
        self.install("chatgpt.desktop", "chatgpt %U", "ChatGPT", "Utility;")
        self.install("com.google.Chrome.desktop", "/usr/bin/google-chrome-stable %U", "Chrome",
                     extra="NoDisplay=true\n")
        self.assertEqual(module.list_browsers(), [{"id": "firefox.desktop", "name": "Firefox"}])
        for choice in ("chatgpt.desktop", "com.google.Chrome.desktop", "../firefox.desktop", "missing.desktop"):
            with self.assertRaises(ValueError):
                module.browser(choice)

    def test_default_choice_follows_the_system_browser(self):
        self.install("firefox.desktop", "/usr/lib/firefox/firefox %u", "Firefox")
        self.assertEqual(module.parse_args(["--browser", "default", "--lowmem", "launch"]),
                         (None, True, ["launch"]))
        with patch.object(module, "capture", return_value="firefox.desktop\n"):
            self.assertEqual(module.browser(None)["desktop"], "firefox.desktop")

    def assert_matches(self, info, cls, title, expected):
        result = subprocess.run(["jq", "-ne", "--arg", "c", info["class"],
                                 "--arg", "t", info["title"], "--arg", "cls", cls,
                                 "--arg", "title", title,
                                 '($cls|test($c)) and ($title|test($t))'], capture_output=True)
        self.assertEqual(result.returncode == 0, expected, result.stderr)

    def test_show_succeeds_without_a_reload(self):
        script = (ROOT / "bin/omarchy-x-panel").read_text()
        function = script[script.index("show_window() {"):].split("\n}", 1)[0] + "\n}"
        stubs = "hl_move() { :; }; ensure_float() { :; }; ensure_pin() { :; }; apply_layout() { :; }; hl_focus() { :; }; reload_if_pending() { return 1; }; maybe_refresh() { return 1; }; reload_if_broken() { return 1; };\n"
        result = subprocess.run(["bash", "-c", stubs + function + '\nshow_window "0x123|42"'])
        self.assertEqual(result.returncode, 0)

    def test_browser_suffix_is_healthy(self):
        script = (ROOT / "bin/omarchy-x-panel").read_text()
        function = next(line for line in script.splitlines() if line.startswith("title_healthy()"))
        for title, expected in [("Home / X", 0), ("Inicio / X — Ablaze Floorp", 0),
                                ("X", 1), ("x.com", 1), ("Home / XYZ", 1)]:
            result = subprocess.run(["bash", "-c", function + '\ntitle_healthy "$1"', "test", title])
            self.assertEqual(result.returncode, expected)


if __name__ == "__main__":
    unittest.main()
