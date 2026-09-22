import json
import unittest
from unittest.mock import patch

from app.services import openai_batch


class OpenAIBatchTests(unittest.TestCase):
    def test_request_line_uses_responses_and_strict_schema(self):
        profile = {"candidate": {}, "skills": [], "roles": [], "projects": [], "domains": [], "education": [], "constraints": {}, "evidence_chunks": []}
        with patch.object(openai_batch, "candidate_profile", return_value=profile):
            line = openai_batch.request_line(
                {"id": "123", "job_description": "A sufficiently detailed job description."}, "abc"
            )
        self.assertEqual(line["custom_id"], "batch-abc-job-123")
        self.assertEqual(line["url"], "/v1/responses")
        self.assertEqual(line["body"]["model"], "gpt-5.6-luna")
        self.assertTrue(line["body"]["text"]["format"]["strict"])
        self.assertEqual(line["body"]["prompt_cache_options"]["mode"], "explicit")
        self.assertEqual(line["body"]["input"][1]["content"][0]["prompt_cache_breakpoint"]["mode"], "explicit")

    def test_extracts_structured_text_from_batch_response(self):
        body = {"output": [{"content": [{"type": "output_text", "text": '{"requirements": []}'}]}]}
        self.assertEqual(openai_batch._output_json(body), {"requirements": []})


if __name__ == "__main__":
    unittest.main()
