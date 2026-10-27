from pathlib import Path
import subprocess
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / "bin/omarchy-x-panel").read_text()


def function(name):
    return SCRIPT[SCRIPT.index(name + "() {"):].split("\n}", 1)[0] + "\n}\n"


class LayoutTests(unittest.TestCase):
    def layout(self, monitor, bar, size, valign="top"):
        code = function("safe_area") + function("px_value") + function("compute_xy") \
            + function("panel_box") + function("apply_layout")
        code += '''
GAP=8
pref() { case "$1" in side) echo right;; valign) echo "$VALIGN";; esac; }
monitor_geom() { echo "$MONITOR"; }
bar_geom() { echo "$BAR"; }
size_for() { echo '620 75%'; }
ensure_float() { :; }
ensure_client_fullscreen() { :; }
resize_and_measure() { echo "$ACTUAL"; }
hl_movepos() { echo "$2 $3"; }
apply_layout '0x123|42'
'''
        import os
        result = subprocess.run(["bash", "-c", code], capture_output=True, text=True, check=True,
                                env={**os.environ, "MONITOR": monitor, "BAR": bar,
                                     "ACTUAL": size, "VALIGN": valign})
        return tuple(map(int, result.stdout.split()))

    def test_floorp_minimum_width_keeps_right_margin_on_external_monitor(self):
        x, y = self.layout("HDMI 1728 0 1920 1080 LG", "0 26", "731 784")
        self.assertEqual((x, y), (2897, 34))
        self.assertEqual(x + 731, 1728 + 1920 - 20)

    def test_scaled_monitor_with_negative_origin(self):
        x, y = self.layout("eDP 3648 -49 1728 1117 eDP", "-49 32", "731 808")
        self.assertEqual((x, y), (4625, -9))
        self.assertLessEqual(x + 731, 3648 + 1728)
        self.assertLessEqual(y + 808, -49 + 1117)

    def test_bottom_alignment_uses_accepted_height(self):
        x, y = self.layout("HDMI 1728 0 1920 1080 LG", "0 26", "731 900", "bottom")
        self.assertEqual(y + 900, 1080)

    def rule(self, rule_class):
        import json, os
        code = function("safe_area") + function("px_value") + function("compute_xy") \
            + function("panel_box") + function("launch_rule") + '''
GAP=8
pref() { case "$1" in side) echo right;; valign) echo top;; esac; }
monitor_geom() { echo "HDMI 1728 0 1920 1080 LG"; }
bar_geom() { echo "0 26"; }
size_for() { echo '620 75%'; }
hyprctl() { printf '%s\\n' "$2" >&3; }
exec 3>&1
launch_rule
'''
        return subprocess.run(["bash", "-c", code], capture_output=True, text=True,
                              env={**os.environ, "BROWSER_INFO": json.dumps({"ruleClass": rule_class})}).stdout

    def test_launch_rule_opens_the_app_as_the_panel(self):
        out = self.rule(r"^(chrome|chromium)-x\.com__home-.*$")
        # Monitor-relative: right edge minus margin, just below the bar.
        self.assertEqual(out.strip(), 'hl.window_rule({ name = "omarchy-x-panel", match = { class = '
                         r'"^(chrome|chromium)-x\\.com__home-.*$" }, float = true, pin = true, '
                         'size = { 620, 784 }, move = { 1280, 34 } })')

    def test_launch_rule_refuses_lua_quotes(self):
        self.assertEqual(self.rule('^x" }) os.execute("id") --$'), "")

    def test_size_prefs_never_reach_lua_unvalidated(self):
        import subprocess
        code = function("px_value") + '''
for v in 420 "50%" '1, y = os.execute("id")' 'a[$(id)]' "99999999" "08"; do px_value "$v" w 1000; done
'''
        out = subprocess.run(["bash", "-c", code], capture_output=True, text=True).stdout.split()
        self.assertEqual(out, ["420", "500", "750", "750", "750", "8"])


if __name__ == "__main__":
    unittest.main()
