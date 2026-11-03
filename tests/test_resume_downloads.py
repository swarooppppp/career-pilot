from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.api.routes.resume import download_resume, generate_resume_endpoint, ResumeRequest


class ResumeDownloadTests(unittest.TestCase):
    def test_timestamp_folder_download_has_fixed_attachment_name(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'job-one' / 'Swaroop_Software_Engineer_2026-11-03_233500_000001' / 'Swaroop_Software_Engineer.pdf'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'%PDF-test')
            with patch('app.services.resume_tasks.RESUME_ROOT', root):
                response = download_resume('job-one', path.relative_to(root / 'job-one').as_posix())
            self.assertEqual(response.path, path.resolve())
            self.assertEqual(response.filename, 'Swaroop_Software_Engineer.pdf')
            self.assertIn('filename="Swaroop_Software_Engineer.pdf"', response.headers['content-disposition'])

    def test_parent_traversal_is_rejected(self):
        for filename in ['../private.pdf', '/private.pdf', 'folder/../../private.pdf']:
            with self.assertRaises(HTTPException) as error:
                download_resume('job-one', filename)
            self.assertEqual(error.exception.status_code, 400)

    def test_direct_generation_url_includes_timestamp_folder(self):
        with TemporaryDirectory() as directory:
            def fake_generate(jd, output):
                return output.resolve() / 'Swaroop_Software_Engineer_timestamp' / 'Swaroop_Software_Engineer.pdf'
            with patch('app.api.routes.resume.TEMP_ROOT', Path(directory)), patch('app.api.routes.resume.generate_resume', side_effect=fake_generate), patch('app.api.routes.resume.send_resume_email', return_value=False):
                result = generate_resume_endpoint(ResumeRequest(job_description='A sufficiently detailed job description.'))
            self.assertEqual(result['filename'], 'Swaroop_Software_Engineer.pdf')
            self.assertTrue(result['download_url'].endswith('/Swaroop_Software_Engineer_timestamp/Swaroop_Software_Engineer.pdf'))
