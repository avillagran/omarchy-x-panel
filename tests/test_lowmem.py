import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / "bin/omarchy-x-panel").read_text()


def function(name):
    return SCRIPT[SCRIPT.index(name + "() {"):].split("\n}", 1)[0] + "\n}\n"


class LowMemoryTests(unittest.TestCase):
    def run_hide(self, lowmem, survives, focus="focus", where="visible"):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.write_text("0x1|7\n")
            code = function("close_guarded") + function("hide_window") + f'''
STATE="{state}"; HIDDEN_AT="{tmp}/hidden"; RUNDIR="{tmp}"; SPECIAL=special:x
sleep() {{ :; }}
pref() {{ echo "$LOWMEM"; }}
exec 3>&1
hyprctl() {{ echo "dispatch $2" >&3; }}
addr_alive() {{ [ "$SURVIVES" = 1 ]; }}
state_of() {{ echo "$WHERE"; }}
reveal_window() {{ echo reveal; }}
apply_layout() {{ echo layout; }}
hl_focus() {{ echo focus; }}
hl_move() {{ echo "move $2"; }}
ensure_pin() {{ echo "pin $2"; }}
draft_notify() {{ echo notify; }}
hide_window '0x1|7' {focus}
echo "rc=$?"
'''
            result = subprocess.run(["bash", "-c", code], capture_output=True, text=True,
                                    env={**os.environ, "LOWMEM": lowmem, "SURVIVES": survives,
                                         "WHERE": where})
            return result.stdout.split("\n"), state.exists()

    def test_normal_mode_parks_the_window(self):
        out, kept = self.run_hide("false", "1")
        self.assertIn("move special:x", out)
        self.assertFalse(any("close" in line for line in out))
        self.assertTrue(kept)

    def test_lowmem_closes_and_forgets_the_window(self):
        out, kept = self.run_hide("true", "0")
        self.assertTrue(any("window.close" in line for line in out))
        self.assertNotIn("move special:x", out)
        self.assertNotIn("notify", out)
        self.assertIn("rc=0", out)
        self.assertFalse(kept)

    def test_lowmem_keeps_a_window_holding_a_draft_and_warns(self):
        out, kept = self.run_hide("true", "1")
        self.assertIn("focus", out)
        self.assertIn("notify", out)
        self.assertIn("rc=3", out)
        self.assertTrue(kept)

    def test_blocked_close_of_a_parked_panel_brings_it_back(self):
        out, _ = self.run_hide("true", "1", where="hidden")
        self.assertIn("reveal", out)
        self.assertIn("layout", out)

    def test_blur_hide_never_steals_focus(self):
        out, _ = self.run_hide("true", "1", focus="nofocus")
        self.assertNotIn("focus", out)
        self.assertIn("notify", out)

    def settings_close(self, key, val, where, chromium):
        code = function("settings_close") + f'''
STATE=/nonexistent; X_CHROMIUM={chromium}
read_file_safe() {{ echo '0x1|7'; }}
resolve() {{ echo "$1"; }}
state_of() {{ echo {where}; }}
close_guarded() {{ echo closed; return 3; }}
settings_close {key} {val}; echo "rc=$?"
'''
        return subprocess.run(["bash", "-c", code], capture_output=True, text=True).stdout.split()

    def test_settings_changes_close_only_a_window_they_would_orphan(self):
        # A blocked close (draft) is reported, so the change is not saved.
        self.assertEqual(self.settings_close("browser", '"firefox.desktop"', "visible", "false"),
                         ["closed", "rc=3"])
        self.assertEqual(self.settings_close("lowmem", "false", "visible", "true"), ["closed", "rc=3"])
        self.assertEqual(self.settings_close("lowmem", "true", "hidden", "false"), ["closed", "rc=3"])
        self.assertEqual(self.settings_close("lowmem", "true", "visible", "false"), ["rc=0"])
        self.assertEqual(self.settings_close("lowmem", "false", "hidden", "false"), ["rc=0"])
        self.assertEqual(self.settings_close("browser", '"default"', "gone", "true"), ["rc=0"])


if __name__ == "__main__":
    unittest.main()
