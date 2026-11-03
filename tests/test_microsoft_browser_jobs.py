"""Verify retry limits and cache behavior without hitting Microsoft."""
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_microsoft_browser_jobs as microsoft


class MicrosoftBrowserTests(unittest.TestCase):
    def test_user_filters_survive_and_selected_job_is_removed(self):
        url, query = microsoft.configure_url(microsoft.DEFAULT_URL + "&pid=123")
        self.assertNotIn("pid=", url)
        self.assertEqual(query["filter_profession"], ["software engineering"])
        self.assertEqual(query["filter_seniority"], ["Mid-Level,Senior,Entry"])
        self.assertEqual(query["filter_include_relocation"], ["0"])
        self.assertEqual(query["sort_by"], ["timestamp"])

    def test_retry_after_handles_seconds_and_http_date(self):
        self.assertEqual(microsoft.retry_seconds("120", 1000), 120)
        date = format_datetime(datetime.fromtimestamp(1120, timezone.utc), usegmt=True)
        self.assertEqual(microsoft.retry_seconds(date, 1000), 120)
        self.assertEqual(microsoft.retry_seconds("invalid", 1000), 60)
        self.assertEqual(microsoft.retry_seconds("nan", 1000), 60)

    def test_429_saves_cooldown_and_does_not_retry_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(state_file=Path(directory) / "state.json", max_retries=0, max_retry_wait=10, delay=0, timeout=10)
            page = Mock()
            page.evaluate.return_value = {"status": 429, "retryAfter": "120", "text": ""}
            state = {"details": {}}
            client = microsoft.BrowserClient(page, args, state)
            with patch.object(microsoft.time, "time", return_value=1000), patch.object(microsoft.time, "sleep"):
                with self.assertRaises(microsoft.CooldownRequired):
                    client.get_json("/api/pcsx/search", {})
            self.assertEqual(state["cooldown_until"], 1120)
            self.assertTrue(args.state_file.exists())
            page.evaluate.assert_called_once()

    def test_long_cooldown_is_not_shortened_to_fit_retry_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(state_file=Path(directory) / "state.json", max_retries=2, max_retry_wait=10)
            client = microsoft.BrowserClient(Mock(), args, {"details": {}})
            with patch.object(microsoft.time, "sleep") as sleep:
                with self.assertRaises(microsoft.CooldownRequired):
                    client.cooldown("120", 0)
            sleep.assert_not_called()

    def test_next_run_with_active_cooldown_never_launches_browser(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            microsoft.save_state(state, {"details": {}, "cooldown_until": 2000})
            with patch.object(sys, "argv", ["fetch", "--state-file", str(state)]), \
                    patch.object(microsoft.time, "time", return_value=1000), patch.object(microsoft, "fetch") as fetch:
                with self.assertRaises(microsoft.CooldownRequired):
                    microsoft.main()
            fetch.assert_not_called()

    def test_cache_expires_and_changed_posting_is_refetched(self):
        summary = {"postedTs": 10, "name": "Software Engineer"}
        entry = {"postedTs": 10, "name": "Software Engineer", "fetched_at": 100, "job": {"jobDescriptionHtml": "<p>Full role</p>"}}
        self.assertTrue(microsoft.cache_valid(entry, summary, 110, 60))
        self.assertFalse(microsoft.cache_valid(entry, summary, 170, 60))
        self.assertFalse(microsoft.cache_valid(entry, {**summary, "postedTs": 11}, 110, 60))


if __name__ == "__main__":
    unittest.main()
