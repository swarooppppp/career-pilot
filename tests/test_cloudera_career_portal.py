"""Company wiring and source-specific location/description boundaries."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "local_career_portals"))
import fetch_cloudera_jobs as cloudera
import fetch_workday_india_jobs as workday
import run


class ClouderaTests(unittest.TestCase):
    def test_registry_command_uses_browser_and_dedicated_script(self):
        company = next(c for c in json.loads((ROOT / "local_career_portals/companies.json").read_text())["companies"] if c["slug"] == "cloudera")
        command = run.command(company, 50, Path("snapshot.json"))
        self.assertTrue(command[1].endswith("fetch_cloudera_jobs.py"))
        self.assertEqual(run.environment(company)["CAREER_PORTAL_TRANSPORT"], "browser")

    def test_wrapper_keeps_empty_search_for_all_technical_titles(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(workday, "main") as main:
            cloudera.main([cloudera.CAREERS_URL, "--max-jobs", "50", "--output", "jobs.json"])
            self.assertEqual(main.call_args.args[0], [cloudera.CAREERS_URL, "--company", "Cloudera", "--search-text", "", "--max-jobs", "50", "--output", "jobs.json"])
            self.assertIsInstance(main.call_args.kwargs["requester"], cloudera.BrowserTransport)

    def test_secondary_india_location_retains_full_description_and_date(self):
        job = workday.normalize({"title": "Software Engineer", "externalPath": "/job/123"},
            {"jobReqId": "123", "location": "US-California", "additionalLocations": ["India-Bangalore"],
             "country": {"descriptor": "United States"}, "jobDescription": "<p>Complete role description.</p>",
             "startDate": "2026-11-17"}, "cloudera.wd5.myworkdayjobs.com", "External_Career", "Cloudera")
        self.assertEqual(job["jobDescriptionText"], "Complete role description.")
        self.assertEqual(job["posted_date"], "2026-11-17")

    def test_rate_limit_propagates_instead_of_writing_empty_snapshot(self):
        with patch.object(cloudera, "BrowserTransport") as transport, patch.object(workday, "write_snapshot") as write:
            transport.return_value.side_effect = RuntimeError("HTTP 429")
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                cloudera.main(["--output", "unused.json"])
            write.assert_not_called()


    def test_native_navigation_captures_page_response_without_synthetic_fetch(self):
        page = Mock()
        response = Mock(ok=True)
        response.json.return_value = {"total": 2, "jobPostings": []}
        context = page.expect_response.return_value
        context.__enter__ = Mock(return_value=Mock(value=response))
        context.__exit__ = Mock(return_value=False)
        page.goto.return_value = Mock(ok=True)
        with patch.object(cloudera.portal_http, "browser_page", return_value=page):
            result = cloudera.BrowserTransport()(cloudera.API_ROOT + "jobs",
                {"offset": 0, "searchText": "", "appliedFacets": {"locationCountry": ["india-id"]}}, 30)
        self.assertEqual(result["total"], 2)
        self.assertIn("en-US/External_Career?locationCountry=india-id", page.goto.call_args.args[0])
        page.evaluate.assert_not_called()
        predicate = page.expect_response.call_args.args[0]
        request = Mock(url=cloudera.API_ROOT + "jobs")
        request.request.method = "POST"
        request.request.post_data_json = {"offset": 0, "searchText": "", "appliedFacets": {"locationCountry": ["india-id"]}}
        self.assertTrue(predicate(request))
        request.request.post_data_json = {"offset": 0, "searchText": "", "appliedFacets": {}}
        self.assertFalse(predicate(request))

    def test_security_check_stops_immediately(self):
        with self.assertRaisesRegex(RuntimeError, "HTTP 429; Retry-After=120"):
            cloudera.BrowserTransport.check_navigation(Mock(ok=False, status=429, headers={"retry-after": "120"}))

    def test_transport_rejects_unrelated_hosts(self):
        with self.assertRaises(ValueError):
            cloudera.BrowserTransport()("https://example.org/jobs", {}, 30)

if __name__ == "__main__":
    unittest.main()
