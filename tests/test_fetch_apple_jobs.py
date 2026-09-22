from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_apple_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_apple_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_apple_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_apple_jobs
SPEC.loader.exec_module(fetch_apple_jobs)


class AppleFetchTests(unittest.TestCase):
    def test_decodes_static_router_hydration_data(self):
        data = {"loaderData": {"search": {"searchResults": []}}}
        encoded = json.dumps(json.dumps(data))
        self.assertEqual(fetch_apple_jobs.hydration_data(f"<script>window.__staticRouterHydrationData = JSON.parse({encoded})</script>"), data)

    def test_adds_page_without_losing_filters(self):
        url = fetch_apple_jobs.with_page("https://jobs.apple.com/en-in/search?location=india-INDC&key=Software%2520Engineer", 2)
        self.assertIn("location=india-INDC", url)
        self.assertIn("page=2", url)

    def test_normalises_apple_detail_sections(self):
        result = fetch_apple_jobs.normalise_result(
            {"id": "200001", "postingTitle": "Software Engineer", "postDateInGMT": "2026-09-22",
             "locations": [{"name": "Hyderabad, India"}]},
            {"jobSummary": "<p>Build services.</p>", "minimumQualifications": "<ul><li>Java</li></ul>"},
            "https://jobs.apple.com/en-in/details/200001/software-engineer",
        )
        assert result is not None
        self.assertEqual(result["company"], "Apple")
        self.assertIn("Minimum qualifications", result["jobDescriptionText"])
        self.assertIn("Java", result["jobDescriptionText"])


if __name__ == "__main__":
    unittest.main()
