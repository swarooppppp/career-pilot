"""New-source scope boundaries and explicitly selected headless transport."""
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

DIRECTORY = Path(__file__).resolve().parents[1] / "local_career_portals"
sys.path.insert(0, str(DIRECTORY))
import fetch_additional_board_jobs as boards
import fetch_flipkart_portal_jobs as flipkart
import fetch_hashicorp_jobs as hashicorp
import fetch_ibm_jobs as ibm
import fetch_lever_india_jobs as lever
import fetch_workday_india_jobs as workday
import portal_http
import run


class CommerceEnterpriseAITests(unittest.TestCase):
    def test_browser_post_allows_ibm_redirect_but_rejects_workday_maintenance(self):
        page = Mock()
        page.url = "https://www.ibm.com/in-en"
        page.goto.return_value = Mock(status=200)
        page.evaluate.return_value = {"status": 200, "body": '{"hits": []}'}
        with patch.dict(os.environ, {"CAREER_PORTAL_TRANSPORT": "browser"}), patch.object(portal_http, "browser_page", return_value=page):
            self.assertEqual(portal_http.request_json("https://www-api.ibm.com/search/api/v2", {}, 10), {"hits": []})
            page.url = "https://community.workday.com/maintenance-page"
            page.goto.return_value = Mock(status=500)
            with self.assertRaisesRegex(RuntimeError, "unavailable host"):
                portal_http.request_json("https://walmart.wd5.myworkdayjobs.com/wday/cxs/walmart/WalmartExternal/jobs", {}, 10)

    def test_failure_classification_does_not_treat_timeout_variable_as_timeout_error(self):
        from sample_all import classification
        self.assertEqual(classification("data = request(url, args.timeout)\nRuntimeError: invalid response"), "fetch_failed")
        self.assertEqual(classification("TimeoutError: Timeout 30000ms exceeded"), "timeout")

    def test_headless_transport_setting_is_per_company_not_global(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(portal_http.browser_enabled())
            self.assertEqual(run.environment({"transport": "browser"})["CAREER_PORTAL_TRANSPORT"], "browser")
            self.assertNotIn("CAREER_PORTAL_TRANSPORT", os.environ)

    def test_browser_get_errors_are_not_empty_json_results(self):
        page = Mock()
        page.goto.return_value = Mock(ok=False, status=429)
        with patch.dict(os.environ, {"CAREER_PORTAL_TRANSPORT": "browser"}), patch.object(portal_http, "browser_page", return_value=page):
            with self.assertRaisesRegex(RuntimeError, "HTTP 429"):
                portal_http.read("https://example.test/jobs", 10)

    def test_large_json_body_can_be_read_from_browser_dom_if_protocol_buffer_evicted(self):
        page = Mock()
        response = Mock(ok=True, headers={"content-type": "application/json"})
        response.text.side_effect = RuntimeError("response evicted")
        page.goto.return_value = response
        page.locator.return_value.count.return_value = 1
        page.locator.return_value.inner_text.return_value = '{"jobs": []}'
        with patch.dict(os.environ, {"CAREER_PORTAL_TRANSPORT": "browser"}), patch.object(portal_http, "browser_page", return_value=page):
            self.assertEqual(json.loads(portal_http.read("https://example.test/jobs", 10)), {"jobs": []})

    def test_ibm_search_reuses_native_country_and_keyword_instead_of_searching_all_ibm(self):
        payload = ibm.search_payload("https://www.ibm.com/careers/search?q=hashicorp&field_keyword_05%5B0%5D=India", 0, 30)
        self.assertEqual(payload["query"]["bool"]["must"][0]["simple_query_string"]["query"], "hashicorp")
        self.assertIn({"terms": {"field_keyword_05": ["India"]}}, payload["post_filter"]["bool"]["must"])

    def test_hashicorp_requires_india_technical_role_and_brand_evidence(self):
        summary = {"title": "Software Engineer", "url": "https://careers.ibm.com/careers/JobDetail?jobId=123", "field_keyword_19": "Bangalore, IN"}
        detail = {"description": "<p>Build the HashiCorp platform with IBM.</p>", "hiringOrganization": {"name": "IBM"}, "datePosted": "2026-11-01"}
        job = hashicorp.normalize(summary, detail)
        self.assertEqual(job["employer_name"], "IBM")
        self.assertEqual(job["company"], "HashiCorp")
        self.assertEqual(job["posted_date"], "2026-11-01")
        self.assertIsNone(hashicorp.normalize(summary, {**detail, "description": "Generic IBM role"}))
        self.assertIsNone(hashicorp.normalize({**summary, "field_keyword_19": "London, GB"}, detail))
        self.assertIsNone(hashicorp.normalize({**summary, "title": "Sales Engineer"}, detail))

    def test_walmart_requires_global_tech_business_unit_evidence(self):
        self.assertIsNone(workday.brand_evidence({"jobDescription": "Maintain Walmart store refrigeration"}, "Walmart Global Tech"))
        self.assertIn("GlobalTech", workday.brand_evidence({"jobDescription": "Join Walmart GlobalTech and build software"}, "Walmart Global Tech"))

    def test_flipkart_uses_publication_not_update_and_preserves_canonical_id(self):
        item = {"JobId": "1", "JobIdObfuscated": "encoded%2Ftoken", "JobTitle": "SDE-2, FPG Engineering", "Department": "Technology",
                "Location": json.dumps([{"Address": "Bangalore, Karnataka, India"}]), "JobDescV2": "<h2>Role</h2><p>Build payment systems</p>",
                "PublishedDate": "2026-10-30T07:44:14.1467659Z", "UpdatedDate": "2026-11-02T04:03:24Z"}
        job = flipkart.normalize(item)
        self.assertEqual(job["posted_date"], "2026-10-30T07:44:14.146765Z")
        self.assertEqual(job["source_posted_date"], item["PublishedDate"])
        self.assertEqual(job["updated_date"], item["UpdatedDate"])
        self.assertTrue(job["application_url"].endswith("/job/publicjobs/encoded%2Ftoken"))
        self.assertIsNone(flipkart.normalize({**item, "Department": "Fulfilment Center Ops"}))
        self.assertIsNone(flipkart.normalize({**item, "Location": json.dumps([{"Address": "London, UK"}])}))

    def test_cred_and_meesho_keep_security_engineering_without_exact_engineering_team(self):
        for source in ["cred", "meesho"]:
            item = {"id": "1", "text": "Cloud Security Engineer", "categories": {"team": "cloud and data security", "location": "bengaluru"},
                    "description": "<p>Secure infrastructure</p>", "hostedUrl": f"https://jobs.lever.co/{source}/1"}
            self.assertIsNotNone(lever.normalize(item, source))
            self.assertIsNone(lever.normalize({**item, "categories": {"team": "Sales", "location": "bengaluru"}}, source))

    def test_quince_native_engineering_branches_keep_data_science_not_sourcing(self):
        jobs = [{"id": 1, "title": "Senior Data Scientist", "location": {"name": "Bengaluru"}, "departments": [{"id": 10, "name": "Supply Chain Engineering"}]},
                {"id": 2, "title": "Sourcing Manager", "location": {"name": "Bengaluru"}, "departments": [{"id": 11, "name": "Material Sourcing"}]}]
        self.assertEqual([j["id"] for j in boards.select_jobs(jobs, "quince", "https://example.test")], [1])


if __name__ == "__main__":
    unittest.main()
