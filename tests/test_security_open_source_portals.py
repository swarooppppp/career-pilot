"""India/remote scope, source completeness and browser fallback regressions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "local_career_portals"))
import fetch_security_portals as portals
import fetch_oracle_india_jobs as oracle
from common import write_snapshot


class SecurityPortalTests(unittest.TestCase):
    def test_snapshot_is_utf8_and_preserves_unicode_descriptions(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jobs.json"
            write_snapshot(output, [{"jobDescriptionText": "Pune\u202fIndia: \u4f60\u597d"}])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["jobs"][0]["jobDescriptionText"], "Pune\u202fIndia: \u4f60\u597d")

    def gh(self, location, department="Engineering", title="Software Engineer"):
        return {"id": 1, "title": title, "location": {"name": location},
                "departments": [{"name": department}], "absolute_url": "https://example.org/job/1",
                "content": "<p>Complete description.</p>", "first_published": "2026-11-17T12:00:00Z"}

    def board(self, item, company="Canonical"):
        browser = Mock()
        browser.json.return_value = {"jobs": [item]}
        return portals.greenhouse_jobs(browser, company, "test")[0]

    def test_worldwide_home_based_retains_source_evidence(self):
        jobs = self.board(self.gh("Home based - Worldwide"))
        self.assertEqual(jobs[0]["country"], "India")
        self.assertEqual(jobs[0]["location_evidence"], "Home based - Worldwide")
        self.assertEqual(jobs[0]["location"], "Home based - Worldwide")

    def test_generic_remote_apac_and_emea_are_not_india(self):
        for location in ["Remote", "Home Based - APAC", "Home based - EMEA"]:
            self.assertEqual(self.board(self.gh(location)), [])

    def test_worldwide_exception_is_only_for_verified_canonical_location(self):
        self.assertEqual(self.board(self.gh("Home based - Worldwide"), "Tenable"), [])

    def test_sales_support_and_missing_description(self):
        self.assertEqual(self.board(self.gh("Pune, India", "Support Engineering")), [])
        self.assertEqual(self.board(self.gh("Pune, India", title="Sales Engineer")), [])
        item = self.gh("Pune, India")
        item["content"] = ""
        with self.assertRaises(RuntimeError):
            self.board(item)

    def test_description_mentions_do_not_supply_location(self):
        item = self.gh("US-Remote")
        item["content"] = "<p>Collaborate with India teams.</p>"
        self.assertEqual(self.board(item), [])

    def test_ashby_apac_not_inferred_from_description(self):
        browser = Mock()
        browser.json.return_value = {"jobs": [{"id": "x", "title": "Software Engineer", "location": "APAC",
            "isListed": True, "department": "Engineering", "descriptionHtml": "India collaboration",
            "jobUrl": "https://example.org/job/x"}]}
        self.assertEqual(portals.ashby_jobs(browser, "Zapier", "zapier")[0], [])

    def test_oracle_requires_requested_rd_facet_to_be_applied(self):
        response = {"items": [{"TotalJobsCount": 0, "requisitionList": [], "SelectedTitlesFacet": None}]}
        with patch.object(oracle, "read", return_value=json.dumps(response)):
            with self.assertRaisesRegex(RuntimeError, "did not confirm"):
                oracle.collect("https://example.org", "Fortinet", title_facet="RD")

    def test_smartrecruiters_truncated_pagination_fails(self):
        browser = Mock()
        browser.json.return_value = {"content": [], "totalFound": 1}
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            portals.smartrecruiters_jobs(browser, "Mirantis", "Mirantis")

    def test_headed_fallback_has_separate_browser_and_retains_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jobs.json"
            args = ["script", "https://example.org", "--source", "sophos", "--output", str(output)]
            with patch.object(sys, "argv", args), patch("playwright.sync_api.sync_playwright"), \
                 patch.object(portals, "Browser") as browser, \
                 patch.object(portals, "collect", side_effect=[RuntimeError("headless network failure"), ([], {"complete": True})]):
                self.assertEqual(portals.main(), 0)
                self.assertEqual([c.args[1] for c in browser.call_args_list], [False, True])
            snapshot = json.loads(output.read_text())
            self.assertEqual(snapshot["browser_mode"], "headed")
            self.assertEqual(len(snapshot["previous_attempt_errors"]), 1)

    def test_both_failures_preserve_existing_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jobs.json"
            output.write_text("existing snapshot")
            with patch.object(sys, "argv", ["script", "https://example.org", "--source", "sophos", "--output", str(output)]), \
                 patch("playwright.sync_api.sync_playwright"), patch.object(portals, "Browser"), \
                 patch.object(portals, "collect", side_effect=RuntimeError("HTTP 429; Retry-After=unspecified")):
                self.assertEqual(portals.main(), 1)
            self.assertEqual(output.read_text(), "existing snapshot")

    def test_retry_after_does_not_trigger_immediate_headed_retry(self):
        with patch.object(sys, "argv", ["script", "https://example.org", "--source", "sophos", "--output", "unused.json"]), \
             patch("playwright.sync_api.sync_playwright"), patch.object(portals, "Browser") as browser, \
             patch.object(portals, "collect", side_effect=RuntimeError("HTTP 429; Retry-After=120")):
            self.assertEqual(portals.main(), 1)
            self.assertEqual(browser.call_count, 1)


if __name__ == "__main__":
    unittest.main()
