from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "career portal scripts" / "fetch_meta_jobs.py"
SPEC = importlib.util.spec_from_file_location("fetch_meta_jobs", MODULE_PATH)
assert SPEC and SPEC.loader
fetch_meta_jobs = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = fetch_meta_jobs
SPEC.loader.exec_module(fetch_meta_jobs)


class MetaFetchTests(unittest.TestCase):
    def test_derives_external_id_from_path_or_query(self):
        self.assertEqual(fetch_meta_jobs.external_id("https://www.metacareers.com/profile/job_details/12345/"), "12345")
        self.assertEqual(fetch_meta_jobs.external_id("https://www.metacareers.com/profile/job_details/?id=54321"), "54321")

    def test_normalises_detail_text_to_import_schema(self):
        result = fetch_meta_jobs.normalise_result({
            "job_url": "https://www.metacareers.com/profile/job_details/12345/",
            "title": "Software Engineer", "description_text": "Build reliable services.",
        })
        assert result is not None
        self.assertEqual(result["id"], "12345")
        self.assertEqual(result["company"], "Meta")
        self.assertIn("Build reliable services.", result["jobDescriptionHtml"])


if __name__ == "__main__":
    unittest.main()
