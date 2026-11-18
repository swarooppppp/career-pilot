"""Oracle source geography, full descriptions and incomplete-result safeguards."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local_career_portals"))
import fetch_oracle_india_jobs as oracle


class OracleTests(unittest.TestCase):
    def detail(self, **changes):
        return {"Id": "123", "Title": "Software Engineer", "PrimaryLocation": "India",
                "PrimaryLocationCountry": "IN", "ExternalDescriptionStr": "<p>Build systems.</p>",
                "ExternalResponsibilitiesStr": "<p>Maintain systems.</p>",
                "ExternalQualificationsStr": "<p>Python experience.</p>",
                "ExternalPostedStartDate": "2026-11-16T09:00:00Z", **changes}

    def normalize(self, **changes):
        return oracle.normalize(self.detail(**changes), "Akamai", "https://example.com", "CX_1")

    def test_description_sections_and_publication_retained(self):
        job = self.normalize()
        self.assertIn("Build systems.", job["jobDescriptionText"])
        self.assertIn("Maintain systems.", job["jobDescriptionText"])
        self.assertIn("Python experience.", job["jobDescriptionText"])
        self.assertEqual(job["posted_date"], "2026-11-16T09:00:00Z")

    def test_secondary_india_location_is_eligible(self):
        self.assertIsNotNone(self.normalize(PrimaryLocation="Poland", PrimaryLocationCountry="PL",
            secondaryLocations=[{"LocationName": "Bengaluru, India"}]))

    def test_foreign_and_support_jobs_are_excluded(self):
        self.assertIsNone(self.normalize(PrimaryLocation="Poland", PrimaryLocationCountry="PL"))
        self.assertIsNone(self.normalize(Title="Technical Support Engineer"))

    def test_missing_full_description_fails(self):
        with self.assertRaisesRegex(RuntimeError, "full description"):
            self.normalize(ExternalDescriptionStr="")

    def test_incomplete_pagination_fails_instead_of_empty_success(self):
        payload = json.dumps({"items": [{"TotalJobsCount": 200, "requisitionList": []}]})
        with patch.object(oracle, "read", return_value=payload):
            with self.assertRaisesRegex(RuntimeError, "pagination ended"):
                oracle.collect("https://example.com", "Akamai", delay=0)

    def test_title_candidate_with_foreign_primary_still_hydrates_secondary(self):
        listing = json.dumps({"items": [{"TotalJobsCount": 1, "requisitionList": [
            {"Id": "123", "Title": "Software Engineer", "PrimaryLocationCountry": "PL"}]}]})
        detail = self.detail(PrimaryLocation="Poland", PrimaryLocationCountry="PL",
                             secondaryLocations=[{"LocationName": "India"}])
        with patch.object(oracle, "read", side_effect=[listing, json.dumps({"items": [detail]})]):
            jobs, total = oracle.collect("https://example.com", "Akamai", delay=0)
        self.assertEqual((len(jobs), total), (1, 1))


if __name__ == "__main__":
    unittest.main()
