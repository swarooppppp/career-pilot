from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_intuit_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_intuit_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_intuit_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_intuit_jobs
SPEC.loader.exec_module(fetch_intuit_jobs)


class IntuitFetchTests(unittest.TestCase):
    def test_preserves_search_query_and_adds_page(self):
        url = fetch_intuit_jobs.page_url("https://jobs.intuit.com/search-jobs?acm=68357", 2)
        self.assertIn("acm=68357", url)
        self.assertIn("p=2", url)

    def test_extracts_search_card(self):
        jobs = fetch_intuit_jobs.extract_results(
            '<a class="sr-item" href="/job/bengaluru/sde/27595/123" data-title="SDE">'
            '<span class="job-location">Bangalore, India</span></a>'
        )
        self.assertEqual(jobs[0]["location"], "Bangalore, India")
        self.assertEqual(jobs[0]["url"], "https://jobs.intuit.com/job/bengaluru/sde/27595/123")

    def test_normalises_json_ld_job(self):
        result = fetch_intuit_jobs.normalise_result(
            {"title": "SDE", "location": "Bangalore, India", "url": "https://jobs.intuit.com/job/x"},
            {"@type": "JobPosting", "identifier": "24142", "title": "SDE", "description": "<p>Build APIs.</p>",
             "url": "https://jobs.intuit.com/job/x", "datePosted": "2026-09-22"},
        )
        assert result is not None
        self.assertEqual(result["id"], "24142")
        self.assertEqual(result["company"], "Intuit")
        self.assertIn("Build APIs.", result["jobDescriptionText"])


if __name__ == "__main__":
    unittest.main()
