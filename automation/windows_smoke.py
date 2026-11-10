"""CI-only native Windows server smoke test. No external job/LLM requests."""
import json
import os
from pathlib import Path
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.name != 'nt' or os.getenv('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('CI-only check; refuses to touch a personal installation.')
    from automation import windows_service as service
    config = ROOT / '.env'
    if config.exists():
        raise RuntimeError('Refusing to replace an existing .env')
    config.write_text('DATABASE_URL=sqlite:///data/ci-smoke.db\nPORTAL_SCHEDULER_ENABLED=false\nOPENAI_BATCH_SUBMISSION_ENABLED=false\n', encoding='utf-8')
    try:
        service.start()
        pid = service.running()['pid']
        service.start()
        assert service.running()['pid'] == pid, 'Duplicate instance was started'
        with urlopen('http://127.0.0.1:8000/api/jobs/sources/status', timeout=5) as response:
            state = json.load(response)
        assert not state['schedule_enabled'] and not state['is_running']
        assert not (ROOT / 'data/portal_schedule.json').exists(), 'Startup triggered fetching'
        with urlopen('http://127.0.0.1:8000/', timeout=5) as response:
            html = response.read().decode('utf-8')
        assert 'Saved jobs' in html and 'Fetch jobs now' in html
        service.stop()
        assert not service.running(), 'Service did not stop'
        print('Native Windows service start, health, duplicate prevention, manual-only collection, and graceful stop passed.')
    finally:
        service.stop()
        config.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
