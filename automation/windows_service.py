#!/usr/bin/env python3
"""Per-user Windows dashboard service; never schedules job collection."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid
from urllib.request import urlopen
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from local_career_portals.runtime_support import FileLock

STATE = ROOT / 'data/windows-service.json'
STOP = ROOT / 'data/windows-service.stop'
LOG = ROOT / 'data/logs/windows-service.log'
TASK = 'CareerPilotLocal'
PYTHON = ROOT / '.venv/Scripts/python.exe'
PYTHONW = ROOT / '.venv/Scripts/pythonw.exe'


def powershell(script):
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                           "$ErrorActionPreference='Stop'; " + script], check=True, capture_output=True, text=True).stdout.strip()


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def running():
    import psutil
    try:
        state = json.loads(STATE.read_text(encoding='utf-8'))
        process = psutil.Process(state['pid'])
        return state if process.create_time() == state['created'] else None
    except (OSError, ValueError, KeyError, psutil.NoSuchProcess):
        return None


def busy():
    from automation.migrate_local import database_path, connect
    import sqlite3
    lock = FileLock(ROOT / 'data/portal_schedule.lock')
    if not lock.acquire():
        return 'Job collection is active. Wait for it to finish.'
    lock.close()
    db = database_path(ROOT)
    if db.exists():
        with connect(db) as connection:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'jobs' in tables and connection.execute("SELECT COUNT(*) FROM jobs WHERE resume_status='generating'").fetchone()[0]:
                return 'Resume generation is active. Wait for it to finish.'
    return None


def wait_health():
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            with urlopen('http://127.0.0.1:8000/health', timeout=2) as response:
                if response.status == 200 and running():
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError('App did not become healthy. See data/logs/windows-service.log.')


def start():
    if running():
        wait_health()
        return
    installed = powershell(f"[bool](Get-ScheduledTask -TaskName {quote(TASK)} -ErrorAction SilentlyContinue)")
    if installed.lower() == 'true':
        powershell(f'Start-ScheduledTask -TaskName {quote(TASK)}')
    else:
        subprocess.Popen([str(PYTHONW), '-X', 'utf8', str(Path(__file__).resolve()), 'run'], cwd=ROOT,
                         creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    wait_health()


def stop():
    state = running()
    if not state:
        return
    reason = busy()
    if reason:
        raise RuntimeError(reason)
    STOP.write_text(state['token'], encoding='utf-8')
    deadline = time.monotonic() + 180
    while running() and time.monotonic() < deadline:
        time.sleep(1)
    if running():
        raise RuntimeError('Shutdown is still pending; no process was forcibly killed. Check the log and retry.')


def task_xml():
    user = escape(os.environ['USERDOMAIN'] + '\\' + os.environ['USERNAME'])
    return f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
<Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{user}</UserId><Delay>PT15S</Delay></LogonTrigger></Triggers>
<Principals><Principal id="Author"><UserId>{user}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
<Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><StartWhenAvailable>true</StartWhenAvailable><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure></Settings>
<Actions Context="Author"><Exec><Command>{escape(str(PYTHONW))}</Command><Arguments>-X utf8 &quot;{escape(str(Path(__file__).resolve()))}&quot; run</Arguments><WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory></Exec></Actions>
</Task>'''


def run():
    lock = FileLock(ROOT / 'data/windows-service.lock')
    if not lock.acquire():
        return
    os.chdir(ROOT)
    os.environ['PORTAL_SCHEDULER_ENABLED'] = 'false'
    os.environ['HOST'] = '127.0.0.1'
    os.environ['PYTHONUTF8'] = '1'
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with lock, LOG.open('a', encoding='utf-8', buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
        import psutil
        import uvicorn
        token = uuid.uuid4().hex
        state = {'pid': os.getpid(), 'created': psutil.Process().create_time(), 'token': token}
        STATE.write_text(json.dumps(state), encoding='utf-8')
        STOP.unlink(missing_ok=True)
        server = uvicorn.Server(uvicorn.Config('app.main:app', host='127.0.0.1', port=8000, log_config=None))
        finished = threading.Event()

        def monitor():
            while not finished.wait(1):
                try:
                    if STOP.read_text(encoding='utf-8') == token:
                        server.should_exit = True
                        return
                except FileNotFoundError:
                    pass
        threading.Thread(target=monitor, daemon=True).start()
        try:
            server.run()
            if not server.started:
                raise RuntimeError('Server failed to start; check the service log.')
        except BaseException:
            import traceback
            traceback.print_exc(file=log)
            raise
        finally:
            finished.set()
            STATE.unlink(missing_ok=True)
            STOP.unlink(missing_ok=True)


def update():
    os.chdir(ROOT)
    if subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('Local code changes exist. Commit/stash them before updating; nothing was changed.')
    reason = busy()
    if reason:
        raise RuntimeError(reason)
    was_running = bool(running())
    stop()
    from automation.migrate_local import backup
    name = datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.migration.zip'
    backup(ROOT, ROOT / 'data/backups' / name)
    try:
        subprocess.run(['git', 'pull', '--ff-only'], check=True)
        subprocess.run([str(PYTHON), '-m', 'pip', 'install', '-r', 'requirements.txt', '-c', 'constraints.txt'], check=True)
        subprocess.run([str(PYTHON), '-m', 'playwright', 'install', 'chromium'], check=True)
        subprocess.run([str(PYTHON), str(ROOT / 'automation/windows_check.py')], check=True)
    except Exception:
        print('Update failed. App remains stopped; your database backup is in data/backups. Fix the error before starting.')
        raise
    if was_running:
        start()
    print('Updated. Local database, credentials and user actions were preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'start', 'stop', 'status', 'install', 'uninstall', 'update', 'logs'])
    args = parser.parse_args()
    if os.name != 'nt':
        parser.exit(1, 'This command is for native Windows. Use automation/local_service.py on macOS.\n')
    try:
        if args.action == 'run':
            run()
        elif args.action == 'start':
            start()
            print('Running: http://127.0.0.1:8000')
        elif args.action == 'stop':
            stop()
            print('Stopped.')
        elif args.action == 'status':
            print('Running; collection is manual only.' if running() else 'Stopped.')
        elif args.action == 'install':
            xml = ROOT / 'data/windows-service.xml'
            xml.parent.mkdir(parents=True, exist_ok=True)
            xml.write_text(task_xml(), encoding='utf-16')
            powershell(f'Register-ScheduledTask -TaskName {quote(TASK)} -Xml (Get-Content -Raw -LiteralPath {quote(xml)}) -Force | Out-Null')
            # A manually started instance must be handed over to Task Scheduler.
            stop()
            start()
            print('Installed login startup. Job fetching remains manual.')
        elif args.action == 'uninstall':
            stop()
            powershell(f'Unregister-ScheduledTask -TaskName {quote(TASK)} -Confirm:$false -ErrorAction SilentlyContinue')
            print('Login startup removed.')
        elif args.action == 'update':
            update()
        elif LOG.exists():
            print('\n'.join(LOG.read_text(encoding='utf-8', errors='replace').splitlines()[-80:]))
    except Exception as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
