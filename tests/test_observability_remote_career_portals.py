"""India/remote eligibility and tenant facet semantics for the seventh batch."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_additional_board_jobs as boards
import fetch_automattic_jobs as automattic
import fetch_dynatrace_jobs as dynatrace
import fetch_workday_india_jobs as workday


class ObservabilityRemoteTests(unittest.TestCase):
    def test_workday_continues_after_later_pages_report_zero_total(self):
        facet = {"facetParameter": "country", "values": [{"id": "in", "descriptor": "India"}]}
        def response(url, payload, timeout):
            if not payload:
                return {"jobPostingInfo": {"title": "MTS 2, AI Platform", "country": "India", "location": "Bengaluru", "jobDescription": "Build systems", "jobReqId": url.rsplit("/", 1)[-1]}}
            if "appliedFacets" not in payload:
                return {"facets": [facet], "jobPostings": [], "total": 3}
            index = payload["offset"] // 20
            return {"total": 3 if index == 0 else 0, "jobPostings": [
                {"title": "MTS 2, AI Platform", "externalPath": "/job/" + str(index)}]}
        with TemporaryDirectory() as directory, patch.object(workday.transport, "request_json", side_effect=response), \
                patch.object(workday.time, "sleep"), patch.object(workday, "write_snapshot") as output, \
                patch.object(sys, "argv", ["fetch", "https://ebay.wd5.myworkdayjobs.com/apply", "--company", "eBay", "--output", str(Path(directory) / "jobs.json")]):
            workday.main()
        self.assertEqual(len(output.call_args.args[1]), 3)
        self.assertEqual(output.call_args.kwargs["total_filtered_results"], 3)
        self.assertTrue(output.call_args.kwargs["complete"])

    def test_red_hat_opaque_facet_keys_are_discovered_by_labels(self):
        facets = [{"facetParameter": "a", "descriptor": "Country", "values": [
            {"descriptor": "India", "id": "india"}, {"descriptor": "United States", "id": "us"}]},
                  {"facetParameter": "d", "descriptor": "Job Function", "values": [
                      {"descriptor": "Engineering", "id": "eng"}, {"descriptor": "Sales", "id": "sales"}]}]
        self.assertEqual(workday.native_facets(facets), {"a": ["india"], "d": ["eng"]})

    def test_paypal_uses_all_india_locations_and_actual_technical_families(self):
        facets = [{"facetParameter": "locations", "values": [
            {"id": "blr", "descriptor": "Bangalore, Karnataka, India"},
            {"id": "tn", "descriptor": "Tamil Nadu, India (Virtual)"},
            {"id": "us", "descriptor": "Austin, Texas, United States"}]},
                  {"facetParameter": "jobFamilies", "values": [
                      {"id": "software", "descriptor": "Software Engineering"},
                      {"id": "sales", "descriptor": "Sales Engineering"}]}]
        self.assertEqual(workday.native_facets(facets), {"locations": ["blr", "tn"], "jobFamilies": ["software"]})

    def test_new_boards_require_explicit_india_and_exclude_support(self):
        jobs = [{"id": 1, "title": "Software Engineer", "location": {"name": "Remote, India"}},
                {"id": 2, "title": "Software Engineer", "location": {"name": "Remote, United States"}},
                {"id": 3, "title": "Software Engineer", "location": {"name": "Remote"}},
                {"id": 4, "title": "Technical Support Engineer", "location": {"name": "India"}},
                {"id": 5, "title": "Software Engineer", "location": {"name": "Hybrid"}, "offices": [{"name": "Bangalore"}]},
                {"id": 6, "title": "Engineer", "location": {"name": "India"}, "departments": [{"name": "Sales Engineering"}]},
                {"id": 7, "title": "Consulting Architect", "location": {"name": "India"}, "departments": [{"name": "Consulting - Global - COE"}]},
                {"id": 8, "title": "Senior Partner Solutions Architect", "location": {"name": "India"}, "departments": [{"name": "SA - APJ - India"}]}]
        for source in ("commvault", "veeam", "gitlab", "grafana_labs", "elastic"):
            self.assertEqual([j["id"] for j in boards.select_jobs(jobs, source, "https://example.test")], [1, 5])

    def test_automattic_requires_role_specific_worldwide_hiring_evidence(self):
        raw = {"id": 1, "title": "Software Engineer", "metadata": {"Category": ["Engineering"]},
               "content": "<p>We are looking for experienced engineers worldwide.</p>",
               "href": "https://automattic.com/work-with-us/job/engineer/"}
        result = automattic.normalize(raw)
        self.assertIn("worldwide", result["location_evidence"])
        self.assertIsNone(result["posted_date"])
        for content in ["Our global users live worldwide.", "We are a fully remote company.", "Global salaries, regardless of location."]:
            self.assertIsNone(automattic.normalize({**raw, "content": content}))
        self.assertIsNone(automattic.normalize({**raw, "metadata": {"Category": ["Marketing"]}}))
        self.assertIsNone(automattic.normalize({**raw, "location": "United States"}))

    def test_automattic_missing_job_data_fails_instead_of_claiming_zero_jobs(self):
        with self.assertRaises(RuntimeError):
            automattic.listings("<html>Challenge</html>")
        self.assertEqual(automattic.listings('const ghJobsData = [{"id": 1}];')[0]["id"], 1)

    def test_dynatrace_uses_publication_not_search_index_date(self):
        item = {"uri": "https://www.dynatrace.com/careers/jobs/1/", "raw": {
            "country": ["India"], "team": ["Engineering"], "office_locations": ["Bengaluru"], "date": 1793710333000}}
        detail = {"@type": "JobPosting", "title": "Software Engineer", "identifier": {"value": "1"},
                  "description": "Build systems", "datePosted": "2026-10-02T10:00:00Z"}
        document = '<script type="application/ld+json">' + json.dumps({"@graph": [detail]}) + '</script>'
        result = dynatrace.normalize(item, dynatrace.posting(document))
        self.assertEqual(result["posted_date"], detail["datePosted"])
        detail.pop("datePosted")
        self.assertIsNone(dynatrace.normalize(item, detail)["posted_date"])
        item["raw"]["country"] = ["Austria"]
        with self.assertRaises(RuntimeError):
            dynatrace.normalize(item, detail)


if __name__ == "__main__":
    unittest.main()
