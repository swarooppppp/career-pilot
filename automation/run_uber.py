#!/usr/bin/env python3
"""Bounded Uber-only supervisor. Never sources .env as shell code."""
import argparse
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.automation/uber'


def profile_browsers(profile):
    """Exact dedicated profile, main Chromium only; Playwright uses its own PGID."""
    rows = subprocess.check_output(['/bin/ps', '-axo', 'pid=,pgid=,command='], text=True)
    found = []
    for row in rows.splitlines():
        fields = row.strip().split(None, 2)
        if len(fields) != 3:
            continue
        pid, pgid, command = fields
        marker = "--user-data-dir=" + str(profile) + " --remote-debugging-pipe"
        if marker in command and ' --type=' not in command and int(pid) == int(pgid):
            found.append(int(pid))
    return found


def hide_browser(group, profile, attempted):
    try:
        for pid in profile_browsers(profile):
            if pid in attempted:
                continue
            script = ('tell application "System Events" to set visible of '
                      '(every application process whose unix id is %s) to false' % pid)
            attempted.add(pid)
            result = subprocess.run(['/usr/bin/osascript', '-e', script],
                                    capture_output=True, timeout=3)
            logging.info('browser_hide pid=%s status=%s', pid, result.returncode)
            if result.returncode:
                logging.warning('Browser hiding denied; check Automation/Accessibility permissions')
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        logging.warning("Browser hiding unavailable exception=%s; check macOS permissions", type(error).__name__)
        if not attempted:
            logging.warning('Browser hiding unavailable; execution continues')
            attempted.add(-1)


def cleanup_profile(profile):
    # Recover dedicated browsers left after crashes; never match a normal Chrome profile.
    try:
        for pid in profile_browsers(profile):
            os.killpg(pid, signal.SIGTERM)
        time.sleep(.3)
        for pid in profile_browsers(profile):
            os.killpg(pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        logging.warning('Could not inspect/clean dedicated browser processes')


def terminate_group(child):
    # Give asyncio/Playwright time to close the persistent context, then reap leftovers.
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        child.poll()
        try:
            os.killpg(child.pid, 0)
        except ProcessLookupError:
            break
        time.sleep(.2)
    else:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    child.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout', type=float, default=300)
    parser.add_argument('--show-browser', action='store_true')
    parser.add_argument('--smoke-test', action='store_true', help='Use local fixture through the real fetcher, separate profile/output')
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('timeout must be positive')
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(STATE / 'history.log', maxBytes=2_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()])
    # Never unlink the lock: flock is released by the kernel on exit/crash.
    with (STATE / 'run.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logging.info('status=skipped reason=already_running')
            return 0
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        from dotenv import dotenv_values
        config = {**dotenv_values(ROOT / '.env'), **os.environ}
        url = config.get('UBER_JOBS_URL')
        if not url and not args.smoke_test:
            logging.error('UBER_JOBS_URL missing')
            return 1
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        diagnostics = STATE / 'diagnostics' / run_id
        diagnostics.mkdir(parents=True, mode=0o700)
        profile = STATE / ('smoke-profile' if args.smoke_test else 'profile')
        cleanup_profile(profile)
        command = [sys.executable, str(Path(__file__).resolve()), '--worker'] if args.smoke_test else [
            sys.executable, str(ROOT / 'career portal scripts/fetch_uber_jobs.py'), url,
            '--headed', '--profile', str(profile), '--diagnostics', str(diagnostics),
            '--max-pages', config.get('UBER_MAX_PAGES', '10'),
            '--max-jobs', config.get('UBER_MAX_JOBS', '50'),
            '--timeout', config.get('UBER_TIMEOUT', '30'),
            '--output', str(ROOT / 'data/uber_jobs.json')]
        started = time.monotonic()
        stop = []
        old = {sig: signal.signal(sig, lambda signum, frame: stop.append(signum))
               for sig in (signal.SIGTERM, signal.SIGINT)}
        child = None
        status = 'failed'
        logging.info('start run=%s smoke=%s', run_id, args.smoke_test)
        try:
            # The inherited lock keeps another supervisor out until the worker exits.
            with (diagnostics / 'worker.log').open('w') as output:
                child = subprocess.Popen(command, cwd=ROOT, start_new_session=True,
                                         stdout=output, stderr=subprocess.STDOUT,
                                         pass_fds=(lock.fileno(),), env={**os.environ, 'PYTHONUNBUFFERED': '1', 'UBER_SUPERVISOR_PID': str(os.getpid())})
                attempted = set()
                while child.poll() is None:
                    if stop or time.monotonic() - started >= args.timeout:
                        status = 'cancelled' if stop else 'timeout'
                        break
                    if not args.show_browser:
                        hide_browser(child.pid, profile, attempted)
                    time.sleep(.5)
                else:
                    status = 'success' if child.returncode == 0 else 'failed'
        except Exception as error:
            # No exception text: Playwright errors may embed URLs or page content.
            logging.error('supervisor exception=%s', type(error).__name__)
        finally:
            if child:
                terminate_group(child)
            cleanup_profile(profile)
            for sig, previous in old.items():
                signal.signal(sig, previous)
            elapsed = time.monotonic() - started
            record = dict(run=run_id, status=status, duration_seconds=round(elapsed, 2),
                          ended=datetime.now(timezone.utc).isoformat())
            (diagnostics / 'status.json').write_text(json.dumps(record, indent=2))
            logging.info('end run=%s status=%s duration=%.2fs', run_id, status, elapsed)
        return 0 if status == 'success' else 1


async def smoke_worker():
    """Exercise actual Uber fetch/normalization against a deterministic browser fixture."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('uber', ROOT / 'career portal scripts/fetch_uber_jobs.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Persistent launch creates an initial page before returning: install routing on context.
    from playwright.async_api import BrowserType
    launch = BrowserType.launch_persistent_context
    async def fixture_launch(self, *a, **kw):
        context = await launch(self, *a, **kw)
        async def route(request):
            if '/api/jobs/search/' in request.request.url:
                await request.fulfill(json={'jobs': []})
            else:
                await request.fulfill(content_type='text/html', body='<a class="js-view-job">Fixture</a>')
        await context.route('https://jobs.uber.com/**', route)
        import asyncio
        await asyncio.sleep(8)
        return context
    BrowserType.launch_persistent_context = fixture_launch
    try:
        pages = await module.fetch_pages_in_browser('https://jobs.uber.com/en/jobs/', 1, 10000, True, STATE / 'smoke-profile')
        assert pages == [{'jobs': []}], pages
        print('SMOKE_OK: real headed persistent browser, navigation, selector, API fetch, context cleanup')
    finally:
        BrowserType.launch_persistent_context = launch


if __name__ == '__main__':
    if sys.argv[1:] == ['--worker']:
        import asyncio
        # asyncio.run cancels the task on SIGINT, unwinding the fetcher's finally.
        signal.signal(signal.SIGTERM, lambda *_: os.kill(os.getpid(), signal.SIGINT))
        asyncio.run(smoke_worker())
    else:
        sys.exit(main())
