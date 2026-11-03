from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest

SCRIPT = (Path(__file__).resolve().parents[1] / 'bin/omarchy-x-panel').read_text()


def function(name):
    return SCRIPT[SCRIPT.index(name + '() {'):].split('\n}', 1)[0] + '\n}\n'


class IdentityTests(unittest.TestCase):
    def resolve(self, saved, marker, clients):
        code = function('resolve') + r'''
X_POPUP=true; X_DISCOVER=false; X_CLASS='^google-chrome$'; RUNDIR=/unused
read_file_safe() { printf '%s' "$MARKER"; }
hypr_json() { printf '%s' "$CLIENTS"; }
find_x() { :; }
resolve "$SAVED"
'''
        return subprocess.check_output(['bash', '-c', code], text=True,
            env={**os.environ, 'SAVED': saved, 'MARKER': marker, 'CLIENTS': json.dumps(clients)}).strip()

    def test_missing_state_recovers_owned_popup(self):
        self.assertEqual(self.resolve('', '0x123|42', [{'address':'0x123','pid':42,'class':'google-chrome'}]), '0x123|42')

    def test_wrong_state_never_adopts_normal_browser_window(self):
        clients = [{'address':'0x123','pid':42,'class':'google-chrome'}, {'address':'0x999','pid':42,'class':'google-chrome'}]
        self.assertEqual(self.resolve('0x999|42', '0x123|42', clients), '0x123|42')

    def test_dead_marker_does_not_adopt_an_unrelated_window(self):
        self.assertEqual(self.resolve('0x999|42', '0x123|42', [{'address':'0x999','pid':42,'class':'google-chrome'}]), '')

    def test_marker_rejects_reused_address_with_different_pid(self):
        self.assertEqual(self.resolve('', '0x123|42', [{'address':'0x123','pid':99,'class':'google-chrome'}]), '')

    def test_force_chromeless_reissues_transition_despite_cached_state(self):
        code = function('ensure_client_fullscreen') + r'''
X_CLIENT_FULLSCREEN=true
window_field() { echo 2; }
hyprctl() { echo "$2" >&3; }
exec 3>&1
ensure_client_fullscreen 0x123 force
'''
        lines=subprocess.check_output(['bash','-c',code],text=True).splitlines()
        self.assertEqual(len(lines),2)
        self.assertIn('client = 0',lines[0])
        self.assertIn('client = 2',lines[1])
        self.assertTrue(all('address:0x123' in line for line in lines))

    def test_force_does_not_change_non_chromium_app_windows(self):
        code = function('ensure_client_fullscreen') + r'''
X_CLIENT_FULLSCREEN=false
hyprctl() { echo unexpected >&3; }
exec 3>&1
ensure_client_fullscreen 0x123 force
'''
        self.assertEqual(subprocess.check_output(['bash','-c',code],text=True), '')

    def launch(self, succeeds=True):
        with tempfile.TemporaryDirectory() as folder:
            code = function('launch_or_reuse') + r'''
X_POPUP=true; SCRIPT_DIR=/unused; BROWSER_ARGS=(); STATE="$TESTDIR/state"; CANCEL="$TESTDIR/cancel"
resolve() { if [ -f "$TESTDIR/confirmed" ]; then echo '0x123|42'; fi; }
python3() {
  if [ "${@: -1}" = launch ]; then
    if [ "$SUCCEEDS" = false ]; then return 1; fi
    touch "$TESTDIR/confirmed"
  fi
}
write_state() { echo "$1"; }
apply_layout() { :; }
ensure_float() { :; }
ensure_pin() { :; }
x_clients() { echo 'UNCONFIRMED DISCOVERY' >&2; return 1; }
launch_or_reuse
'''
            return subprocess.run(['bash','-c',code],text=True,capture_output=True,
                env={**os.environ,'TESTDIR':folder,'SUCCEEDS':str(succeeds).lower()})

    def test_popup_launch_waits_for_confirmation_before_saving_state(self):
        result=self.launch()
        self.assertEqual(result.returncode,0)
        self.assertEqual(result.stdout.strip(),'0x123|42')
        self.assertEqual(result.stderr,'')

    def test_failed_popup_launch_cannot_save_unconfirmed_window(self):
        result=self.launch(False)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
