from __future__ import annotations
import importlib.util, json, sys, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("fetch_zeta_jobs",ROOT/"career portal scripts"/"fetch_zeta_jobs.py")
assert SPEC and SPEC.loader
module=importlib.util.module_from_spec(SPEC); sys.modules[SPEC.name]=module; SPEC.loader.exec_module(module)
class ZetaFetchTests(unittest.TestCase):
    def test_keeps_only_engineering_and_combines_requirements(self):
        groups=[{"title":"Engineering","postings":[{"id":"1","text":"Engineer","description":"<p>Build systems.</p>","lists":[{"content":"<p>3+ years.</p>"}],"categories":{"location":"Bangalore"},"hostedUrl":"https://example.test/1"}]},{"title":"Sales","postings":[]}]
        class Response:
            headers=type("Headers",(),{"get_content_charset":lambda _:"utf-8"})()
            def read(self): return json.dumps(groups).encode()
            def __enter__(self): return self
            def __exit__(self,*_): return False
        with patch.object(module,"urlopen",return_value=Response()): jobs=module.fetch_jobs(30)
        self.assertEqual(jobs[0]["id"],"1"); self.assertIn("3+ years.",jobs[0]["jobDescriptionText"])
if __name__ == "__main__": unittest.main()
