"""Department, vacancy, location and publication boundaries for batch eight."""
import json
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_additional_board_jobs as boards
import fetch_ashby_jobs as ashby
import fetch_thoughtspot_jobs as thoughtspot


class DataAIPortalTests(unittest.TestCase):
    def board_job(self, ident, title, department="Engineering", location="India", **kwargs):
        return {"id": ident, "title": title, "location": {"name": location},
                "departments": [{"id": 10, "name": department}], **kwargs}

    def test_native_engineering_includes_security_researchers_and_descendants(self):
        jobs = [self.board_job(1, "Senior Security Researcher"),
                self.board_job(2, "Researcher", departments=[{"id": 11, "name": "Security", "parent_id": 10}]),
                self.board_job(3, "Engineer", department="Customer Solutions", departments=[{"id": 12, "name": "Customer Solutions"}]),
                self.board_job(4, "Researcher", location="Remote, United States")]
        self.assertEqual([j["id"] for j in boards.select_jobs(jobs, "endor_labs", "https://example.test")], [1, 2])

    def test_talent_communities_are_not_open_vacancies(self):
        jobs = [self.board_job(1, "Talent Community – Engineering & Product, India"),
                self.board_job(2, "General Application - Software Engineer"),
                self.board_job(3, "Software Engineer")]
        for source in ["yugabyte", "singlestore", "startree", "prophecy", "devrev", "endor_labs"]:
            self.assertEqual([j["id"] for j in boards.select_jobs(jobs, source, "https://example.test")], [3])

    def test_singlestore_technical_team_names_and_sales_exclusions(self):
        jobs = [self.board_job(1, "Software Engineer", "Engine"),
                self.board_job(2, "Cloud Platform Engineer", "Internal Services"),
                self.board_job(3, "Principal Architect", "EMEA SE"),
                self.board_job(4, "Technical Support Engineer", "Technical Support"),
                self.board_job(5, "Engineer", location="Remote")]
        self.assertEqual([j["id"] for j in boards.select_jobs(jobs, "singlestore", "https://example.test")], [1, 2])

    def test_ashby_engineering_department_required_for_new_boards(self):
        job = {"id": "1", "title": "Solutions Architect", "department": "Sales", "location": "Bengaluru",
               "isListed": True, "descriptionHtml": "<p>Build products</p>", "jobUrl": "https://jobs.ashbyhq.com/Ema/1"}
        self.assertEqual(ashby.normalize([job], "Ema", department="Engineering"), [])
        job.update(title="Software Engineer", department="Engineering", publishedAt="2026-11-01")
        self.assertEqual(ashby.normalize([job], "Ema", department="Engineering")[0]["posted_date"], "2026-11-01")
        job["location"] = "United States"
        self.assertEqual(ashby.normalize([job], "Ema", department="Engineering"), [])

    def summary(self, title="Member of Technical Staff-3", department="Engineering and Product Management", country="India"):
        return {"id": "1", "name": title, "url": "https://ats.rippling.com/thoughtspot/jobs/1",
                "department": {"name": department}, "locations": [{"name": country, "country": country}]}

    def test_thoughtspot_mixed_department_keeps_technical_leads_not_product_managers(self):
        for title in ["Member of Technical Staff-3", "Tech Lead Manager", "Technical Lead Manager"]:
            self.assertTrue(thoughtspot.eligible(self.summary(title)))
        self.assertFalse(thoughtspot.eligible(self.summary("Product Manager")))
        self.assertFalse(thoughtspot.eligible(self.summary("Technical Program Manager")))
        self.assertFalse(thoughtspot.eligible(self.summary("Developer", department="Sales")))
        self.assertFalse(thoughtspot.eligible(self.summary(country="United States")))

    def test_rippling_full_detail_identity_and_creation_date_are_distinct(self):
        detail = {"uuid": "1", "companyName": "ThoughtSpot", "name": "Software Engineer",
                  "description": {"company": "<p>About ThoughtSpot</p>", "role": '<p>Build "AI" &amp; data products</p>'},
                  "createdOn": "2026-10-01", "unlistedFromSearch": False}
        document = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps({
            "props": {"pageProps": {"apiData": {"jobPost": detail}}}}) + '</script>'
        result = thoughtspot.normalize(self.summary(), thoughtspot.detail_data(document))
        self.assertIn('Build "AI" & data products', result["jobDescriptionText"])
        self.assertIn("About ThoughtSpot", result["jobDescriptionText"])
        self.assertIsNone(result["posted_date"])
        self.assertEqual(result["source_created_date"], "2026-10-01")
        detail["jsonLd"] = {"datePosted": "2026-10-02"}
        self.assertEqual(thoughtspot.normalize(self.summary(), detail)["posted_date"], "2026-10-02")
        detail["uuid"] = "wrong-job"
        with self.assertRaises(RuntimeError):
            thoughtspot.normalize(self.summary(), detail)
        with self.assertRaises(RuntimeError):
            thoughtspot.detail_data("<html>Verification required</html>")

    def test_instabase_unavailable_source_is_excluded_from_default_runs(self):
        inventory = json.loads((DIRECTORY / "companies.json").read_text())
        company = next(c for c in inventory["companies"] if c["slug"] == "instabase")
        self.assertEqual(company["status"], "source_unavailable")
        self.assertTrue((DIRECTORY.parent / company["existing_script"]).exists())


if __name__ == "__main__":
    unittest.main()
