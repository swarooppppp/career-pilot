import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from datetime import datetime

from app.services import portal_scheduler as scheduler, job_store as store


class LocalScheduleTests(unittest.TestCase):
    def test_six_slots_and_overnight_catchup(self):
        for hour in (7, 10, 13, 16, 19, 22):
            now = datetime(2026, 11, 3, hour, 15, tzinfo=scheduler.ZONE)
            self.assertEqual(scheduler.latest_slot(now).hour, hour)
        now = datetime(2026, 11, 3, 6, tzinfo=scheduler.ZONE)
        self.assertEqual(scheduler.latest_slot(now).day, 2)
        self.assertEqual(scheduler.latest_slot(now).hour, 22)
        self.assertEqual(scheduler.latest_slot(now.replace(hour=9)).hour, 7)

    def test_completed_slot_does_not_run_twice(self):
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            slot = datetime(2026, 11, 3, 10, tzinfo=scheduler.ZONE)
            state.write_text(json.dumps({'last_slot': slot.isoformat(), 'status': 'complete', 'sources': {}}))
            with patch.object(scheduler, 'STATE', state):
                self.assertFalse(scheduler.collect(slot, threading.Event()))

    def test_process_lock_prevents_overlapping_runs(self):
        from local_career_portals.runtime_support import FileLock
        with TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            with FileLock(state.with_suffix('.lock')) as lock:
                self.assertTrue(lock.acquire())
                with patch.object(scheduler, 'STATE', state):
                    self.assertFalse(scheduler.collect(datetime.now(scheduler.ZONE), threading.Event()))


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.environment = patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///' + self.directory.name + '/jobs.db'})
        self.environment.start()
        store._engine.cache_clear()

    def tearDown(self):
        store._engine.cache_clear()
        self.environment.stop()
        self.directory.cleanup()

    def raw(self, description):
        return {'id': 'one', 'title': 'Software Engineer', 'description': description}

    def test_ceiling_ranges_missing_and_above(self):
        for text, eligible in [('Requires 3+ years', True), ('Requires 3-5 years', True), ('Requires 4+ years', False), ('No requirement', True), ('Requires 0 years', True)]:
            self.assertEqual(store.normalise_job(self.raw(text), 'example', 2.4)['experience_eligible'], eligible)

    def test_applied_deleted_and_resume_preserve_user_actions(self):
        raw = self.raw('Requires 2 years')
        store.import_jobs([raw], 'example', 2.4)
        ident = store.list_jobs()[0]['id']
        store.update_user_status(ident, 'applied')
        store.mark_resume_generated(ident)
        self.assertEqual(store.list_jobs(), [])
        store.import_jobs([self.raw('Requires 3 years')], 'example', 2.4)
        self.assertTrue(store.get_job(ident)['applied'])
        self.assertEqual(store.get_job(ident)['user_status'], 'applied')
        store.update_user_status(ident, 'deleted')
        store.import_jobs([raw], 'example', 2.4)
        self.assertIsNotNone(store.get_job(ident)['deleted_at'])
        self.assertEqual(store.reserve_pending_jobs_for_batch(100), [])

    def test_old_batch_cannot_match_changed_description(self):
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        job = store.reserve_pending_jobs_for_batch(100)[0]
        batch = store.record_analysis_batch('remote', 'file', [job['id']], content_hashes={job['id']: job['content_hash']})
        self.assertTrue(store.batch_item_is_current(batch, job['id']))
        store.import_jobs([self.raw('Requires 3 years')], 'example', 2.4)
        self.assertFalse(store.batch_item_is_current(batch, job['id']))
        store.update_analysis_batch(batch, 'completed')
        self.assertEqual(len(store.reserve_pending_jobs_for_batch(100)), 1)

class DashboardTests(LifecycleTests):
    def test_api_actions_and_pending_resume(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with patch.dict(os.environ, {'PORTAL_SCHEDULER_ENABLED': 'false', 'APP_PASSWORD': ''}), patch('app.main.start_batch_scheduler', return_value=threading.Event()):
            with TestClient(app) as client:
                store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
                job = client.get('/api/jobs').json()['jobs'][0]
                self.assertEqual(client.get('/api/jobs/' + job['id']).status_code, 200)
                self.assertEqual(client.post('/api/jobs/' + job['id'] + '/generate-resume').status_code, 422)
                self.assertEqual(client.post('/api/jobs/' + job['id'] + '/action', json={'status': 'applied'}).status_code, 200)
                self.assertEqual(client.get('/api/jobs').json()['jobs'], [])
                self.assertTrue(store.get_job(job['id'])['applied'])
                self.assertEqual(client.delete('/api/jobs/' + job['id']).status_code, 200)
                self.assertIsNotNone(store.get_job(job['id'])['deleted_at'])

class BatchFailureTests(LifecycleTests):
    def test_client_failure_releases_reserved_jobs(self):
        from app.services import openai_batch
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        ident = store.list_jobs()[0]['id']
        with patch.object(openai_batch, '_client', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                openai_batch.submit_pending_batch(100)
        self.assertEqual(store.get_job(ident)['analysis_status'], 'pending')

    def test_interrupted_submission_is_not_respent_automatically(self):
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        ident = store.reserve_pending_jobs_for_batch(100)[0]['id']
        store.recover_untracked_batch_reservations()
        self.assertEqual(store.get_job(ident)['analysis_status'], 'failed')
        self.assertEqual(store.reserve_pending_jobs_for_batch(100), [])

class ParallelCollectionTests(unittest.TestCase):
    def test_fast_source_imports_before_slow_source_finishes(self):
        import sys
        import importlib
        sys.path.insert(0, str(scheduler.ROOT / 'local_career_portals'))
        sampler = importlib.import_module('sample_all')
        imported = threading.Event()
        def fake_fetch(company, directory, limit, timeout):
            if company['slug'] == 'slow':
                self.assertTrue(imported.wait(3), 'fast source was not imported promptly')
            return {'status': 'ok', 'jobs': [], 'jobs_count': 0}
        def fake_import(jobs, slug, years):
            if slug == 'fast':
                imported.set()
            return {'imported': 0}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local_career_portals').mkdir()
            (root / 'local_career_portals' / 'companies.json').write_text(json.dumps({'companies': [
                {'slug': name, 'status': 'implemented'} for name in ['fast', 'slow']]}))
            with patch.object(scheduler, 'ROOT', root), patch.object(scheduler, 'STATE', root / 'data' / 'state.json'), patch.object(scheduler, 'initialise'), patch.object(scheduler, 'import_jobs', side_effect=fake_import), patch.object(sampler, 'fetch', side_effect=fake_fetch), patch.dict(os.environ, {'PORTAL_WORKERS': '2'}):
                slot = datetime.now(scheduler.ZONE)
                self.assertTrue(scheduler.collect(slot, threading.Event()))
                self.assertEqual(scheduler.read_state()['status'], 'complete')
                self.assertFalse(scheduler.collect(slot, threading.Event()))

class BulkDeleteTests(LifecycleTests):
    def test_bulk_delete_deduplicates_and_survives_import(self):
        raw = [self.raw('Requires 2 years'), {**self.raw('Requires 2 years'), 'id': 'two'}]
        store.import_jobs(raw, 'example', 2.4)
        ids = [job['id'] for job in store.list_jobs()]
        self.assertEqual(store.delete_jobs([ids[0], ids[0], 'missing']), 1)
        self.assertEqual(len(store.list_jobs()), 1)
        store.import_jobs(raw, 'example', 2.4)
        self.assertEqual(len(store.list_jobs()), 1)
        self.assertEqual(store.delete_jobs(ids), 1)
        self.assertEqual(store.list_jobs(), [])

    def test_bulk_delete_endpoint_validation_and_response(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with patch.dict(os.environ, {'APP_PASSWORD': '', 'PORTAL_SCHEDULER_ENABLED': 'false'}), patch('app.main.start_batch_scheduler', return_value=threading.Event()):
            with TestClient(app) as client:
                store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
                ident = store.list_jobs()[0]['id']
                self.assertEqual(client.post('/api/jobs/bulk-delete', json={'job_ids': []}).status_code, 422)
                self.assertEqual(client.post('/api/jobs/bulk-delete', json={'job_ids': [ident, ident]}).json(), {'deleted': 1})
                self.assertEqual(store.list_jobs(), [])

class CollectionStatisticsTests(unittest.TestCase):
    def test_existing_run_counts_only_inserts_and_includes_zero_sources(self):
        state = scheduler.collection_statistics({'sources': {
            'one': {'status': 'ok', 'import': {'imported': 3, 'updated': 8, 'skipped': 20}},
            'two': {'status': 'failed'},
            'three': {'status': 'queued', 'new_jobs': 0},
        }})
        self.assertEqual(state['statistics'], {'new_jobs_total': 3, 'new_eligible_jobs_total': 0, 'companies_completed': 2, 'companies_total': 3})
        self.assertEqual(state['sources']['two']['new_jobs'], 0)

    def test_recovery_total_prefers_accumulated_insert_count(self):
        state = scheduler.collection_statistics({'sources': {
            'one': {'status': 'ok', 'new_jobs': 7, 'import': {'imported': 0, 'skipped': 7}},
        }})
        self.assertEqual(state['statistics']['new_jobs_total'], 7)

    def test_a_new_run_resets_counts_and_keeps_last_success(self):
        import importlib
        import sys
        from datetime import timedelta
        sys.path.insert(0, str(scheduler.ROOT / 'local_career_portals'))
        sampler = importlib.import_module('sample_all')
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local_career_portals').mkdir()
            (root / 'local_career_portals' / 'companies.json').write_text(json.dumps({'companies': [{'slug': 'one', 'status': 'implemented'}]}))
            slot = datetime.now(scheduler.ZONE)
            with patch.object(scheduler, 'ROOT', root), patch.object(scheduler, 'STATE', root / 'data' / 'state.json'), patch.object(scheduler, 'initialise'), patch.object(scheduler, 'import_jobs', side_effect=[{'imported': 5}, {'imported': 0, 'skipped': 5}]), patch.object(sampler, 'fetch', return_value={'status': 'ok', 'jobs': [], 'jobs_count': 5}):
                scheduler.collect(slot, threading.Event())
                self.assertEqual(scheduler.read_state()['statistics']['new_jobs_total'], 5)
                scheduler.collect(slot + timedelta(hours=3), threading.Event())
                self.assertEqual(scheduler.read_state()['statistics']['new_jobs_total'], 0)
                self.assertIsNotNone(scheduler.read_state()['sources']['one']['last_success_at'])

class EligibleImportStatisticsTests(LifecycleTests):
    def test_new_eligible_count_excludes_filtered_and_repeated_jobs(self):
        raw = [self.raw('Requires 2 years'), {**self.raw('Requires 5 years'), 'id': 'senior'}]
        first = store.import_jobs(raw, 'example', 2.4)
        self.assertEqual(first['imported'], 1)
        self.assertEqual(first['imported_eligible'], 1)
        repeated = store.import_jobs(raw, 'example', 2.4)
        self.assertEqual(repeated['imported_eligible'], 0)
        changed = store.import_jobs([self.raw('Requires 3 years')], 'example', 2.4)
        self.assertEqual(changed['imported_eligible'], 0)

    def test_legacy_run_count_handles_india_timezone_and_deleted_jobs(self):
        from datetime import timedelta
        start = datetime.now(scheduler.ZONE) - timedelta(seconds=1)
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        ident = store.list_jobs()[0]['id']
        store.update_user_status(ident, 'deleted')
        state = scheduler.collection_statistics({'started_at': start.isoformat(), 'completed_at': datetime.now(scheduler.ZONE).isoformat(), 'sources': {'example': {'status': 'ok', 'import': {'imported': 1}}}})
        self.assertEqual(state['statistics']['new_eligible_jobs_total'], 1)

class EligibleOnlyStorageTests(LifecycleTests):
    def test_rejected_jobs_never_reach_jobs_table(self):
        counts = store.import_jobs([self.raw('Requires 5 years')], 'example', 2.4)
        self.assertEqual(counts['imported'], 0)
        self.assertEqual(counts['ineligible'], 1)
        self.assertEqual(store.list_jobs(include_ineligible=True), [])

    def test_becoming_ineligible_removes_description_and_preserves_applied_marker(self):
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        ident = store.list_jobs()[0]['id']
        store.update_user_status(ident, 'applied')
        store.import_jobs([self.raw('Requires 5 years')], 'example', 2.4)
        self.assertIsNone(store.get_job(ident))
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        self.assertEqual(store.list_jobs(include_ineligible=True), [])
        self.assertEqual(store.existing_external_job_ids('example'), set())

    def test_cleanup_preserves_deleted_marker(self):
        from sqlalchemy import update
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        ident = store.list_jobs()[0]['id']
        store.update_user_status(ident, 'deleted')
        with store._engine(store.database_url()).begin() as connection:
            connection.execute(update(store.jobs).where(store.jobs.c.id == ident).values(experience_eligible=False))
        self.assertEqual(store.purge_ineligible_jobs(), 1)
        self.assertEqual(store.purge_ineligible_jobs(), 0)
        store.import_jobs([self.raw('Requires 2 years')], 'example', 2.4)
        self.assertIsNone(store.get_job(ident))
        self.assertEqual(store.list_jobs(include_ineligible=True), [])
