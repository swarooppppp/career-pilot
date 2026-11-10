import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
import app.main as main


class AssetVersionTests(unittest.TestCase):
    def test_page_requests_new_script_when_frontend_changes(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {'APP_PASSWORD': ''}):
            assets=Path(directory)
            (assets/'app.js').write_text('// old frontend')
            (assets/'styles.css').write_text('body {}')
            with patch.object(main, 'STATIC_DIR', assets):
                client=TestClient(main.app)
                first=client.get('/')
                old_url=re.search(r'src="(/static/app.js[^\"]*)"',first.text).group(1)
                (assets/'app.js').write_text('// manual fetch button handler')
                second=client.get('/')
                new_url=re.search(r'src="(/static/app.js[^\"]*)"',second.text).group(1)
                self.assertNotEqual(old_url,new_url)
                self.assertEqual(new_url,re.search(r'src="(/static/app.js[^\"]*)"',client.get('/').text).group(1))
                self.assertEqual(second.headers['cache-control'],'no-cache')
                self.assertIn('id="fetch-jobs"',second.text)
