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

    def test_two_year_experience_buffer_keeps_four_year_role(self):
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

    def test_multiple_experience_requirements_expose_lowest_and_highest_values(self):
        requirement = "Requires 5 years of product management and 2 years of cloud product experience."

        self.assertEqual(job_store.extract_minimum_years(requirement), 2.0)
        self.assertEqual(job_store.extract_experience_years(requirement), (2.0, 5.0))

    def test_highest_explicit_requirement_controls_the_deterministic_gate(self):
        job_store.import_jobs(
            [raw_job(description="Requires 4 years of Java and 6 years of backend engineering experience.")],
            "google",
            candidate_years=2,
        )

        jobs = job_store.list_jobs(include_ineligible=True)
        self.assertEqual(jobs[0]["minimum_years_experience"], 4.0)
        self.assertFalse(jobs[0]["experience_eligible"])

    def test_requirement_above_two_year_buffer_is_not_sent_to_dashboard(self):
        job_store.import_jobs([raw_job(description="Requires 5+ years of Java experience.")], "google", 2)

        self.assertEqual(job_store.list_jobs(), [])
        self.assertEqual(len(job_store.list_jobs(include_ineligible=True)), 1)

    def test_manager_and_staff_titles_are_eliminated_before_llm_processing(self):
        manager = raw_job(job_id="manager", description="No experience requirement.")
        manager["title"] = "Engineering Manager"
        staff = raw_job(job_id="staff", description="No experience requirement.")
        staff["title"] = "Staff Software Engineer"

        result = job_store.import_jobs([manager, staff], "google", 2)
        jobs = job_store.list_jobs(include_ineligible=True)

        self.assertEqual(result["ineligible"], 2)
        self.assertEqual(job_store.list_jobs(), [])
        self.assertTrue(all("excluded seniority" in job["filter_reason"] for job in jobs))

    def test_unchanged_portal_job_is_not_imported_or_reprocessed(self):
        first = job_store.import_jobs([raw_job()], "google", 2)
        second = job_store.import_jobs([raw_job()], "google", 2)

        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(len(job_store.queue_pending_jobs(10)), 1)

    def test_unchanged_job_recalculates_eligibility_without_discarding_analysis(self):
        job_store.import_jobs([raw_job()], "google", 2)
        job_id = job_store.list_jobs()[0]["id"]
        job_store.save_analysis(job_id, {"overall_score": 91, "summary": "Completed"})

        result = job_store.import_jobs([raw_job()], "google", 0)
        stored = job_store.get_job(job_id)

        self.assertEqual(result["updated"], 1)
        self.assertFalse(stored["experience_eligible"])
        self.assertEqual(stored["analysis_status"], "completed")
        self.assertEqual(stored["match_score"], 91)

    def test_changed_detail_url_updates_an_unchanged_job(self):
        first_job = raw_job()
        first_job["application_url"] = "https://example.test/job-detail"
        second_job = {**first_job, "application_url": "https://example.test/job-detail-v2"}

        first = job_store.import_jobs([first_job], "google", 2)
        second = job_store.import_jobs([second_job], "google", 2)
        stored = job_store.list_jobs()[0]

        self.assertEqual(first["imported"], 1)
        self.assertEqual(second["updated"], 1)
        self.assertEqual(stored["application_url"], "https://example.test/job-detail-v2")

    def test_detail_url_change_preserves_existing_analysis_state(self):
        first_job = raw_job()
        first_job["application_url"] = "https://example.test/job-detail"
        job_store.import_jobs([first_job], "google", 2)
        job_id = job_store.list_jobs()[0]["id"]
        job_store.save_analysis_error(job_id, RuntimeError("previous failure"))

        job_store.import_jobs([{**first_job, "application_url": "https://example.test/job-detail-v2"}], "google", 2)

        self.assertEqual(job_store.get_job(job_id)["analysis_status"], "failed")

    def test_active_batch_job_is_not_reserved_a_second_time(self):
        job_store.import_jobs([raw_job()], "google", 2)
        job_id = job_store.list_jobs()[0]["id"]
        job_store.record_analysis_batch("provider-1", "file-1", [job_id])

        self.assertEqual(job_store.reserve_pending_jobs_for_batch(10), [])

    def test_previously_submitted_job_is_not_automatically_submitted_again(self):
        job_store.import_jobs([raw_job()], "google", 2)
        job_id = job_store.list_jobs()[0]["id"]
        batch_id = job_store.record_analysis_batch("provider-1", "file-1", [job_id])
        job_store.update_analysis_batch(batch_id, "completed")

        self.assertEqual(job_store.reserve_pending_jobs_for_batch(10), [])

    def test_explicit_retry_can_resubmit_a_previously_batched_failed_job(self):
        job_store.import_jobs([raw_job()], "google", 2)
        job_id = job_store.list_jobs()[0]["id"]
        batch_id = job_store.record_analysis_batch("provider-1", "file-1", [job_id])
        job_store.update_analysis_batch(batch_id, "failed")
        job_store.save_analysis_error(job_id, RuntimeError("batch failure"))

        self.assertTrue(job_store.retry_analysis(job_id))
        self.assertEqual(job_store.reserve_pending_jobs_for_batch(10)[0]["id"], job_id)

    def test_google_sign_in_url_is_replaced_with_the_public_job_detail_url(self):
        job = raw_job(job_id="85847378480767686")
        job["title"] = "Senior Software Engineer, Search Platforms"
        job["applyUrl"] = "https://www.google.com/about/careers/applications/signin?jobId=85847378480767686"

        job_store.import_jobs([job], "google", 2)
        application_url = job_store.list_jobs()[0]["application_url"]

        self.assertEqual(
            application_url,
            "https://www.google.com/about/careers/applications/jobs/results/"
            "85847378480767686-senior-software-engineer-search-platforms",
        )
        self.assertNotIn("signin", application_url)

    def test_batch_item_custom_ids_allow_a_job_to_be_resubmitted(self):
        first_batch = job_store.record_analysis_batch("provider-1", "file-1", ["job-1"])
        second_batch = job_store.record_analysis_batch("provider-2", "file-2", ["job-1"])

        first_custom_id = next(iter(job_store.batch_job_ids(first_batch)))
        second_custom_id = next(iter(job_store.batch_job_ids(second_batch)))

        self.assertNotEqual(first_custom_id, second_custom_id)
        self.assertEqual(job_store.batch_job_ids(second_batch)[second_custom_id], "job-1")

    def test_legacy_provider_custom_id_can_be_recovered_for_a_new_batch(self):
        job_store.record_analysis_batch("provider-1", "file-1", ["job-1"], custom_ids={"job-1": "job-job-1"})
        recovered = job_store.record_analysis_batch("provider-2", "file-2", ["job-1"], custom_ids={"job-1": "job-job-1"})

        self.assertEqual(job_store.batch_job_ids(recovered), {"job-job-1": "job-1"})

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
