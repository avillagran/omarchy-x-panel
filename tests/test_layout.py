from pathlib import Path
import subprocess
import unittest


SCRIPT = (Path(__file__).resolve().parents[1] / "bin/omarchy-x-panel").read_text()


def function(name):
    return SCRIPT[SCRIPT.index(name + "() {"):].split("\n}", 1)[0] + "\n}\n"


class LayoutTests(unittest.TestCase):
    def layout(self, monitor, bar, size, valign="top"):
        code = function("safe_area") + function("px_value") + function("apply_layout")
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


if __name__ == "__main__":
    unittest.main()
