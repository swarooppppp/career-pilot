from __future__ import annotations
import importlib.util, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_capital_one_jobs", ROOT / "career portal scripts" / "fetch_capital_one_jobs.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = module; SPEC.loader.exec_module(module)
class CapitalOneFetchTests(unittest.TestCase):
    def test_parses_listing_and_job_posting_description(self):
        listing = '<nav aria-label="pagination">Page 1 of 2</nav><a data-job-id="1" href="/job/1"><h2>Engineer</h2><span class="job-location">Bengaluru</span><span class="job-date-posted">Today</span></a>'
        jobs, pages = module.parse_page(listing, "https://example.test")
        self.assertEqual((jobs[0]["id"], pages), ("1", 2))
        page = '<script type="application/ld+json">{"@type":"JobPosting","description":"<p>Build systems.</p>"}</script>'
        self.assertEqual(module.job_description(page), "<p>Build systems.</p>")
if __name__ == "__main__": unittest.main()
