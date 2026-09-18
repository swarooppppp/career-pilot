import os
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import job_store


def raw_job(job_id="job-1", description="Requires 3+ years of Java experience."):
    return {
        "id": job_id,
        "title": "Software Engineer",
        "company": "Example",
        "locations": ["Hyderabad"],
        "applyUrl": "https://example.test/jobs/1",
        "jobDescriptionText": description,
    }


class JobStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.database_url = f"sqlite:///{Path(self.directory.name) / 'career_pilot.db'}"
        self.environment_patch = patch.dict(os.environ, {"DATABASE_URL": self.database_url})
        self.environment_patch.start()
        job_store._engine.cache_clear()

    def tearDown(self):
        job_store._engine.cache_clear()
        self.environment_patch.stop()
        self.directory.cleanup()

    def test_one_year_experience_buffer_keeps_three_year_role(self):
        result = job_store.import_jobs([raw_job()], "google", candidate_years=2)
        jobs = job_store.list_jobs()

        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["minimum_years_experience"], 3.0)
        self.assertTrue(jobs[0]["experience_eligible"])

    def test_extracts_bare_years_requirement_to_the_left_of_years(self):
        self.assertEqual(job_store.extract_minimum_years("Requires 6 years of experience."), 6.0)

    def test_extracts_lower_bound_from_a_year_range(self):
        self.assertEqual(job_store.extract_minimum_years("Requires 3 to 5 years of experience."), 3.0)

    def test_extracts_years_requirement_with_number_to_the_right(self):
        self.assertEqual(job_store.extract_minimum_years("Years of experience: 6"), 6.0)

    def test_multiple_experience_requirements_use_the_lowest_for_the_conservative_gate(self):
        requirement = "Requires 5 years of product management and 2 years of cloud product experience."

        self.assertEqual(job_store.extract_minimum_years(requirement), 2.0)

    def test_multiple_requirements_reject_only_when_all_exceed_the_candidate_threshold(self):
        job_store.import_jobs(
            [raw_job(description="Requires 4 years of Java and 6 years of backend engineering experience.")],
            "google",
            candidate_years=2,
        )

        jobs = job_store.list_jobs(include_ineligible=True)
        self.assertEqual(jobs[0]["minimum_years_experience"], 4.0)
        self.assertFalse(jobs[0]["experience_eligible"])

    def test_four_year_role_is_kept_but_not_sent_to_dashboard(self):
        job_store.import_jobs([raw_job(description="Requires 4+ years of Java experience.")], "google", 2)

        self.assertEqual(job_store.list_jobs(), [])
        self.assertEqual(len(job_store.list_jobs(include_ineligible=True)), 1)

    def test_unchanged_portal_job_is_not_imported_or_reprocessed(self):
        first = job_store.import_jobs([raw_job()], "google", 2)
        second = job_store.import_jobs([raw_job()], "google", 2)

        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(len(job_store.queue_pending_jobs(10)), 1)

    def test_failed_analysis_requires_an_explicit_retry(self):
        job_store.import_jobs([raw_job()], "google", 2)
        job = job_store.list_jobs()[0]
        job_store.save_analysis_error(job["id"], RuntimeError("Gemini unavailable"))

        self.assertEqual(job_store.queue_pending_jobs(10), [])
        self.assertTrue(job_store.retry_analysis(job["id"]))
        self.assertEqual(len(job_store.queue_pending_jobs(10)), 1)

    def test_local_worker_claims_a_queued_job_once(self):
        job_store.import_jobs([raw_job()], "google", 2)
        job_store.queue_pending_jobs(1, create_outbox_events=False)

        job = job_store.claim_next_queued_job()
        self.assertIsNotNone(job)
        self.assertEqual(job["analysis_status"], "processing")
        self.assertIsNone(job_store.claim_next_queued_job())

    def test_interrupted_local_worker_job_is_requeued_after_lease(self):
        job_store.import_jobs([raw_job()], "google", 2)
        job_store.queue_pending_jobs(1, create_outbox_events=False)
        job_store.claim_next_queued_job()

        self.assertEqual(job_store.requeue_stale_processing_jobs(max_age_seconds=0), 1)
        self.assertIsNotNone(job_store.claim_next_queued_job())


if __name__ == "__main__":
    unittest.main()
