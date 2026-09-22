from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_amazon_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_amazon_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_amazon_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_amazon_jobs
SPEC.loader.exec_module(fetch_amazon_jobs)


SEARCH_URL = (
    "https://www.amazon.jobs/en/search?offset=0&result_limit=10&sort=recent&"
    "category%5B%5D=software-development&job_type%5B%5D=Full-Time&"
    "city%5B%5D=Bengaluru&city%5B%5D=Hyderabad"
)


class AmazonFetchTests(unittest.TestCase):
    def test_translates_browser_search_filters_to_json_api(self):
        url = fetch_amazon_jobs.api_url(SEARCH_URL, offset=20, result_limit=10)

        self.assertIn("/en/search.json?", url)
        self.assertIn("schedule_type_id%5B%5D=Full-Time", url)
        self.assertIn("normalized_city_name%5B%5D=Bengaluru", url)
        self.assertIn("offset=20", url)
        self.assertNotIn("job_type", url)

    def test_normalises_public_result_to_import_schema(self):
        result = fetch_amazon_jobs.normalise_result({
            "id_icims": "10553343",
            "title": "SDE I",
            "company_name": "Amazon Dev Center India",
            "location": "IN, TS, Hyderabad",
            "job_path": "/en/jobs/10553343/sde-i",
            "description": "<p>Build services.</p>",
            "basic_qualifications": "<p>1+ years of experience.</p>",
            "preferred_qualifications": "<p>Java preferred.</p>",
            "posted_date": "September 18, 2026",
        })

        assert result is not None
        self.assertEqual(result["id"], "10553343")
        self.assertEqual(result["application_url"], "https://www.amazon.jobs/en/jobs/10553343/sde-i")
        self.assertIn("1+ years", result["jobDescriptionText"])

    def test_skips_result_without_required_job_content(self):
        self.assertIsNone(fetch_amazon_jobs.normalise_result({"id_icims": "123", "title": "SDE"}))


if __name__ == "__main__":
    unittest.main()
