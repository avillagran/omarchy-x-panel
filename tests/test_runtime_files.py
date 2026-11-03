from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RuntimeFiles(unittest.TestCase):
    def test_two_helper_imports_do_not_write_into_watched_plugin(self):
        with tempfile.TemporaryDirectory() as folder:
            bin_path = Path(folder) / 'bin'
            bin_path.mkdir()
            for name in ['panel-browser.py', 'chromium-popup.py', 'process_io.py']:
                shutil.copyfile(ROOT / 'bin' / name, bin_path / name)
            env = dict(os.environ)
            env.pop('PYTHONDONTWRITEBYTECODE', None)
            for _ in range(2):
                for name in ['panel-browser.py', 'chromium-popup.py']:
                    subprocess.run([sys.executable, '-c',
                        'import runpy,sys; runpy.run_path(sys.argv[1], run_name="probe")',
                        str(bin_path / name)], env=env, check=True, timeout=5)
            self.assertEqual(sorted(p.name for p in bin_path.iterdir()),
                             ['chromium-popup.py', 'panel-browser.py', 'process_io.py'])
