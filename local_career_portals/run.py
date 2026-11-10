#!/usr/bin/env python3
"""Run selected portal adapters locally without starting the app or importing jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from runtime_support import process_options, stop_process_tree
from common import newest_first, write_snapshot
from filters import apply_policy

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def environment(company):
    values = dict(os.environ)
    values["CAREER_PORTAL_TRANSPORT"] = company.get("transport", "browser")
    values["PYTHONPATH"] = os.pathsep.join([str(HERE), str(ROOT)] + ([values["PYTHONPATH"]] if values.get("PYTHONPATH") else []))
    return values


def command(company, max_jobs, output):
    cmd = [sys.executable, str(ROOT / company["existing_script"])]
    if company.get("url") and company["slug"] != "rubrik":
        cmd.append(company["url"])
    cmd.extend(company.get("args", []))
    cmd.extend(["--max-jobs", str(max_jobs), "--output", str(output)])
    return cmd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("companies", nargs="*", help="Company slugs; default runs all implemented companies")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--source-timeout", type=int, default=600)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.source_timeout < 1:
        parser.error("max-jobs must be nonnegative; source-timeout must be positive")
    inventory = json.loads((HERE / "companies.json").read_text())
    companies = {c["slug"]: c for c in inventory["companies"]}
    if args.list:
        for slug, company in companies.items():
            print(f"{slug}: {company['status']} — {company['note']}")
        print("Deferred: " + ", ".join(inventory["deferred_companies"]))
        return 0
    selected = args.companies or [slug for slug, c in companies.items() if c["status"] in {"reuse", "implemented"}]
    for slug in selected:
        if slug not in companies or companies[slug]["status"] not in {"reuse", "implemented"}:
            parser.error(f"Company is unavailable: {slug}; use --list")
    failed = False
    for slug in selected:
        company = companies[slug]
        output = HERE / "data" / f"{slug}_jobs.json"
        pending = output.with_suffix(".pending.json")
        cmd = command(company, args.max_jobs, pending)
        if args.dry_run:
            print(json.dumps(cmd))
            continue
        try:
            pending.unlink(missing_ok=True)
            process = subprocess.Popen(cmd, cwd=ROOT, env=environment(company), **process_options())
            try:
                code = process.wait(timeout=args.source_timeout)
            except subprocess.TimeoutExpired:
                stop_process_tree(process)
                raise
            if code:
                raise subprocess.CalledProcessError(code, cmd)
            snapshot = json.loads(pending.read_text())
            candidates = snapshot.pop("jobs")
            jobs = newest_first(apply_policy(candidates, company["filter_policy"]))
            if args.max_jobs:
                jobs = jobs[:args.max_jobs]
            snapshot.pop("jobs_fetched", None)
            snapshot["filter_policy"] = company["filter_policy"]
            snapshot["jobs_excluded_by_local_filters"] = len(candidates) - len(jobs)
            snapshot["local_ordering"] = "Available dates descending within fetched results; undated records preserve portal order"
            write_snapshot(output, jobs, **snapshot)
            print(f"{slug}: saved {len(jobs)} jobs", flush=True)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            failed = True
            print(f"{slug}: failed ({type(error).__name__}); previous snapshot retained", file=sys.stderr, flush=True)
        finally:
            pending.unlink(missing_ok=True)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
