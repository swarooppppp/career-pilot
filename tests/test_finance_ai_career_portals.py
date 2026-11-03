"""Native taxonomy, date semantics and transport tests for the fourth batch."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_additional_board_jobs as board
import fetch_de_shaw_jobs as shaw
import fetch_eightfold_company_jobs as eightfold
from filters import in_india


class FourthBatchTests(unittest.TestCase):
    def test_coinbase_engineering_subdepartments_exclude_other_functions(self):
        jobs = [{"id": 1, "location": {"name": "Remote - India"}, "departments": [{"id": 1, "name": "Engineering - Backend"}]},
                {"id": 2, "location": {"name": "India"}, "departments": [{"id": 2, "name": "Finance"}]}]
        self.assertEqual([j["id"] for j in board.select_jobs(jobs, "coinbase", "https://www.coinbase.com/careers/positions")], [1])

    def test_technology_department_requires_engineering_title_before_limit(self):
        jobs = [{"id": 1, "title": "Product Manager", "location": {"name": "Bangalore"}, "departments": [{"id": 1, "name": "Technology"}]},
                {"id": 2, "title": "Software Developer", "location": {"name": "Bangalore"}, "departments": [{"id": 1, "name": "Technology"}]}]
        for source in ("squarepoint", "arcesium"):
            self.assertEqual([j["id"] for j in board.select_jobs(jobs, source, "https://example.test")], [2])
        self.assertTrue(in_india({"location": "Gift City"}))

    def test_quant_developers_are_not_lost_to_trading_department_labels(self):
        jobs = [{"id": 1, "title": "Quantitative Developer", "location": {"name": "Gurgaon"}, "departments": [{"id": 1, "name": "Quantitative Research & Trading"}]},
                {"id": 2, "title": "Experienced Quantitative Trader", "location": {"name": "Gurgaon"}, "departments": [{"id": 1, "name": "Quantitative Research & Trading"}]}]
        self.assertEqual([j["id"] for j in board.select_jobs(jobs, "tower_research", "https://tower-research.com/roles/")], [1])

    def test_shaw_excludes_exploratory_finance_inactive_and_foreign_jobs(self):
        def job(ident, department="Core Tech", exploratory=False, active=True, city="Hyderabad"):
            return {"data": {"id": ident, "displayName": "Member Technical Staff", "jobUrl": f"job-{ident}", "activeOnJobsListing": active,
                             "department": {"name": department}, "jobMetadata": {"isExploratory": exploratory, "jobLocations": [{"name": city}]},
                             "jobDescription": {"websiteDescription": "Build systems", "responsibilities": "Implement", "peopleWeAreLookingForHtml": "<p>Requirements</p>"}}}
        data = {"props": {"pageProps": {"regularJobs": [job(1), job(2, exploratory=True), job(3, department="Financial Operations"), job(4, active=False), job(5, city="London")], "jobsFetchingError": False}}}
        results = shaw.normalize('<script id="__NEXT_DATA__">' + json.dumps(data) + '</script>')
        self.assertEqual([j["id"] for j in results], ["1"])
        self.assertIn("Requirements", results[0]["jobDescriptionText"])
        self.assertIsNone(results[0]["posted_date"])

    def test_millennium_update_timestamp_is_not_a_posting_date(self):
        summary = {"id": 1, "name": "Software Engineer", "locations": ["India"]}
        detail = {"job_description": "<p>Full role</p>", "locations": ["India"], "t_update": 1700000000, "t_create": 1600000000}
        result = eightfold.normalize(summary, detail, "https://career.mlp.com", "Millennium Management", "v2")
        self.assertIsNone(result["posted_date"])
        self.assertIsNotNone(result["updated_date"])
        self.assertEqual(result["application_url"], "https://career.mlp.com/careers/job/1")

    def test_nvidia_uses_confirmed_camel_case_facet_and_full_description(self):
        first = {"status": 200, "data": {"count": 1, "positions": [{"id": 1, "name": "Software Engineer", "locations": ["India"], "postedTs": 1700000000}], "appliedFilters": {"jobCategory": ["engineering"]}}}
        detail = {"status": 200, "data": {"name": "Software Engineer", "locations": ["India"], "jobDescription": "<p>Build systems</p>"}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jobs.json"
            with patch.object(sys, "argv", ["fetch", "https://jobs.nvidia.com/careers?query=Software+Engineer", "--source", "nvidia", "--max-jobs", "1", "--delay", "0", "--output", str(output)]), \
                    patch.object(eightfold, "read", side_effect=[json.dumps(first), json.dumps(detail)]) as read:
                eightfold.main()
            self.assertEqual(read.call_count, 2)
            self.assertIn("filter_job_category=engineering", read.call_args_list[0].args[0])
            result = json.loads(output.read_text())["jobs"][0]
            self.assertIsNotNone(result["posted_date"])
            self.assertEqual(result["jobDescriptionText"], "Build systems")


if __name__ == "__main__":
    unittest.main()
