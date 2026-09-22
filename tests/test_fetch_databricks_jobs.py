from __future__ import annotations
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_databricks_jobs", ROOT / "career portal scripts" / "fetch_databricks_jobs.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name] = module; SPEC.loader.exec_module(module)

class DatabricksFetchTests(unittest.TestCase):
    def test_filters_url_terms_and_normalises_greenhouse_job(self):
        job = {"id": 1, "title": "Software Engineer", "content": "<p>Build APIs.</p>", "absolute_url": "https://databricks.com/job/1",
               "updated_at": "2026-09-22", "location": {"name": "Bengaluru, India"}, "departments": [{"name": "Engineering"}]}
        self.assertTrue(module.matches(job, module.parse_qs("department=Engineering&location=India&search=Software+Engineer")))
        result = module.normalise_result(job)
        assert result is not None
        self.assertEqual(result["company"], "Databricks")
        self.assertIn("Build APIs.", result["jobDescriptionText"])

if __name__ == "__main__":
    unittest.main()
