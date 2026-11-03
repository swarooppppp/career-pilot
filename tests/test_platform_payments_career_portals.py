"""Engineering/India filters and complete Lever data for batch nine."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_additional_board_jobs as greenhouse
import fetch_ashby_jobs as ashby
import fetch_lever_india_jobs as lever


class PlatformPaymentsPortalTests(unittest.TestCase):
    def test_kong_uses_engineering_team_under_generic_cost_center(self):
        job = {"id": "1", "title": "Software Engineer", "department": "All Cost Center", "team": "ENG",
               "location": "Bangalore, India", "isListed": True, "descriptionHtml": "<p>Build gateways</p>",
               "jobUrl": "https://jobs.ashbyhq.com/kong/1", "publishedAt": "2026-11-01"}
        self.assertEqual(len(ashby.normalize([job], "Kong", team="ENG")), 1)
        self.assertEqual(ashby.normalize([{**job, "team": "GTM"}], "Kong", team="ENG"), [])
        self.assertEqual(ashby.normalize([{**job, "location": "Remote, United States"}], "Kong", team="ENG"), [])

    def posting(self, **overrides):
        return {"id": "role-1", "text": "Cloud Network Engineer II",
                "categories": {"team": "Engineering", "location": "Hyderabad"},
                "hostedUrl": "https://jobs.lever.co/zeta/role-1", "description": "<p>Build banking systems.</p>",
                "lists": [{"text": "What you'll do", "content": "<ul><li>Design networks</li></ul>"}],
                "additional": "<p>Benefits and inclusion.</p>", "createdAt": 1790812800000, **overrides}

    def test_zeta_requires_native_team_india_and_engineering_title(self):
        self.assertIsNotNone(lever.normalize(self.posting()))
        self.assertIsNone(lever.normalize(self.posting(categories={"team": "Engineering", "location": "Basking Ridge, New Jersey"})))
        self.assertIsNone(lever.normalize(self.posting(categories={"team": "Solution Engineering", "location": "Bangalore"})))
        self.assertIsNone(lever.normalize(self.posting(text="Technical Support Engineer II")))
        self.assertIsNone(lever.normalize(self.posting(text="Talent Community, Engineering")))
        self.assertIsNone(lever.normalize(self.posting(categories={"team": "Engineering", "location": "Remote"}, description="Work with India teams")))

    def test_zeta_secondary_locations_are_preserved(self):
        result = lever.normalize(self.posting(categories={"team": "Engineering", "location": "Dubai", "allLocations": ["Dubai", "Bangalore"]}))
        self.assertEqual(result["locations"], ["Dubai", "Bangalore"])
        self.assertEqual(result["country"], "India")

    def test_lever_keeps_full_sections_without_inventing_publication_dates(self):
        result = lever.normalize(self.posting())
        for text in ["Build banking systems", "What you'll do", "Design networks", "Benefits and inclusion"]:
            self.assertIn(text, result["jobDescriptionText"])
        self.assertIsNone(result["posted_date"])
        self.assertIsNotNone(result["source_created_date"])
        self.assertEqual(lever.normalize(self.posting(datePosted="2026-11-01"))["posted_date"], "2026-11-01")
        with self.assertRaises(RuntimeError):
            lever.normalize(self.posting(hostedUrl="https://jobs.lever.co/zetaglobal/role-1"))

    def test_lever_jsonld_dates_handle_graphs_and_encoded_quotes(self):
        payload = {"@graph": [{"@type": "WebPage", "datePublished": "2026-11-03"},
                               {"@type": "JobPosting", "description": '<p>Build &quot;AI&quot;</p>', "datePosted": "2026-10-01"}]}
        document = '<script type="application/ld+json">' + json.dumps(payload) + '</script>'
        self.assertEqual(lever.posting_date(document), "2026-10-01")
        self.assertIsNone(lever.posting_date('<script type="application/ld+json">{"@type":"WebPage","datePublished":"2026-11-03"}</script>'))

    def test_lever_paginated_listing_and_duplicate_page_detection(self):
        first = [{"id": str(i)} for i in range(100)]
        with patch.object(lever.transport, "get", side_effect=[first, [{"id": "100"}]] ) as request:
            self.assertEqual(len(lever.collect_postings(10)), 101)
            self.assertIn("skip=100", request.call_args.args[0])
        with patch.object(lever.transport, "get", side_effect=[first, first]):
            with self.assertRaises(RuntimeError):
                lever.collect_postings(10)

    def test_new_native_boards_exclude_foreign_roles_and_other_departments(self):
        jobs = [{"id": 1, "title": "Engineer", "location": {"name": "Hybrid, Bangalore"}, "departments": [{"id": 10, "name": "Engineering"}]},
                {"id": 2, "title": "Engineer", "location": {"name": "India"}, "departments": [{"id": 11, "name": "Operations"}]},
                {"id": 3, "title": "Engineer", "location": {"name": "Toronto"}, "departments": [{"id": 10, "name": "Engineering"}]}]
        for source in ["bloomreach", "apollo", "bitgo"]:
            self.assertEqual([j["id"] for j in greenhouse.select_jobs(jobs, source, "https://example.test")], [1])

    def test_flexport_and_miro_exclude_customer_consulting_and_talent_pools(self):
        jobs = [{"id": 1, "title": "Software Engineer", "location": {"name": "Bengaluru"}, "departments": [{"name": "Platform"}]},
                {"id": 2, "title": "Solutions Architect", "location": {"name": "India"}, "departments": [{"name": "Professional Services"}]},
                {"id": 3, "title": "Engineering - Talent Community", "location": {"name": "India"}, "departments": []},
                {"id": 4, "title": "Software Engineer", "location": {"name": "Remote, United States"}, "departments": []}]
        for source in ["miro", "flexport"]:
            self.assertEqual([j["id"] for j in greenhouse.select_jobs(jobs, source, "https://example.test")], [1])

    def test_new_ashby_boards_retain_secondary_india_but_not_support_roles(self):
        job = {"id": "1", "title": "Software Engineer", "isListed": True, "department": "Engineering", "location": "Remote",
               "secondaryLocations": [{"location": "India"}], "descriptionHtml": "<p>Build systems</p>",
               "jobUrl": "https://jobs.ashbyhq.com/company/1", "publishedAt": "2026-11-01"}
        self.assertEqual(ashby.normalize([job], "Company", department="Engineering")[0]["posted_date"], "2026-11-01")
        self.assertEqual(ashby.normalize([{**job, "department": "Support Services"}], "Company", department="Engineering"), [])
        self.assertEqual(ashby.normalize([{**job, "secondaryLocations": []}], "Company", department="Engineering"), [])


if __name__ == "__main__":
    unittest.main()
