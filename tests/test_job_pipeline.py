import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import job_pipeline, job_store


class JobPipelineTests(unittest.TestCase):
    def test_transient_gemini_error_retries_with_backoff(self):
        job = {
            "id": "job-1", "job_description": "A detailed Java role description.",
            "experience_eligible": True, "analysis_status": "processing", "user_status": "new",
        }
        analysis = {"overall_score": 80}
        with patch.dict(os.environ, {"GEMINI_MAX_RETRIES": "3"}), \
                patch.object(job_pipeline, "analyse_job", side_effect=[RuntimeError("HTTP 429"), analysis]) as analyse, \
                patch.object(job_pipeline.time, "sleep") as sleep, \
                patch.object(job_pipeline.random, "uniform", return_value=0.25):
            state = job_pipeline.evaluate_match({"job": job})

        self.assertEqual(state["next_step"], "persist")
        self.assertEqual(analyse.call_count, 2)
        sleep.assert_called_once_with(1.25)

    def test_completed_job_is_not_analysed_twice(self):
        with TemporaryDirectory() as directory, patch.dict(
            os.environ, {"DATABASE_URL": f"sqlite:///{Path(directory) / 'career_pilot.db'}"}
        ):
            job_store._engine.cache_clear()
            job_store.import_jobs(
                [{
                    "id": "1",
                    "title": "Backend Engineer",
                    "company": "Example",
                    "jobDescriptionText": "Requires 3+ years building Java REST APIs.",
                }],
                "example",
                candidate_years=2,
            )
            analysis = {
                "overall_score": 87,
                "summary": "Strong match.",
                "strong_matches": [],
                "transferable_matches": [],
                "uncertain_requirements": [],
                "critical_gaps": [],
                "recommendations": [],
                "requirements": [],
            }
            with patch.object(job_pipeline, "analyse_job", return_value=analysis) as analyse:
                job_id = job_store.queue_pending_jobs(1)[0]
                first = job_pipeline.process_job(job_store.claim_queued_job(job_id))
                second = job_store.claim_queued_job(job_id)

            jobs = job_store.list_jobs()
            self.assertEqual(first, "processed")
            self.assertIsNone(second)
            self.assertEqual(analyse.call_count, 1)
            self.assertEqual(jobs[0]["analysis_status"], "completed")
            self.assertEqual(jobs[0]["match_score"], 87)
            job_store._engine.cache_clear()


if __name__ == "__main__":
    unittest.main()
