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

    def restore(self, state, locked=False):
        with tempfile.TemporaryDirectory() as folder:
            code = function('restore_chromeless') + r'''
X_CLIENT_FULLSCREEN=true; LOCK="$TESTDIR/lock"; STATE=/unused
read_file_safe() { echo '0x123|42'; }
resolve() { echo "$1"; }
state_of() { echo "$PANEL_STATE"; }
ensure_client_fullscreen() { echo "restore $1"; }
if [ "$LOCKED" = true ]; then exec 8>>"$LOCK"; flock -n 8; fi
restore_chromeless
'''
            return subprocess.check_output(['bash', '-c', code], text=True,
                env={**os.environ, 'TESTDIR': folder, 'PANEL_STATE': state,
                     'LOCKED': str(locked).lower()}).strip()

    def test_workspace_change_restores_chromeless_visible_panel(self):
        self.assertEqual(self.restore('visible'), 'restore 0x123')

    def test_restore_chromeless_leaves_hidden_or_busy_panel_alone(self):
        self.assertEqual(self.restore('hidden'), '')
        self.assertEqual(self.restore('visible', locked=True), '')

    def nobar(self, address):
        code = 'PANEL_TAG=x-panel\n' + function('panel_nobar') + r'''
hyprctl() { echo "$2" >&3; }
exec 3>&1
panel_nobar "$ADDRESS"
'''
        return subprocess.check_output(['bash', '-c', code], text=True,
            env={**os.environ, 'ADDRESS': address}).splitlines()

    def test_floating_workspace_title_bar_is_dropped_by_tag(self):
        lines = self.nobar('0xabc')
        self.assertEqual(len(lines), 2)
        self.assertIn('match = { tag = "x-panel" }', lines[0])
        self.assertIn('["hyprbars:no_bar"] = true', lines[0])
        self.assertIn('tag = "+x-panel", window = "address:0xabc"', lines[1])

    def test_title_bar_rule_never_splices_an_invalid_address(self):
        self.assertEqual(self.nobar('0xabc" }) os.execute("x'), [])

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
