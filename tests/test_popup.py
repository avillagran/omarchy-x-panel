import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("chromium_popup", Path(__file__).resolve().parents[1] / "bin/chromium-popup.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PopupTests(unittest.TestCase):
    def run_launcher(self, focused):
        launcher = {"address": "0x123", "title": "X Panel Launch token - Google Chrome", "pid": 42, "class": "google-chrome"}
        popup = {"address": "0x456", "title": "(7) Home / X - Google Chrome", "pid": 42, "class": "google-chrome"}
        snapshots = [[], [launcher], [popup], [launcher]] if focused else [[], [launcher], [launcher]]
        info = {"baseCommand": ["chrome", "--profile-directory=Work"],
                "class": "^google-chrome$", "title": " / X"}
        with tempfile.TemporaryDirectory() as folder, \
             patch.dict(os.environ, XDG_RUNTIME_DIR=folder), \
             patch.object(module.secrets, "token_hex", return_value="token"), \
             patch.object(module, "HTTPServer"), \
             patch.object(module, "clients", side_effect=snapshots), \
             patch.object(module, "hypr", return_value=json.dumps({"address": "0x123" if focused else "0x999"})), \
             patch.object(module, "dispatch") as dispatch, \
             patch.object(module.time, "sleep"), \
             patch.object(module.subprocess, "Popen") as launch:
            marker = Path(folder) / "x-panel.chromium-popup"
            if focused:
                module.launch(info)
                self.assertEqual(marker.read_text(), "0x456|42\n")
                self.assertEqual(launch.call_args.args[0][:5], ["uwsm-app", "--", "chrome", "--profile-directory=Work", "--new-window"])
                keys = [c.args[0] for c in dispatch.call_args_list if "send_key_state" in c.args[0]]
                self.assertEqual(len(keys), 2)
                self.assertTrue(all('window = "address:0x123"' in c for c in keys))
            else:
                with self.assertRaisesRegex(RuntimeError, "lost focus"):
                    module.launch(info)
                self.assertFalse(marker.exists())
                self.assertFalse(any("send_key_state" in c.args[0] for c in dispatch.call_args_list))
            self.assertIn('window.close({ window = "address:0x123"', dispatch.call_args_list[-1].args[0])

    def test_popup_marker_and_activation_are_scoped_to_owned_launcher(self):
        self.run_launcher(True)

    def test_focus_change_aborts_without_sending_keys_or_claiming_panel(self):
        self.run_launcher(False)


if __name__ == "__main__":
    unittest.main()
