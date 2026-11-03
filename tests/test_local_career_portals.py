"""Verify filtering and date semantics for the local collection."""
import importlib.util
from pathlib import Path
import sys
import unittest

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
from common import newest_first, timestamp
import fetch_ibm_jobs as ibm
import fetch_rubrik_jobs as rubrik
import fetch_filtered_board_jobs as boards
from filters import apply_policy, in_india


class LocalPortalTests(unittest.TestCase):
    def test_uber_local_command_uses_headed_minimized_browser(self):
        import json
        import run
        companies = json.loads((DIRECTORY / "companies.json").read_text())["companies"]
        company = next(c for c in companies if c["slug"] == "uber")
        command = run.command(company, 50, Path("/tmp/uber-command-test.json"))
        self.assertIn("--headed", command)
        self.assertIn("--minimized", command)

    def test_public_portal_display_dates_sort_chronologically(self):
        self.assertGreater(timestamp("October 30, 2026"), timestamp("September 30, 2026"))
        self.assertGreater(timestamp("2026-10-30 07:01 AM"), timestamp("2026-10-29 11:59 PM"))
    def test_airbnb_structured_country_and_city_are_preserved(self):
        spec = importlib.util.spec_from_file_location("local_airbnb_adapter", DIRECTORY.parent / "career portal scripts/fetch_server_rendered_jobs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        value = {"address": {"addressLocality": "Bengaluru", "addressCountry": {"name": "India"}}}
        self.assertEqual(module.locations_text(value), "Bengaluru, India")
        self.assertEqual(module.locations_text({"address": {"addressCountry": "IN"}}), "India")

    def test_glean_exact_department_excludes_sales_engineering(self):
        from unittest.mock import patch
        spec = importlib.util.spec_from_file_location("local_greenhouse_adapter", DIRECTORY.parent / "career portal scripts/fetch_greenhouse_jobs.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        jobs = [{"id": 1, "title": "Engineer", "location": {"name": "Bangalore, India"}, "departments": [{"name": "Sales Engineering"}]},
                {"id": 2, "title": "Engineer", "location": {"name": "Bangalore, India"}, "departments": [{"name": "Engineering"}]}]
        with patch.object(module, "get", return_value={"jobs": jobs}):
            result = module.fetch("gleanwork", "Glean", "", "India", "Engineering", 1, 30, set(), exact_department=True)
        self.assertEqual([job["id"] for job in result], ["2"])

    def test_description_mentions_do_not_satisfy_country_or_engineering(self):
        policy = {"country": "India", "engineering": "title"}
        jobs = [{"title": "Software Engineer", "location": "London", "jobDescriptionText": "Work with India"},
                {"title": "Sales Engineer", "location": "Bengaluru"},
                {"title": "Recruiter", "location": "India", "jobDescriptionText": "Hire engineers"},
                {"title": "Backend Developer", "location": "Pune"}]
        self.assertEqual([j["title"] for j in apply_policy(jobs, policy)], ["Backend Developer"])
        self.assertFalse(in_india({"location": "Indianapolis"}))

    def test_cloudflare_uses_site_category_and_location_metadata(self):
        job = {"location": {"name": "Hybrid"}, "metadata": [
            {"name": "Career Site Department", "value": ["Engineering"]},
            {"name": "Job Posting Location", "value": ["Bengaluru, India"]}]}
        self.assertTrue(boards.cloudflare_matches(job, "Bengaluru, India"))
        job["metadata"][0]["value"] = ["Solution Engineering"]
        self.assertFalse(boards.cloudflare_matches(job, "Bengaluru, India"))

    def test_abnormal_category_is_read_from_portal_not_department_names(self):
        import json
        data = '1:["$","component",null,{"jobs":[{"id":1,"category":"Engineering","departmentName":"Platform & Infrastructure"}]}]'
        document = '<script>self.__next_f.push(' + json.dumps([1, data]) + ')</script>'
        self.assertEqual(boards.abnormal_categories(document)["1"]["category"], "Engineering")
        with self.assertRaises(RuntimeError):
            boards.abnormal_categories("<html>Unavailable</html>")

    def test_every_runnable_company_has_filter_policy(self):
        import json
        companies = json.loads((DIRECTORY / "companies.json").read_text())["companies"]
        for company in companies:
            if company["status"] in {"reuse", "implemented"}:
                self.assertEqual(company["filter_policy"]["country"], "India")
                self.assertIn(company["filter_policy"]["engineering"], {"native", "title"})

    def test_dates_compare_timezones_and_keep_undated_stable(self):
        jobs = [{"id": "unknown1"}, {"id": "earlier", "posted_date": "2026-10-30T15:00:00+05:30"},
                {"id": "later", "posted_date": "2026-10-30T10:00:00Z"}, {"id": "unknown2", "posted_date": "invalid"}]
        self.assertEqual([j["id"] for j in newest_first(jobs)], ["later", "earlier", "unknown1", "unknown2"])

    def test_rubrik_excludes_sales_engineering_and_uses_publication_date(self):
        def job(ident, department, published, updated):
            return {"id": ident, "title": "Engineer", "departments": [{"name": department}],
                    "location": {"name": "Bangalore, India"}, "absolute_url": "https://www.rubrik.com/job",
                    "content": "<p>Full description</p>", "first_published": published, "updated_at": updated}
        jobs = [job(1, "Engineering", "2026-10-01", "2026-10-31"),
                job(2, "Engineering", "2026-10-30", "2026-10-30"),
                job(3, "Sales Engineering", "2026-10-31", "2026-10-31")]
        self.assertEqual([j["id"] for j in rubrik.normalize(jobs, "India")], ["2", "1"])
        self.assertEqual(rubrik.normalize(jobs, "London"), [])
        jobs[0]["location"]["name"] = "Bengaluru"
        jobs[0]["offices"] = [{"name": "Bangalore, India Office"}]
        self.assertEqual(rubrik.normalize(jobs[:1], "India")[0]["id"], "1")

    def test_ibm_preserves_user_filters_sort_and_pagination(self):
        payload = ibm.search_payload(ibm.DEFAULT_URL, 30, 30)
        filters = payload["post_filter"]["bool"]["must"]
        self.assertIn({"terms": {"field_keyword_05": ["India"]}}, filters)
        self.assertIn({"terms": {"field_keyword_08": ["Software Engineering"]}}, filters)
        self.assertIn({"terms": {"field_keyword_18": ["Professional"]}}, filters)
        self.assertEqual(payload["sort"][0], {"dcdate": "desc"})
        self.assertEqual(payload["from"], 30)

    def test_ibm_requires_full_jobposting_instead_of_summary(self):
        self.assertIsNone(ibm.job_schema('<p>A listing summary...</p>'))
        document = '<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","description":"Full requirements"}]}</script>'
        self.assertEqual(ibm.job_schema(document)["description"], "Full requirements")

    def test_linkedin_keeps_company_and_day_filter_with_recent_sort(self):
        import json
        from urllib.parse import parse_qs, urlparse
        companies = json.loads((DIRECTORY / "companies.json").read_text())["companies"]
        company = next(c for c in companies if c["slug"] == "linkedin")
        query = parse_qs(urlparse(company["url"]).query)
        self.assertEqual((query["f_C"], query["f_TPR"], query["sortBy"]), (["1337"], ["r86400"], ["DD"]))


if __name__ == "__main__":
    unittest.main()
