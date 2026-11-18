"""Current source identities, publication semantics, native data and scope guards."""
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local_career_portals"))
import fetch_security_portals as portals


class TravelCommerceTests(unittest.TestCase):
    def native_browser(self, data):
        browser = Mock()
        browser.timeout = 30
        browser.page = MagicMock()
        response = Mock(ok=True)
        response.json.return_value = data
        browser.page.expect_response.return_value.__enter__.return_value.value = response
        return browser

    def test_verified_successor_sources(self):
        self.assertEqual(portals.SOURCES["spotnana"][1:], ("gem", "spotnana"))
        self.assertEqual(portals.SOURCES["twilio"][1], "twilio")
        self.assertEqual(portals.SOURCES["wisdom_ai"][2], "Wisdom-AI")
        self.assertEqual(portals.SOURCES["arcana"][2], "arcanaanalytics")
        self.assertEqual(portals.SOURCES["wayfair"][1], "wayfair")

    def test_gem_publication_is_separate_from_creation(self):
        browser = Mock()
        browser.json.return_value = [{"id": "gem-1", "title": "Software Engineer", "location": {"name": "Bengaluru"},
            "departments": [{"name": "Engineering"}], "absolute_url": "https://jobs.gem.com/spotnana/gem-1",
            "content": "<p>Full responsibilities and qualifications.</p>",
            "first_published_at": "2026-11-17T10:00:00Z", "created_at": "2025-01-01"}]
        jobs, _ = portals.gem_jobs(browser, "Spotnana", "spotnana")
        self.assertEqual(jobs[0]["posted_date"], "2026-11-17T10:00:00Z")
        self.assertIn("qualifications", jobs[0]["jobDescriptionText"])

    def test_lightweight_coupang_feed_hydrates_and_rechecks_identity(self):
        browser = Mock()
        summary = {"id": 1, "title": "Software Engineer", "location": {"name": "Bangalore"}}
        browser.json.side_effect = [{"jobs": [summary]}, {**summary, "id": 2}]
        with self.assertRaisesRegex(RuntimeError, "identity mismatch"):
            portals.greenhouse_selective_jobs(browser, "Coupang", "coupang")
        self.assertIn("content=false", browser.json.call_args_list[0].args[0])

    def test_ambiguous_location_candidate_is_hydrated(self):
        browser = Mock()
        summary = {"id": 1, "title": "Software Engineer", "location": {"name": "Multiple locations"}}
        detail = {**summary, "offices": [{"name": "Bangalore"}], "content": "Full description",
                  "departments": [{"name": "Engineering"}], "absolute_url": "https://example.org/job/1"}
        browser.json.side_effect = [{"jobs": [summary]}, detail]
        jobs, _ = portals.greenhouse_selective_jobs(browser, "Coupang", "coupang")
        self.assertEqual(len(jobs), 1)

    def test_wayfair_active_public_engineering_only_and_creation_not_publication(self):
        item = {"id": 1, "title": "Software Engineer", "teamId": 1, "isActive": True,
                "location": {"name": "Bangalore, IND", "country": "India"}, "category": {"name": "Engineering"},
                "description": "<p>Full description.</p>", "applyLink": "https://wayfair.avature.net/job/1",
                "createdDate": "2026-10-01", "lastUpdatedDate": "2026-11-01"}
        data = {"jobListData": [item, {**item, "id": 2, "isHidden": True}, {**item, "id": 3, "isReferralOnly": True}],
                "validTeams": {"filters": [{"teamId": 1, "team": "Engineering & Technology"}]}}
        jobs, _ = portals.wayfair_jobs(self.native_browser(data), "Wayfair", "https://www.wayfair.com/careers/jobs")
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(jobs[0]["posted_date"])
        self.assertEqual(jobs[0]["source_created_date"], "2026-10-01")

    def test_wayfair_missing_native_engineering_mapping_fails(self):
        with self.assertRaisesRegex(RuntimeError, "mapping missing"):
            portals.wayfair_jobs(self.native_browser({"jobListData": []}), "Wayfair", "https://www.wayfair.com/careers/jobs")

    def test_twilio_explicit_post_date_not_index_creation(self):
        item = {"id": 1, "name": "Software Engineer", "locations": ["Remote - India"], "department": "Engineering", "postedTs": 0}
        detail = {**item, "jobDescription": "<p>Full description.</p>", "efcustomTextPostDate": ["2026-11-17"], "creationTs": 12345}
        browser = Mock()
        browser.json.side_effect = [{"status": 200, "data": {"positions": [item], "count": 1}}, {"status": 200, "data": detail}]
        jobs, _ = portals.twilio_jobs(browser, "Twilio", "https://jobs.twilio.com")
        self.assertEqual(jobs[0]["posted_date"], "2026-11-17")
        self.assertEqual(jobs[0]["source_created_timestamp"], 12345)

    def test_twilio_incomplete_pagination_is_failure(self):
        browser = Mock()
        browser.json.return_value = {"status": 200, "data": {"positions": [], "count": 1}}
        with self.assertRaisesRegex(RuntimeError, "before reported count"):
            portals.twilio_jobs(browser, "Twilio", "https://jobs.twilio.com")

    def test_zepto_native_description_decodes_and_posted_on_is_kept(self):
        data = {"status": "success", "job_counts": 1, "data": [{"id": "abc", "title": "Software Engineer",
            "department_name_only": "Engineering", "country": "India", "officelocations_area": ["Bengaluru, India"],
            "jd": "&lt;p&gt;Full description.&lt;/p&gt;", "posted_on": 1700000000, "created_on": "2020-01-01"}]}
        jobs, _ = portals.darwinbox_jobs(self.native_browser(data), "Zepto", portals.SOURCES["zepto"][2])
        self.assertEqual(jobs[0]["jobDescriptionHtml"], "<p>Full description.</p>")
        self.assertIn("/jobDetails/abc?from=all", jobs[0]["application_url"])
        self.assertTrue(jobs[0]["posted_date"].startswith("2023-11-14"))

    def test_zepto_operations_role_is_not_engineering(self):
        data = {"status": "success", "job_counts": 1, "data": [{"id": "abc", "title": "Manager I - Delivery Hub Manager", "country": "India"}]}
        jobs, metadata = portals.darwinbox_jobs(self.native_browser(data), "Zepto", portals.SOURCES["zepto"][2])
        self.assertEqual(jobs, [])
        self.assertTrue(metadata["complete"])


if __name__ == "__main__":
    unittest.main()
