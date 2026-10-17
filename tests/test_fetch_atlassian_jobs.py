from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_atlassian_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_atlassian_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_atlassian_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_atlassian_jobs
SPEC.loader.exec_module(fetch_atlassian_jobs)


class AtlassianFetchTests(unittest.TestCase):
    def test_filters_team_location_and_all_search_words(self):
        query = fetch_atlassian_jobs.parse_qs("team=Engineering&location=India&search=Software+Engineer")
        job = {"category": "Engineering", "locations": ["Bengaluru, India"],
               "title": "Software Engineer", "overview": "Build platform services."}
        self.assertTrue(fetch_atlassian_jobs.matches(job, query))
        self.assertFalse(fetch_atlassian_jobs.matches({**job, "locations": ["Sydney, Australia"]}, query))

    def test_normalises_listing_to_import_schema(self):
        result = fetch_atlassian_jobs.normalise_result({
            "id": "abc123", "title": "Software Engineer", "locations": ["Bengaluru, India"],
            "overview": "<p>Build reliable services.</p>",
            "portalJobPost": {"portalUrl": "/company/careers/details/abc123", "updatedDate": "2026-09-22"},
        })
        assert result is not None
        self.assertEqual(result["application_url"], "https://www.atlassian.com/company/careers/details/abc123")
        self.assertIn("Build reliable services.", result["jobDescriptionText"])

    def test_extracts_full_job_posting_requirements_from_detail_page(self):
        page = (
            '<script type="application/ld+json">'
            '{"@context":"https://schema.org","@type":"JobPosting",'
            '"description":"<p>Requirements: 3+ years of experience.</p>"}'
            '</script>'
        )
        description = fetch_atlassian_jobs.detail_description(page)
        result = fetch_atlassian_jobs.normalise_result({
            "id": "abc123", "title": "Software Engineer", "locations": ["Bengaluru, India"],
            "overview": "<p>Short summary.</p>",
            "portalJobPost": {"portalUrl": "/company/careers/details/abc123"},
        }, description)
        assert result is not None
        self.assertIn("3+ years of experience.", result["jobDescriptionText"])


if __name__ == "__main__":
    unittest.main()
