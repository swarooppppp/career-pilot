from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_linkedin_flipkart_jobs", ROOT / "career portal scripts" / "fetch_linkedin_flipkart_jobs.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class LinkedInFlipkartFetchTests(unittest.TestCase):
    def test_extracts_unique_canonical_job_urls(self) -> None:
        search_html = '''<a href="https://in.linkedin.com/jobs/view/software-engineer-at-flipkart-123?trackingId=x">One</a>
        <a href="https://in.linkedin.com/jobs/view/software-engineer-at-flipkart-123?trackingId=y">Duplicate</a>
        <a href="https://in.linkedin.com/jobs/view/sde-at-flipkart-456">Two</a>'''
        self.assertEqual(module.extract_job_urls(search_html), [
            "https://in.linkedin.com/jobs/view/software-engineer-at-flipkart-123",
            "https://in.linkedin.com/jobs/view/sde-at-flipkart-456",
        ])

    def test_extracts_public_job_detail(self) -> None:
        page_html = '''<h1 class="topcard__title">Software Engineer</h1>
        <a class="topcard__org-name-link">Flipkart</a>
        <span class="topcard__flavor--bullet">Bengaluru, Karnataka, India</span>
        <span class="posted-time-ago__text">2 weeks ago</span>
        <div class="show-more-less-html__markup"><p>Build scalable systems.</p><ul><li>3+ years of Java.</li></ul></div>'''
        job = module.parse_job_page(page_html, "https://in.linkedin.com/jobs/view/software-engineer-at-flipkart-123")
        self.assertEqual(job["id"], "123")
        self.assertEqual(job["company"], "Flipkart")
        self.assertIn("3+ years of Java.", job["jobDescriptionText"])


if __name__ == "__main__":
    unittest.main()
