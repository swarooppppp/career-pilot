#!/usr/bin/env python3
"""Collect a fresh, isolated sample and combined per-company JSON report."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import time
from zoneinfo import ZoneInfo

from common import newest_first, timestamp, write_snapshot
from filters import apply_policy
from run import command, environment, HERE


def classification(text):
    lowered = text.lower()
    if '429' in lowered or 'cooldown' in lowered or 'rate-limit' in lowered:
        return 'rate_limited'
    if any(x in lowered for x in ['403', 'verification', 'challenge']):
        return 'access_blocked'
    if re.search(r"timeouterror|timed out|timeout \d|exceeded \d+s", lowered):
        return 'timeout'
    return 'fetch_failed'


def descendants(pid):
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid='], capture_output=True, text=True)
    pairs = [tuple(map(int, line.split())) for line in result.stdout.splitlines() if len(line.split()) == 2]
    found = {pid}
    while True:
        children = {child for child, parent in pairs if parent in found}
        if children <= found:
            return found - {pid}
        found.update(children)


def stop(process):
    # Only this worker's process tree, including its Playwright Chromium.
    children = descendants(process.pid)
    for pid in children:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        for pid in children:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def fetch(company, directory, limit, timeout):
    slug = company['slug']
    raw = directory / (slug + '.raw.json')
    output = directory / (slug + '_jobs.json')
    log = directory / (slug + '.log')
    started = time.monotonic()
    report = {'company': company['company'], 'slug': slug, 'status': 'failed', 'jobs_count': 0,
              'filter_policy': company['filter_policy'], 'source_url': company.get('url'),
              'source_note': company['note'], 'jobs': []}
    try:
        # Bulk boards include descriptions in one request: sort all matches
        # before imposing the sample cap, without extra detail requests.
        source_limit = 0 if Path(company['existing_script']).name == 'fetch_greenhouse_jobs.py' else limit
        with log.open('w') as handle:
            process = subprocess.Popen(command(company, source_limit, raw), stdout=handle, stderr=subprocess.STDOUT,
                                       cwd=HERE.parent, start_new_session=True, env=environment(company))
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                stop(process)
                report.update(error_type='timeout', error=f'Source exceeded {timeout}s sample deadline')
                return report
        text = log.read_text()
        if code:
            report.update(error_type=classification(text), error=text[-2500:])
            return report
        snapshot = json.loads(raw.read_text())
        candidates = snapshot.pop('jobs')
        jobs = newest_first(apply_policy(candidates, company['filter_policy']))[:limit]
        dated = sum(timestamp(job.get('posted_date') or job.get('updated_date')) != float('-inf') for job in jobs)
        partial = snapshot.get('complete') is False
        report.update(status='partial' if partial else 'ok' if jobs else 'empty', jobs_count=len(jobs),
                      jobs=jobs, dated_jobs=dated, undated_jobs=len(jobs) - dated,
                      candidates_fetched=len(candidates), excluded_by_filters=len(candidates) - len(apply_policy(candidates, company['filter_policy'])),
                      ordering='Available posting dates descending, update-date fallback; undated entries preserve portal order',
                      ordering_limitations='Source may expose update dates only or cap candidates before sorting; see source_note',
                      source_metadata=snapshot)
        if partial:
                reason = snapshot.get('stopped_reason')
                report['error_type'] = 'incomplete_listing' if reason in {'listing_page_limit', 'inconsistent_listing_count'} else classification(str(reason) + text)
        write_snapshot(output, jobs, source_metadata=snapshot, filter_policy=company['filter_policy'])
        report['snapshot_file'] = str(output.relative_to(HERE.parent))
        return report
    except Exception as error:
        report.update(error_type='fetch_failed', error=f'{type(error).__name__}: {error}')
        return report
    finally:
        report['elapsed_seconds'] = round(time.monotonic() - started, 2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--max-jobs', type=int, default=50)
    parser.add_argument('--workers', type=int, default=3)
    parser.add_argument('--source-timeout', type=int, default=180)
    args = parser.parse_args()
    if min(args.max_jobs, args.workers, args.source_timeout) < 1:
        parser.error('Limits must be positive')
    inventory = json.loads((HERE / 'companies.json').read_text())
    companies = [c for c in inventory['companies'] if c['status'] in {'reuse', 'implemented'}]
    run_id = datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y%m%d_%H%M%S')
    directory = HERE / 'data' / 'samples' / run_id
    directory.mkdir(parents=True, exist_ok=False)
    combined = directory / 'all_companies_top50.json'
    document = {'generated_at': datetime.now(timezone.utc).isoformat(), 'run_status': 'running',
                'max_jobs_per_company': args.max_jobs, 'fresh_fetches_only': True,
                'filters': 'Engineering and India, preserving narrower company filters',
                'limitations': ['Fewer than 50 matching jobs may exist.', 'Unavailable dates are not invented.',
                                'Some adapters only sort a bounded subset or provide update dates rather than posting dates.'],
                'excluded': [{'company': c['company'], 'reason': c['status']} for c in inventory['companies'] if c['status'] not in {'reuse', 'implemented'}]
                            + [{'company': name, 'reason': 'deferred'} for name in inventory['deferred_companies']],
                'companies': []}
    def save():
        document['total_jobs'] = sum(c['jobs_count'] for c in document['companies'])
        temporary = combined.with_suffix('.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(combined)
    save()
    print('OUTPUT ' + str(combined), flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(fetch, c, directory, args.max_jobs, args.source_timeout): c for c in companies}
        for future in as_completed(futures):
            result = future.result()
            document['companies'].append(result)
            save()
            print(f"{len(document['companies'])}/{len(companies)} {result['slug']}: {result['status']} {result['jobs_count']} jobs {result.get('error_type', '')}", flush=True)
    order = {c['slug']: i for i, c in enumerate(companies)}
    document['companies'].sort(key=lambda c: order[c['slug']])
    document['run_status'] = 'complete'
    document['completed_at'] = datetime.now(timezone.utc).isoformat()
    save()
    print('COMPLETE ' + str(combined), flush=True)


if __name__ == '__main__':
    main()
