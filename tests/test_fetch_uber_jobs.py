from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_uber_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_uber_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_uber_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_uber_jobs
SPEC.loader.exec_module(fetch_uber_jobs)


class UberFetchTests(unittest.TestCase):
    def test_accepts_public_uber_search_url(self):
        fetch_uber_jobs.validate_search_url(
            "https://jobs.uber.com/en/jobs/?team=Engineer&countries=India"
        )

    def test_rejects_non_uber_or_non_search_url(self):
        with self.assertRaises(ValueError):
            fetch_uber_jobs.validate_search_url("https://example.com/en/jobs/?team=Engineer")

    def test_normalises_api_result_to_import_schema(self):
        result = fetch_uber_jobs.normalise_result({
            "Id": "301977", "Title": "Sr Staff Engineer - Engineer",
            "Description": "<p>Build reliable services.</p>", "DisplayDate": "2026-09-21T06:01:55Z",
            "Locations": [{"Address": "Bengaluru, Karnataka, India"}],
            "Urls": [{"Culture": "en-us", "Url": "/en/jobs/301977/", "IsDefault": True}],
        })

        assert result is not None
        self.assertEqual(result["id"], "301977")
        self.assertEqual(result["company"], "Uber")
        self.assertEqual(result["location"], "Bengaluru, Karnataka, India")
        self.assertIn("Build reliable services.", result["jobDescriptionText"])


if __name__ == "__main__":
    unittest.main()
