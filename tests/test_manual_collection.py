import importlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch
from datetime import datetime,timedelta

from app.services import portal_scheduler as scheduler


class ManualCollectionTests(unittest.TestCase):
    def test_scheduler_disabled_by_default_and_manual_trigger_still_available(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(scheduler.threading, 'Thread') as thread:
            stop = scheduler.start_portal_scheduler()
            self.assertFalse(stop.is_set())
            thread.assert_not_called()
        with patch.dict(os.environ, {'PORTAL_SCHEDULER_ENABLED': 'false'}), patch.object(scheduler.threading, 'Thread') as thread:
            stop = scheduler.start_portal_scheduler()
            thread.assert_not_called()


    def test_reservation_prevents_manual_and_scheduled_overlap_and_releases_after_failure(self):
        entered = threading.Event()
        release = threading.Event()
        threads = []
        real_thread = threading.Thread
        def thread_factory(**kwargs):
            thread = real_thread(**kwargs)
            threads.append(thread)
            return thread
        def collection(*args, **kwargs):
            self.assertTrue(kwargs['manual'])
            entered.set()
            release.wait(3)
            raise RuntimeError('test network unavailable')
        with TemporaryDirectory() as directory, patch.object(scheduler, 'STATE', Path(directory)/'state.json'), patch.object(scheduler, '_collect_locked', side_effect=collection), patch.object(scheduler.threading, 'Thread', side_effect=thread_factory):
            try:
                self.assertTrue(scheduler.trigger_manual_collection())
                self.assertTrue(entered.wait(2))
                self.assertTrue(scheduler.collection_is_running())
                self.assertFalse(scheduler.trigger_manual_collection())
                self.assertFalse(scheduler.collect(datetime.now(scheduler.ZONE), threading.Event()))
            finally:
                release.set()
                for thread in threads:
                    thread.join(3)
            self.assertFalse(scheduler.collection_is_running())
            self.assertEqual(scheduler.read_state()['status'], 'failed')

    def test_manual_run_bypasses_completed_slot_without_consuming_next_schedule(self):
        real_root = scheduler.ROOT
        sys.path.insert(0,str(real_root/'local_career_portals'))
        sampler = importlib.import_module('sample_all')
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'local_career_portals').mkdir()
            (root/'local_career_portals'/'companies.json').write_text(json.dumps({'companies':[{'slug':'example','status':'implemented'}]}))
            slot = datetime(2026,11,5,10,tzinfo=scheduler.ZONE)
            with patch.object(scheduler,'ROOT',root), patch.object(scheduler,'STATE',root/'data'/'state.json'), patch.object(scheduler,'initialise'), patch.object(scheduler,'import_jobs',return_value={'imported':1,'imported_eligible':1}), patch.object(sampler,'fetch',side_effect=lambda *args: {'status':'ok','jobs':[],'jobs_count':1}):
                scheduler.write_state({'last_slot':slot.isoformat(),'status':'complete','sources':{}})
                self.assertFalse(scheduler.collect(slot,threading.Event()))
                self.assertTrue(scheduler._collect_locked(slot,threading.Event(),manual=True))
                state = scheduler.read_state()
                self.assertEqual(state['trigger'],'manual')
                self.assertEqual(state['last_slot'],slot.isoformat())
                self.assertEqual(state['statistics']['new_eligible_jobs_total'],1)
                self.assertTrue(scheduler._collect_locked(slot,threading.Event(),manual=True))
                self.assertEqual(scheduler.read_state()['statistics']['new_eligible_jobs_total'],1)
                self.assertTrue(scheduler.collect(slot+timedelta(hours=3),threading.Event()))
                self.assertEqual(scheduler.read_state()['trigger'],'scheduled')

    def test_api_returns_accepted_or_conflict_without_fetching(self):
        from fastapi.testclient import TestClient
        from app.main import app
        with patch.dict(os.environ, {'APP_PASSWORD': ''}):
            client = TestClient(app)
            with patch.object(scheduler, 'trigger_manual_collection', return_value=True):
                self.assertEqual(client.post('/api/jobs/sources/fetch').status_code, 202)
            with patch.object(scheduler, 'trigger_manual_collection', return_value=False):
                response = client.post('/api/jobs/sources/fetch')
                self.assertEqual(response.status_code, 409)
                self.assertIn('already running', response.json()['detail'])
