"""Country eligibility and role/brand boundaries for the fifth batch."""
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_ashby_jobs as ashby
import fetch_additional_board_jobs as greenhouse
import fetch_canva_jobs as canva
import fetch_cyberark_jobs as cyberark


class DesignSecurityPortalTests(unittest.TestCase):
    def job(self, ident, location="India", title="Software Engineer", **kwargs):
        return {"id": ident, "title": title, "location": location, "isListed": True,
                "descriptionHtml": "<p>Build systems</p>", "jobUrl": "https://jobs.ashbyhq.com/company/" + str(ident),
                "publishedAt": "2026-11-01", **kwargs}

    def test_remote_and_description_mentions_do_not_establish_india_eligibility(self):
        job = self.job(1, "Remote", isRemote=True, descriptionHtml="Work with our India team")
        self.assertFalse(ashby.india_eligible(job))
        self.assertEqual(ashby.normalize([job], "Company"), [])

    def test_secondary_location_or_explicit_country_code_can_include_india(self):
        job = self.job(1, "United States", secondaryLocations=[{"location": "Remote", "address": {"postalAddress": {"addressCountry": "IN"}}}])
        self.assertTrue(ashby.india_eligible(job))
        result = ashby.normalize([job], "Company")[0]
        self.assertEqual(result["country"], "India")
        self.assertIn("may also have other", result["location_scope"])

    def test_ashby_excludes_unlisted_and_non_engineering_and_sorts_dates(self):
        jobs = [self.job(1), self.job(2, publishedAt="2026-11-03"), self.job(3, isListed=False),
                self.job(4, title="Recruiter, Engineering"), self.job(5, title="Deployment Strategist Lead")]
        self.assertEqual([j["id"] for j in ashby.normalize(jobs, "Company")], [2, 1])
        with self.assertRaises(RuntimeError):
            ashby.normalize([self.job(6, descriptionHtml="")], "Company")

    def test_greenhouse_technical_roles_do_not_depend_on_one_department_name(self):
        jobs = [{"id": 1, "title": "Staff Software Engineer", "location": {"name": "Bengaluru"}, "departments": [{"name": "Platform"}]},
                {"id": 2, "title": "Software Engineer", "location": {"name": "India"}, "departments": [{"name": "Sales Engineering"}]},
                {"id": 3, "title": "Product Support Engineer", "location": {"name": "India"}, "departments": [{"name": "Support"}]},
                {"id": 4, "title": "Software Engineer", "location": {"name": "London"}, "departments": [{"name": "Platform"}]}]
        for source in ("adyen", "samsara", "wiz", "okta"):
            self.assertEqual([j["id"] for j in greenhouse.select_jobs(jobs, source, "https://example.test")], [1])

    def test_canva_enforces_country_and_role(self):
        self.assertTrue(canva.selected({"name": "Software Engineer", "location": {"country": "in"}}))
        self.assertFalse(canva.selected({"name": "Software Engineer", "location": {"country": "au"}}))
        self.assertFalse(canva.selected({"name": "Product Localisation Lead", "location": {"country": "in"}}))

    def test_cyberark_scope_never_accepts_unbranded_palo_description(self):
        self.assertIsNone(cyberark.brand_evidence({"description": "Palo Alto Networks engineering role"}))
        self.assertIn("Idira", cyberark.brand_evidence({"description": "Build the Idira platform"}))
        self.assertIn("CyberArk", cyberark.brand_evidence({"description": "CyberArk identity platform team"}))


if __name__ == "__main__":
    unittest.main()
