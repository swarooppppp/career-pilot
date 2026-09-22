import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import sync_jobs


class SyncJobsTests(unittest.TestCase):
    def test_fetches_sources_concurrently_then_imports_serially(self):
        sources = [
            sync_jobs.SourceSpec("alpha", Path("alpha.json"), ["fetch", "alpha"]),
            sync_jobs.SourceSpec("beta", Path("beta.json"), ["fetch", "beta"]),
        ]
        active_fetches = 0
        max_active_fetches = 0
        lock = threading.Lock()
        calls = []

        def fake_run(command):
            nonlocal active_fetches, max_active_fetches
            if command[0] == "fetch":
                with lock:
                    active_fetches += 1
                    max_active_fetches = max(max_active_fetches, active_fetches)
                time.sleep(0.03)
                with lock:
                    active_fetches -= 1
            calls.append(command)

        with patch.object(sync_jobs, "configured_sources", return_value=sources), \
                patch.object(sync_jobs, "run_command", side_effect=fake_run), \
                patch.dict("os.environ", {"JOB_FETCH_CONCURRENCY": "2"}):
            sync_jobs.sync_configured_jobs()

        self.assertEqual(max_active_fetches, 2)
        first_import = next(index for index, call in enumerate(calls) if "ingest_jobs.py" in str(call))
        self.assertTrue(all(call[0] == "fetch" for call in calls[:first_import]))
        self.assertEqual([call[-1] for call in calls[first_import:]], ["alpha", "beta"])

    def test_imports_successes_then_reports_fetch_failures(self):
        sources = [
            sync_jobs.SourceSpec("alpha", Path("alpha.json"), ["fetch", "alpha"]),
            sync_jobs.SourceSpec("beta", Path("beta.json"), ["fetch", "beta"]),
        ]
        calls = []

        def fake_run(command):
            if command == ["fetch", "beta"]:
                raise RuntimeError("blocked")
            calls.append(command)

        with patch.object(sync_jobs, "configured_sources", return_value=sources), \
                patch.object(sync_jobs, "run_command", side_effect=fake_run), \
                patch.dict("os.environ", {"JOB_FETCH_CONCURRENCY": "2"}):
            with self.assertRaisesRegex(RuntimeError, "beta: blocked"):
                sync_jobs.sync_configured_jobs()

        self.assertTrue(any("ingest_jobs.py" in str(command) and command[-1] == "alpha" for command in calls))


if __name__ == "__main__":
    unittest.main()
