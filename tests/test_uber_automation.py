"""Safety boundaries for macOS process targeting and lock recovery."""
import os
import unittest
if os.name == "nt":
    raise unittest.SkipTest("Legacy macOS LaunchAgent only; Windows uses the registry Uber adapter")
import fcntl
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('uber_runner', ROOT / 'automation/run_uber.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class AutomationTests(unittest.TestCase):
    def test_only_exact_profile_main_browser_group_is_selected(self):
        profile = Path('/tmp/profile with spaces')
        rows = '\n'.join([
            '101 101 Chromium --user-data-dir=/tmp/profile with spaces --remote-debugging-pipe about:blank',
            '102 101 Chromium --type=renderer --user-data-dir=/tmp/profile with spaces --remote-debugging-pipe',
            '103 103 Chromium --user-data-dir=/tmp/profile with spaces-other --remote-debugging-pipe',
            '104 104 Google Chrome --user-data-dir=/Users/me/Chrome --remote-debugging-pipe',
        ])
        with patch.object(runner.subprocess, 'check_output', return_value=rows):
            self.assertEqual(runner.profile_browsers(profile), [101])

    def test_flock_recovers_after_crash_without_deleting_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'lock')
            code = 'import fcntl,sys,time; f=open(sys.argv[1],"a+"); fcntl.flock(f,fcntl.LOCK_EX); print("locked",flush=True); time.sleep(30)'
            child = subprocess.Popen([sys.executable, '-c', code, path], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                with open(path, 'a+') as lock:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    child.kill()
                    child.wait()
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stdout.close()


if __name__ == '__main__':
    unittest.main()
