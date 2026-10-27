import importlib.util
from pathlib import Path
import sys
import time
import unittest

spec = importlib.util.spec_from_file_location('bounded_io', Path(__file__).resolve().parents[1] / 'bin/process_io.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ProcessBounds(unittest.TestCase):
    def test_exact_budget_and_oversized_producer(self):
        self.assertEqual(module.capture([sys.executable, '-c', 'print("abcd", end="")'], limit=4), 'abcd')
        with self.assertRaisesRegex(ValueError, 'byte budget'):
            module.capture([sys.executable, '-c', 'import os;\nwhile True: os.write(1, b"x" * 65536)'], limit=64)

    def test_total_deadline_includes_descendant_holding_stdout(self):
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            module.capture([sys.executable, '-c', 'import subprocess,sys; subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])'], timeout=0.2)
        self.assertLess(time.monotonic() - started, 2)

    def test_nonzero_exit_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'failed'):
            module.capture([sys.executable, '-c', 'raise SystemExit(1)'])
