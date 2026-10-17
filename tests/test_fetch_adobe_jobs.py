from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_adobe_jobs", ROOT / "career portal scripts" / "fetch_adobe_jobs.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class AdobeFetchTests(unittest.TestCase):
    def test_parses_embedded_job_detail_and_normalises_import_schema(self):
        document = 'prefix phApp.ddo = {"jobDetail":{"data":{"job":{"reqId":"R1","title":"Software Engineer","description":"<p>Build reliable services.</p>","location":"Bangalore, India","applyUrl":"https://apply.example/R1"}}}}; suffix'
        detail = module.embedded_data(document, "jobDetail")["data"]["job"]
        result = module.normalise_job({"reqId": "R1", "title": "Software Engineer"}, detail)
        assert result is not None
        self.assertEqual(result["id"], "R1")
        self.assertEqual(result["company"], "Adobe")
        self.assertEqual(result["application_url"], "https://apply.example/R1")
        self.assertEqual(result["jobDescriptionText"], "Build reliable services.")

    def test_preserves_filters_when_changing_page_offset(self):
        url = "https://careers.adobe.com/us/en/c/engineering-and-product-jobs?from=10&s=1&location=India"
        self.assertEqual(module.page_url(url, 20), "https://careers.adobe.com/us/en/c/engineering-and-product-jobs?s=1&location=India&from=20")


if __name__ == "__main__":
    unittest.main()
