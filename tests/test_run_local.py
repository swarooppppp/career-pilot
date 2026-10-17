from __future__ import annotations

import sys
import unittest
from unittest.mock import Mock, patch

import run_local


class RunLocalTests(unittest.TestCase):
    def test_sync_jobs_runs_in_a_daemon_thread_before_server_start(self) -> None:
        thread = Mock()
        with patch.object(sys, "argv", ["run_local.py", "--sync-jobs"]), \
                patch.object(run_local.threading, "Thread", return_value=thread) as new_thread, \
                patch.object(run_local.uvicorn, "run") as run_server:
            run_local.main()
        new_thread.assert_called_once_with(
            target=run_local.sync_configured_jobs,
            kwargs={"strict": False},
            name="portal-sync",
            daemon=True,
        )
        thread.start.assert_called_once_with()
        run_server.assert_called_once()


if __name__ == "__main__":
    unittest.main()
