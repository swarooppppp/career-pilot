from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_salesforce_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_salesforce_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_salesforce_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_salesforce_jobs
SPEC.loader.exec_module(fetch_salesforce_jobs)


class SalesforceFetchTests(unittest.TestCase):
    def test_matches_the_search_url_filters(self):
        query = fetch_salesforce_jobs.parse_qs(
            "country=India&employeeTypes=Regular&team=Software+Engineering"
        )
        matching = {
            "Job_Family_Group": "Software Engineering", "Employee_Type": "Regular", "Countries": ["India"],
        }
        self.assertTrue(fetch_salesforce_jobs.matches(matching, query))
        self.assertFalse(fetch_salesforce_jobs.matches({**matching, "Employee_Type": "Intern"}, query))

    def test_normalises_static_dataset_job_to_import_schema(self):
        result = fetch_salesforce_jobs.normalise_result({
            "Job_Requisition_Ref_ID": "JR123", "Job_Posting_Title": "Software Engineer",
            "Job_Description": "<p>Build reliable APIs.</p>",
            "External_Job_Posting_Site": "https://careers.salesforce.com/en/jobs/jr123/",
            "External_Job_Posting_Start_Date": "2026-09-22", "Locations": ["Hyderabad, India"],
        })
        assert result is not None
        self.assertEqual(result["id"], "JR123")
        self.assertEqual(result["company"], "Salesforce")
        self.assertEqual(result["location"], "Hyderabad, India")
        self.assertIn("Build reliable APIs.", result["jobDescriptionText"])


if __name__ == "__main__":
    unittest.main()
