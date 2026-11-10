import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from automation import migrate_local as migration
from local_career_portals.runtime_support import FileLock, stop_process_tree


class PortableRuntimeTests(unittest.TestCase):
    def test_lock_cross_process_and_crash_recovery_in_spaced_path(self):
        with tempfile.TemporaryDirectory(prefix='career pilot ') as directory:
            path = Path(directory) / 'a lock'
            lock = FileLock(path)
            self.assertTrue(lock.acquire())
            code = 'from local_career_portals.runtime_support import FileLock; import sys; l=FileLock(sys.argv[1]); print(l.acquire()); l.close()'
            try:
                self.assertEqual(subprocess.check_output([sys.executable, '-c', code, str(path)], text=True).strip(), 'False')
            finally:
                lock.close()
            self.assertEqual(subprocess.check_output([sys.executable, '-c', code, str(path)], text=True).strip(), 'True')
            child_code = 'from local_career_portals.runtime_support import FileLock; import sys,time; l=FileLock(sys.argv[1]); assert l.acquire(); print("locked",flush=True); time.sleep(30)'
            child = subprocess.Popen([sys.executable, '-c', child_code, str(path)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'locked')
                child.kill()
                child.wait()
                self.assertTrue(lock.acquire())
                lock.close()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stdout.close()

    def test_cleanup_targets_child_tree_only(self):
        try:
            import psutil
        except ImportError:
            self.skipTest('psutil not installed on this host; required in CI')
        script = 'import subprocess,sys,time; c=subprocess.Popen([sys.executable,"-c","import time;time.sleep(60)"]); print(c.pid,flush=True); time.sleep(60)'
        child = subprocess.Popen([sys.executable, '-c', script], stdout=subprocess.PIPE, text=True)
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        grandchild = int(child.stdout.readline().strip())
        try:
            stop_process_tree(child)
            self.assertIsNotNone(child.poll())
            self.assertIsNone(unrelated.poll())
            if psutil.pid_exists(grandchild):
                self.assertEqual(psutil.Process(grandchild).status(), psutil.STATUS_ZOMBIE)
        finally:
            unrelated.kill()
            unrelated.wait()
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdout.close()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='migration with spaces ')
        self.root = Path(self.temp.name) / 'source'
        self.root.mkdir()
        (self.root / 'data').mkdir()
        (self.root / '.env').write_text('OPENAI_API_KEY=private-test-key\nDATABASE_URL=sqlite:///data/career_pilot.db\n')
        with migration.connect(self.root / migration.DB_MEMBER) as db:
            db.executescript("CREATE TABLE jobs(id TEXT, user_status TEXT, resume_filename TEXT); CREATE TABLE analysis_batches(id TEXT); INSERT INTO analysis_batches VALUES('remote-batch-id');")
            db.executemany('INSERT INTO jobs VALUES(?,?,?)', [('one','saved',r'folder\Swaroop_Software_Engineer.pdf'),('two','applied',None),('three','deleted',None)])
        pdf = self.root / 'generated/resumes/one/folder/Swaroop_Software_Engineer.pdf'
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b'%PDF-test')
        cache = self.root / 'data/match_cache/cache.json'
        cache.parent.mkdir()
        cache.write_text('{}')
        (self.root / 'data/portal_schedule.json').write_text('{"status":"complete"}')
        self.archive = Path(self.temp.name) / 'test.migration.zip'
        self.env = patch.dict(os.environ, {'DATABASE_URL': 'sqlite:///data/career_pilot.db'})
        self.env.start()
        self.stopped = patch.object(migration, 'require_stopped')
        self.stopped.start()

    def tearDown(self):
        self.stopped.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_roundtrip_counts_states_remote_batches_paths_and_artifacts(self):
        expected = migration.backup(self.root, self.archive)
        destination = Path(self.temp.name) / 'windows clone'
        destination.mkdir()
        result = migration.restore(destination, self.archive)
        self.assertEqual(expected, result)
        self.assertEqual(result['job_states'], {'saved':1,'applied':1,'deleted':1})
        with migration.connect(destination / migration.DB_MEMBER) as db:
            self.assertEqual(db.execute("SELECT resume_filename FROM jobs WHERE id='one'").fetchone()[0], 'folder/Swaroop_Software_Engineer.pdf')
            self.assertEqual(db.execute('SELECT id FROM analysis_batches').fetchone()[0], 'remote-batch-id')
        self.assertTrue((destination/'generated/resumes/one/folder/Swaroop_Software_Engineer.pdf').exists())
        with zipfile.ZipFile(self.archive) as archive:
            self.assertNotIn('.env', archive.namelist())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            migration.restore(destination, self.archive)
        migration.restore(destination, self.archive, replace=True)

    def test_corrupt_archive_is_rejected_before_writing_destination(self):
        migration.backup(self.root, self.archive)
        bad = Path(self.temp.name)/'bad.zip'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(bad,'w') as dest:
            for name in source.namelist():
                dest.writestr(name, b'corrupt' if name.endswith('cache.json') else source.read(name))
        destination = Path(self.temp.name)/'target'
        destination.mkdir()
        with self.assertRaisesRegex(ValueError,'Checksum'):
            migration.restore(destination,bad)
        self.assertFalse((destination/migration.DB_MEMBER).exists())

    def test_traversal_is_rejected(self):
        migration.backup(self.root, self.archive)
        bad = Path(self.temp.name)/'bad.zip'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(bad,'w') as dest:
            manifest = json.loads(source.read('manifest.json'))
            manifest['files']['data/../../escape']='x'
            for name in source.namelist():
                if name != 'manifest.json':
                    dest.writestr(name,source.read(name))
            dest.writestr('manifest.json',json.dumps(manifest))
            dest.writestr('data/../../escape','bad')
        destination = Path(self.temp.name)/'target'
        destination.mkdir()
        with self.assertRaisesRegex(ValueError,'Unsafe'):
            migration.restore(destination,bad)
        self.assertFalse((destination/migration.DB_MEMBER).exists())

    def test_stopped_guard_refuses_listener(self):
        self.stopped.stop()
        with patch.object(migration.socket,'socket') as socket:
            socket.return_value.__enter__.return_value.connect_ex.return_value=0
            with self.assertRaisesRegex(ValueError,'Stop the local app'):
                migration.require_stopped(self.root)


class WindowsServiceTests(unittest.TestCase):
    def test_task_is_interactive_manual_collection_only_and_restartable(self):
        from automation.windows_service import task_xml
        import xml.etree.ElementTree as ET
        with patch.dict(os.environ, {'USERDOMAIN':'Test','USERNAME':'User'}):
            xml = task_xml()
        root = ET.fromstring(xml)
        ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        self.assertEqual(root.find('.//t:LogonType',ns).text,'InteractiveToken')
        self.assertEqual(root.find('.//t:ExecutionTimeLimit',ns).text,'PT0S')
        self.assertEqual(root.find('.//t:MultipleInstancesPolicy',ns).text,'IgnoreNew')
        self.assertEqual(root.find('.//t:RestartOnFailure/t:Count',ns).text,'999')
        self.assertIn('-X utf8',root.find('.//t:Arguments',ns).text)

    def test_update_refuses_dirty_checkout_before_stop(self):
        from automation import windows_service as service
        with patch.object(service.subprocess,'check_output',return_value=' M app.py'), patch.object(service,'stop') as stop:
            with self.assertRaisesRegex(RuntimeError,'Local code changes'):
                service.update()
            stop.assert_not_called()


class UpdateSafetyTests(unittest.TestCase):
    def test_active_collection_blocks_update_before_stopping(self):
        from automation import windows_service as service
        with patch.object(service.subprocess, 'check_output', return_value=''), patch.object(service, 'busy', return_value='Job collection is active'), patch.object(service, 'stop') as stop:
            with self.assertRaisesRegex(RuntimeError, 'collection is active'):
                service.update()
            stop.assert_not_called()

    def test_failed_pull_retains_backup_and_does_not_restart(self):
        from automation import windows_service as service
        with patch.object(service.subprocess, 'check_output', return_value=''), patch.object(service, 'busy', return_value=None), patch.object(service, 'running', return_value={'pid':1}), patch.object(service, 'stop') as stop, patch.object(migration, 'backup') as backup, patch.object(service.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['git','pull'])), patch.object(service, 'start') as start:
            with self.assertRaises(subprocess.CalledProcessError):
                service.update()
            stop.assert_called_once()
            backup.assert_called_once()
            start.assert_not_called()
