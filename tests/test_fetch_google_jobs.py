from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_google_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_google_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_google_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_google_jobs
SPEC.loader.exec_module(fetch_google_jobs)


class GoogleDetailUrlTests(unittest.TestCase):
    def test_builds_detail_page_not_sign_in_application_url(self):
        url = fetch_google_jobs.job_detail_url(
            "https://www.google.com/about/careers/applications/jobs/results/?q=Software+Engineer&page=3",
            "85847378480767686",
            "Senior Software Engineer, Search Platforms",
        )
        self.assertEqual(
            url,
            "https://www.google.com/about/careers/applications/jobs/results/"
            "85847378480767686-senior-software-engineer-search-platforms?q=Software+Engineer",
        )
        self.assertNotIn("signin", url)


if __name__ == "__main__":
    unittest.main()
