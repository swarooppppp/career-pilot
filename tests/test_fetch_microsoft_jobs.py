from __future__ import annotations

import io
import importlib.util
import json
import sys
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_microsoft_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_microsoft_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_microsoft_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_microsoft_jobs
SPEC.loader.exec_module(fetch_microsoft_jobs)


def response(data: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps({"status": 200, "data": data}).encode("utf-8"))


def http_error(code: int, retry_after: str | None = None) -> HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPError("https://example.test/jobs", code, "error", headers, None)


class MicrosoftFetchRetryTests(unittest.TestCase):
    def get_json(self, **kwargs):
        return fetch_microsoft_jobs.get_json("/api/test", {"query": "test"}, timeout=10, **kwargs)

    def test_retries_a_429_then_returns_the_successful_response(self):
        with patch.object(fetch_microsoft_jobs, "urlopen", side_effect=[http_error(429), response({"ok": True})]) as urlopen:
            with patch.object(fetch_microsoft_jobs.time, "sleep") as sleep:
                self.assertEqual(self.get_json(), {"ok": True})

        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(2)

    def test_retry_after_header_overrides_the_exponential_backoff(self):
        with patch.object(fetch_microsoft_jobs, "urlopen", side_effect=[http_error(429, "7.5"), response({"ok": True})]):
            with patch.object(fetch_microsoft_jobs.time, "sleep") as sleep:
                self.assertEqual(self.get_json(), {"ok": True})

        sleep.assert_called_once_with(7.5)

    def test_uses_exponential_backoff_for_each_retry(self):
        requests = [http_error(429) for _ in range(4)] + [response({"ok": True})]
        with patch.object(fetch_microsoft_jobs, "urlopen", side_effect=requests):
            with patch.object(fetch_microsoft_jobs.time, "sleep") as sleep:
                self.assertEqual(self.get_json(), {"ok": True})

        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4, 8, 16])

    def test_raises_after_the_final_429(self):
        with patch.object(fetch_microsoft_jobs, "urlopen", side_effect=[http_error(429) for _ in range(5)]) as urlopen:
            with patch.object(fetch_microsoft_jobs.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "HTTP 429 from"):
                    self.get_json()

        self.assertEqual(urlopen.call_count, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2, 4, 8, 16])

    def test_does_not_retry_other_http_errors(self):
        with patch.object(fetch_microsoft_jobs, "urlopen", side_effect=http_error(404)) as urlopen:
            with patch.object(fetch_microsoft_jobs.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "HTTP 404 from"):
                    self.get_json()

        urlopen.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
