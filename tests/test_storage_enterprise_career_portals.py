"""Tenant-specific Workday facets and storage/enterprise role coverage."""
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_workday_india_jobs as workday
import fetch_docusign_jobs as docusign
import fetch_arista_jobs as arista
import fetch_additional_board_jobs as greenhouse
from filters import engineering_title
from common import timestamp


class StorageEnterpriseTests(unittest.TestCase):
    def test_workday_preserves_actual_case_sensitive_country_facet(self):
        facets = [{"facetParameter": "Location_Country", "values": [{"id": "india", "descriptor": "India"}, {"id": "us", "descriptor": "United States"}]},
                  {"facetParameter": "jobFamilyGroup", "values": [{"id": "eng", "descriptor": "Product Development and Engineering"}, {"id": "sales", "descriptor": "Sales Engineering"}]}]
        self.assertEqual(workday.native_facets(facets), {"Location_Country": ["india"], "jobFamilyGroup": ["eng"]})

    def test_broadcom_uses_india_locations_when_country_facet_is_absent(self):
        facets = [{"facetParameter": "locationMainGroup", "values": [
            {"facetParameter": "locations", "values": [
                {"id": "blr", "descriptor": "IND-Bangalore-Kalyani Vista II"},
                {"id": "ind-remote", "descriptor": "IND-Remote"},
                {"id": "us", "descriptor": "USA-Indiana-Remote"}]}]}]
        self.assertEqual(workday.native_facets(facets), {"locations": ["blr", "ind-remote"]})
        with self.assertRaises(RuntimeError):
            workday.native_facets([])

    def test_workday_details_must_really_include_india(self):
        summary = {"title": "Software Engineer", "externalPath": "/job/role", "bulletFields": ["R1"]}
        detail = {"title": "Software Engineer", "country": {"descriptor": "United States"}, "location": "Boston", "jobDescription": "Build systems"}
        self.assertIsNone(workday.normalize(summary, detail, "tenant.myworkdayjobs.com", "Site", "Company"))
        detail.update(country={"descriptor": "India"}, location="Bengaluru", startDate="2026-11-01")
        result = workday.normalize(summary, detail, "tenant.myworkdayjobs.com", "Site", "Company")
        self.assertEqual(result["posted_date"], "2026-11-01")
        self.assertEqual(result["application_url"], "https://tenant.myworkdayjobs.com/Site/job/role")

    def test_mts_roles_are_included_without_admitting_sales_or_foreign_roles(self):
        self.assertTrue(engineering_title({"title": "Member of Technical Staff, Distributed Systems"}))
        jobs = [{"id": 1, "title": "Member of Technical Staff", "location": {"name": "Bangalore, India"}, "departments": [{"name": "Engineering"}]},
                {"id": 2, "title": "Sales Engineer", "location": {"name": "India"}, "departments": [{"name": "Sales"}]},
                {"id": 3, "title": "Member of Technical Staff", "location": {"name": "Indianapolis, Indiana"}, "departments": [{"name": "Engineering"}]}]
        self.assertEqual([j["id"] for j in greenhouse.select_jobs(jobs, "pure_storage", "https://example.test")], [1])

    def test_docusign_does_not_drop_engineer_due_to_inconsistent_category(self):
        data = {"req_id": "1", "title": "Software Engineer", "country_code": "IN", "full_location": "Bengaluru, India", "description": "Build systems",
                "qualifications": "Python required", "categories": [{"name": "Marketing & Communications"}], "posted_date": "2026-09-22T07:06:00+0000"}
        result = docusign.normalize(data)
        self.assertEqual(result["title"], "Software Engineer")
        self.assertIn("Python required", result["jobDescriptionText"])
        data["country_code"] = "US"
        data["full_location"] = "Boston"
        self.assertIsNone(docusign.normalize(data))

    def test_dates_with_compact_timezone_offsets_sort_correctly(self):
        self.assertEqual(timestamp("2026-11-03T10:00:00+0530"), timestamp("2026-11-03T04:30:00Z"))

    def test_arista_requires_india_and_engineering_title(self):
        self.assertTrue(arista.eligible({"name": "Software Engineer", "location": {"country": "in"}}))
        self.assertFalse(arista.eligible({"name": "Technical Support Engineer", "location": {"country": "in"}}))
        self.assertFalse(arista.eligible({"name": "Software Engineer", "location": {"country": "us"}}))


if __name__ == "__main__":
    unittest.main()
