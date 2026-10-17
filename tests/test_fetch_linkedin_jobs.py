from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_linkedin_jobs", ROOT / "career portal scripts" / "fetch_linkedin_jobs.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class LinkedInFetchTests(unittest.TestCase):
    def test_builds_scroll_url_with_offset(self) -> None:
        url = module.scroll_page_url("https://www.linkedin.com/jobs/search?keywords=Software%20Engineer&f_C=123", 50)
        self.assertEqual(url, "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=Software+Engineer&f_C=123&start=50")

    def test_reuses_public_parser_without_a_company_restriction(self) -> None:
        page_html = '''<h1 class="topcard__title">Software Engineer</h1>
        <a class="topcard__org-name-link">NVIDIA</a>
        <span class="topcard__flavor--bullet">Bengaluru, India</span>
        <div class="show-more-less-html__markup"><p>Build distributed systems.</p></div>'''
        job = module.linkedin.parse_job_page(page_html, "https://in.linkedin.com/jobs/view/software-engineer-123")
        self.assertEqual(job["company"], "NVIDIA")
        self.assertEqual(job["id"], "123")
        self.assertIn("Build distributed systems.", job["jobDescriptionText"])

    def test_rate_limit_error_is_distinct_from_other_http_failures(self) -> None:
        self.assertTrue(issubclass(module.linkedin.LinkedInRateLimitError, RuntimeError))

    def test_rejects_only_one_randomized_delay_bound(self) -> None:
        with patch.object(sys, "argv", ["fetch_linkedin_jobs.py", "https://example.test", "--min-delay", "3"]):
            with self.assertRaises(SystemExit):
                module.main()

    def test_saves_partial_snapshot_when_rate_limited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "linkedin_jobs.json"
            with patch.object(module.linkedin, "fetch_text", side_effect=["search", module.linkedin.LinkedInRateLimitError("429"), "detail"]), patch.object(module.linkedin, "extract_job_urls", return_value=["https://in.linkedin.com/jobs/view/engineer-123"]), patch.object(module, "sleep"), patch.object(sys, "argv", ["fetch_linkedin_jobs.py", "https://www.linkedin.com/jobs/search", "--delay", "0", "--429-max-retries", "0", "--output", str(output)]):
                self.assertEqual(module.main(), 0)
            payload = __import__("json").loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["jobs"], [])
            self.assertFalse(payload["complete"])
            self.assertEqual(payload["stopped_reason"], "rate_limited")

    def test_429_retries_use_capped_exponential_backoff(self) -> None:
        sleeps = []
        with patch.object(module, "sleep", side_effect=sleeps.append):
            result = module.fetch_with_429_retries(
                __import__("unittest.mock").mock.Mock(side_effect=[module.linkedin.LinkedInRateLimitError("429"), module.linkedin.LinkedInRateLimitError("429"), "ok"]),
                "detail", 10, 60, 480,
            )
        self.assertEqual(result, "ok")
        self.assertEqual(sleeps, [60, 120])

    def test_retry_after_is_capped(self) -> None:
        self.assertEqual(module.retry_delay(module.linkedin.LinkedInRateLimitError("429", 999), 1, 60, 480), (480.0, True))


if __name__ == "__main__":
    unittest.main()
