from __future__ import annotations
import importlib.util, json, sys, unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs
ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_rippling_jobs", ROOT / "career portal scripts" / "fetch_rippling_jobs.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = module; SPEC.loader.exec_module(module)

class RipplingFetchTests(unittest.TestCase):
    def test_extracts_job_posting_schema_and_text(self):
        page = '<script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting","description":"<p>Build services.</p>"}</script>'
        description = module.job_posting_description(page)
        self.assertEqual(module.html_to_text(description), "Build services.")
    def test_search_url_becomes_algolia_facet_filters(self):
        response = b'{"results":[{"hits":[],"nbPages":1}]}'
        with patch.object(module, "fetch_bytes", return_value=response) as fetch_bytes:
            module.search_page("https://www.rippling.com/en-GB/careers/open-roles?search=Software+Engineer&department=Engineering&location=Bangalore%2C+India", 0, 30)
        request = fetch_bytes.call_args.args[0]
        payload = json.loads(request.data)
        parameters = parse_qs(payload["requests"][0]["params"])
        self.assertEqual(parameters["query"], ["Software Engineer"])
        self.assertEqual(json.loads(parameters["facetFilters"][0]), [["departmentName:Engineering"], ["locationNames:Bangalore, India"]])

    def test_extracts_description_from_current_next_data(self):
        page = '<script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"apiData":{"job":{"role":"<p>Build reliable services.</p>"}}}}}</script>'
        self.assertEqual(module.job_posting_description(page), "<p>Build reliable services.</p>")

if __name__ == "__main__": unittest.main()
