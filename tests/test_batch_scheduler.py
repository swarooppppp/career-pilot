from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock,patch

from app.services import batch_scheduler as scheduler, openai_batch


class BatchSchedulerTests(unittest.TestCase):
    def test_empty_queue_does_not_contact_openai(self):
        with patch.object(openai_batch,'reserve_pending_jobs_for_batch',return_value=[]), patch.object(openai_batch,'_client') as client:
            totals=scheduler.submit_waiting_batches(100,threading.Event())
        self.assertEqual(totals,{'batches':0,'jobs':0})
        client.assert_not_called()

    def test_400_pending_jobs_create_exactly_four_provider_batches(self):
        jobs=[{'id':str(i),'content_hash':'hash-'+str(i),'job_description':'Description'} for i in range(400)]
        batches=[jobs[i:i+100] for i in range(0,400,100)]+[[]]
        uploaded=[]
        def upload(file,purpose):
            import json
            lines=[json.loads(line) for line in file]
            self.assertEqual(len(lines),100)
            uploaded.extend(line['custom_id'] for line in lines)
            return SimpleNamespace(id='file-'+str(len(uploaded)))
        client=Mock()
        client.files.create.side_effect=upload
        client.batches.create.side_effect=[SimpleNamespace(id='provider-'+str(i)) for i in range(4)]
        with patch.object(openai_batch,'reserve_pending_jobs_for_batch',side_effect=batches), patch.object(openai_batch,'_client',return_value=client), patch.object(openai_batch,'request_line',side_effect=lambda job,batch_id:{'custom_id':job['id']}), patch.object(openai_batch,'record_analysis_batch') as record:
            totals=scheduler.submit_waiting_batches(100,threading.Event())
        self.assertEqual(totals,{'batches':4,'jobs':400})
        self.assertEqual(client.batches.create.call_count,4)
        self.assertEqual(record.call_count,4)
        self.assertEqual(len(set(uploaded)),400)

    def test_partial_final_batch_is_submitted(self):
        with patch.object(scheduler,'submit_pending_batch',side_effect=[{'submitted':100},{'submitted':100},{'submitted':35}]) as submit:
            totals=scheduler.submit_waiting_batches(100,threading.Event())
        self.assertEqual(totals,{'batches':3,'jobs':235})
        self.assertEqual(submit.call_count,3)

    def test_stop_prevents_submission(self):
        stop=threading.Event();stop.set()
        with patch.object(scheduler,'submit_pending_batch') as submit:
            self.assertEqual(scheduler.submit_waiting_batches(100,stop),{'batches':0,'jobs':0})
        submit.assert_not_called()

    def test_new_work_notification_wakes_submitter_before_hourly_check(self):
        import os
        first=threading.Event();second=threading.Event();threads=[]
        real_thread=threading.Thread
        def factory(**kwargs):
            thread=real_thread(**kwargs);threads.append(thread);return thread
        def submit(*args):
            if first.is_set():second.set()
            else:first.set()
            return {'batches':0,'jobs':0}
        with patch.dict(os.environ,{'OPENAI_BATCH_SUBMIT_INTERVAL_MINUTES':'60','OPENAI_BATCH_POLL_INTERVAL_MINUTES':'60','OPENAI_BATCH_SUBMISSION_ENABLED':'true'}), patch.object(scheduler,'_work_available',threading.Event()), patch.object(scheduler,'poll_openai_batches') as poll, patch.object(scheduler,'submit_waiting_batches',side_effect=submit), patch.object(scheduler.threading,'Thread',side_effect=factory):
            stop=scheduler.start_batch_scheduler()
            try:
                self.assertTrue(first.wait(2))
                scheduler.notify_matching_work()
                self.assertTrue(second.wait(2))
                self.assertEqual(poll.call_count,1)
            finally:
                stop.set()
                for thread in threads:thread.join(2)
            self.assertTrue(all(not thread.is_alive() for thread in threads))

    def test_no_active_batches_do_not_contact_provider(self):
        with patch.object(openai_batch,'active_analysis_batches',return_value=[]),patch.object(openai_batch,'_client') as client:
            self.assertEqual(openai_batch.poll_openai_batches()['checked'],0)
        client.assert_not_called()
