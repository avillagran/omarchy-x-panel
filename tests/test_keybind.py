import importlib.util
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('keybind', Path(__file__).parents[1] / 'bin/keybind-config.py')
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


class KeybindMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.main = self.directory / 'hyprland.lua'
        self.module = self.directory / 'x-panel-bindings.lua'
        self.main.write_bytes(b'-- user config\n')
        self.main.chmod(0o640)
        self.module.write_bytes(k.HEADER + b' legacy\n')

    def run_update(self, enabled):
        k.update('enable' if enabled else 'disable', self.directory, '/opt/x-panel')

    def test_upgrade_and_removal_all_spellings(self):
        for refs in ([k.OLD], [k.NEW], [k.OLD, k.NEW], [k.OLD, k.OLD, k.NEW], []):
            with self.subTest(refs=refs):
                original = b'-- before\r\n' + b''.join(x + b'\n' for x in refs) + b'-- no final newline'
                self.main.write_bytes(original)
                self.run_update(True)
                migrated = self.main.read_bytes()
                self.assertNotIn(k.OLD, migrated)
                self.assertEqual(migrated.count(k.NEW), 1)
                self.assertIn(b'-- before\r\n', migrated)
                self.assertIn(b'-- no final newline', migrated)
                self.assertEqual(stat.S_IMODE(self.main.stat().st_mode), 0o640)
                self.run_update(True)
                self.assertEqual(self.main.read_bytes(), migrated)
                self.run_update(False)
                self.assertNotIn(k.NEW, self.main.read_bytes())
                self.assertNotIn(k.OLD, self.main.read_bytes())
                self.assertFalse(self.module.exists())

    def test_disable_legacy_only_and_config_with_only_generated_lines(self):
        for original in (k.OLD + b'\n', k.NEW + b'\n', k.OLD + b'\n' + k.NEW + b'\n', b''):
            self.main.write_bytes(original)
            self.module.write_bytes(k.HEADER)
            self.run_update(False)
            self.assertEqual(self.main.read_bytes(), b'')
            self.assertFalse(self.module.exists())

    def test_preserves_non_generated_lines_exactly_and_private_backup(self):
        unrelated = b'-- require("x-panel-bindings")\nrequire("hypr.x-panel-bindings.extra")\ncustom = "x-panel-bindings"\n'
        original = unrelated + k.OLD + b'\n' + b'-- tail without newline'
        self.main.write_bytes(original)
        self.run_update(False)
        self.assertEqual(self.main.read_bytes(), unrelated + b'-- tail without newline')
        backups = list(self.directory.glob('.x-panel-backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(stat.S_IMODE(backups[0].stat().st_mode), 0o600)

    def test_unreadable_main_keeps_module(self):
        original = self.module.read_bytes()
        for failure in (PermissionError(), ValueError('too large')):
            with patch.object(k, 'read_regular', side_effect=failure):
                with self.assertRaises((OSError, ValueError)):
                    self.run_update(False)
            self.assertEqual(self.module.read_bytes(), original)

    def test_unsafe_or_oversized_main_keeps_module(self):
        for kind in ('missing', 'symlink', 'fifo', 'large'):
            with self.subTest(kind=kind):
                self.main.unlink(missing_ok=True)
                if kind == 'symlink':
                    self.main.symlink_to(self.module)
                elif kind == 'fifo':
                    os.mkfifo(self.main)
                elif kind == 'large':
                    self.main.write_bytes(b'x' * (k.CAP + 1))
                with self.assertRaises((OSError, ValueError)):
                    self.run_update(False)
                self.assertTrue(self.module.exists())

    def test_failed_main_replace_keeps_module_and_original_config(self):
        self.main.write_bytes(k.OLD + b'\n')
        original = self.main.read_bytes()
        for enabled in (False, True):
            replace = k.os.replace
            def fail_main(src, dst):
                if dst == self.main:
                    raise PermissionError('replacement refused')
                return replace(src, dst)
            with patch.object(k.os, 'replace', side_effect=fail_main):
                with self.assertRaises(OSError):
                    self.run_update(enabled)
            self.assertEqual(self.main.read_bytes(), original)
            self.assertTrue(self.module.exists())
            self.assertEqual(list(self.directory.glob('.x-panel-write-*')), [])

    def test_fresh_install_without_module(self):
        self.module.unlink()
        self.run_update(True)
        self.assertEqual(self.main.read_bytes(), b'-- user config\n' + k.NEW + b'\n')
        self.assertTrue(self.module.read_bytes().startswith(k.HEADER))

    def test_shell_commands_migrate_and_return_failure_without_desktop(self):
        home = self.directory / 'home'
        hypr = home / '.config/hypr'
        hypr.mkdir(parents=True)
        main = hypr / 'hyprland.lua'
        module = hypr / 'x-panel-bindings.lua'
        main.write_bytes(k.OLD + b'\n')
        module.write_bytes(k.HEADER)
        script = Path(__file__).parents[1] / 'bin/omarchy-x-panel'
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'),
                   XDG_RUNTIME_DIR=str(self.directory), HYPRLAND_INSTANCE_SIGNATURE='test')
        for command in ('install-bind', 'uninstall-bind'):
            result = subprocess.run(['bash', str(script), command], env=env,
                                    capture_output=True, timeout=8)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(module.exists())
        module.write_bytes(k.HEADER)
        main.unlink()
        result = subprocess.run(['bash', str(script), 'uninstall-bind'], env=env,
                                capture_output=True, timeout=8)
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(module.exists())

    def test_unrecognized_module_preserved(self):
        self.module.write_bytes(b'-- handmade configuration\n')
        with self.assertRaises(ValueError):
            self.run_update(False)
        self.assertTrue(self.module.exists())


if __name__ == '__main__':
    unittest.main()
