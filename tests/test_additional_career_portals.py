"""Verify third-batch native taxonomy, country and URL filter semantics."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_additional_board_jobs as board
import fetch_smartrecruiters_jobs as smart
import fetch_adobe_india_jobs as adobe_india


class AdditionalPortalTests(unittest.TestCase):
    def test_airbnb_uses_actual_engineering_departments_and_india(self):
        jobs = [{"id": 1, "location": {"name": "India"}, "departments": [{"id": 1, "name": "Software Engineering"}]},
                {"id": 2, "location": {"name": "India"}, "departments": [{"id": 2, "name": "Analytics"}]},
                {"id": 3, "location": {"name": "London"}, "departments": [{"id": 1, "name": "Software Engineering"}]}]
        self.assertEqual([j["id"] for j in board.select_jobs(jobs, "airbnb", "https://careers.airbnb.com/positions/")], [1])

    def test_palo_json_entities_are_not_unescaped_before_json_parse(self):
        spec = importlib.util.spec_from_file_location("palo_entity_test", DIRECTORY.parent / "career portal scripts/fetch_palo_alto_jobs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        schema = {"@type": "JobPosting", "description": "Write &#34;RAG-ready&#34; documentation"}
        document = '<script type="application/ld+json">' + json.dumps(schema) + '</script>'
        self.assertEqual(module.job_posting(document, "https://example.test/job")["description"], schema["description"])

    def test_adobe_filters_and_orders_before_requesting_details(self):
        jobs = [{"reqId": "us", "title": "Software Engineer", "country": "USA", "postedDate": "2026-10-31"},
                {"reqId": "old", "title": "Software Engineer", "country": "India", "postedDate": "2026-10-01"},
                {"reqId": "new", "title": "Software Engineer", "country": "India", "postedDate": "2026-10-30"}]
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "argv", ["fetch", "--max-jobs", "1", "--delay", "0", "--output", str(Path(directory) / "jobs.json")]), \
                patch.object(adobe_india.adapter, "fetch_search_page", return_value={"hits": 10, "totalHits": 3, "data": {"jobs": jobs}}), \
                patch.object(adobe_india.adapter, "fetch_detail", return_value={"reqId": "new", "title": "Software Engineer", "description": "Full role", "location": "India"}) as detail:
            adobe_india.main()
        detail.assert_called_once_with("new", "Software Engineer", 30)

    def test_nutanix_403_gets_only_one_headed_fallback(self):
        spec = importlib.util.spec_from_file_location("nutanix_fallback_test", DIRECTORY.parent / "career portal scripts/fetch_nutanix_jobs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        attempts = []
        async def fetch(url, limit, timeout, skip, headed):
            attempts.append(headed)
            raise module.BrowserAccessRequired("HTTP 403")
        with tempfile.TemporaryDirectory() as directory, patch.object(module, "fetch_jobs", fetch), \
                patch.object(sys, "argv", ["fetch", "--headed-fallback", "--output", str(Path(directory) / "jobs.json")]):
            self.assertEqual(module.main(), 1)
        self.assertEqual(attempts, [False, True])

    def test_nutanix_429_does_not_launch_headed_retry(self):
        spec = importlib.util.spec_from_file_location("nutanix_429_test", DIRECTORY.parent / "career portal scripts/fetch_nutanix_jobs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        attempts = []
        async def fetch(url, limit, timeout, skip, headed):
            attempts.append(headed)
            raise RuntimeError("HTTP 429; no immediate retry")
        with patch.object(module, "fetch_jobs", fetch), patch.object(sys, "argv", ["fetch", "--headed-fallback"]):
            self.assertEqual(module.main(), 1)
        self.assertEqual(attempts, [False])

    def test_razorpay_department_id_includes_descendants_not_sales(self):
        jobs = [
            {"id": 1, "location": {"name": "Bengaluru"}, "departments": [{"id": 4024806005, "name": "Engineering", "child_ids": [2]}]},
            {"id": 2, "location": {"name": "Pune"}, "departments": [{"id": 2, "name": "DevOps", "parent_id": 4024806005}]},
            {"id": 3, "location": {"name": "India"}, "departments": [{"id": 3, "name": "Sales Engineering"}]},
            {"id": 4, "location": {"name": "London"}, "departments": [{"id": 2, "name": "DevOps", "parent_id": 4024806005}]}]
        result = board.select_jobs(jobs, "razorpay", "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited?departments%5B%5D=4024806005")
        self.assertEqual([j["id"] for j in result], [1, 2])

    def test_fivetran_repeated_locations_are_or_and_regular_is_required(self):
        def job(ident, location, employment="Regular"):
            return {"id": ident, "location": {"name": location}, "departments": [{"id": 1, "name": "Engineering Department"}], "metadata": [{"name": "Employee Type", "value": employment}]}
        jobs = [job(1, "Bangalore, India"), job(2, "Bengaluru, Karnataka, India, APAC"),
                job(3, "Remote, India, APAC"), job(4, "Toronto, Ontario, Canada"),
                job(5, "Remote, India", "Contractor"), job(6, "Pune, India")]
        url = "https://www.fivetran.com/careers?dept=Engineering+Department&loc=Bangalore%2C+India&loc=Bengaluru%2C+Karnataka%2C+India&loc=Remote%2C+India&type=Regular"
        self.assertEqual([j["id"] for j in board.select_jobs(jobs, "fivetran", url)], [1, 2, 3])

    def test_phonepe_excludes_unpublished_and_non_engineering(self):
        def job(ident, status="PUBLIC", department="Engineering", location="Bengaluru"):
            return {"status": status, "department": department, "location": location, "applyUrl": f"https://jobs.smartrecruiters.com/PHONEPELIMITED/{ident}-engineer", "updatedAt": f"/Date({ident * 1000})/"}
        jobs = [job(1), job(2), job(3, "NOT_PUBLISHED"), job(4, department="Sales"), job(5, location="London")]
        self.assertEqual([j["id"] for j in smart.phonepe_summaries({"results": jobs})], ["2", "1"])

    def test_servicenow_checks_function_country_and_city_aliases(self):
        job = {"location": {"country": "in", "city": "Bengaluru"}, "function": {"id": "engineering"}}
        self.assertTrue(smart.servicenow_matches(job, {"bangalore", "hyderabad"}))
        self.assertFalse(smart.servicenow_matches(job, {"mumbai"}))
        job["function"]["id"] = "sales"
        self.assertFalse(smart.servicenow_matches(job, {"bangalore"}))
        job["function"]["id"] = "engineering"
        job["location"]["country"] = "us"
        self.assertFalse(smart.servicenow_matches(job, {"bangalore"}))
        self.assertEqual(smart.city_key("Gurugram"), smart.city_key("Gurgaon"))

    def test_full_description_keeps_qualifications_and_rejects_summaries(self):
        with self.assertRaises(RuntimeError):
            smart.description_html({"jobAd": {"sections": {"companyDescription": {"text": "Company only"}}}})
        result = smart.description_html({"jobAd": {"sections": {
            "jobDescription": {"text": "<p>Build</p>"}, "qualifications": {"text": "<p>Required skills</p>"}}}})
        self.assertIn("Required skills", result)

    def test_nutanix_preserves_structured_india_location(self):
        spec = importlib.util.spec_from_file_location("nutanix_local_test", DIRECTORY.parent / "career portal scripts/fetch_nutanix_jobs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        schema = {"@type": "JobPosting", "description": "<p>Build</p>", "jobLocation": {"address": {"addressLocality": "Bangalore", "addressCountry": "IN"}}}
        parsed = module.posting('<script type="application/ld+json">' + json.dumps(schema) + '</script>')
        self.assertEqual(module.locations(parsed["jobLocation"]), "Bangalore, India")


if __name__ == "__main__":
    unittest.main()
