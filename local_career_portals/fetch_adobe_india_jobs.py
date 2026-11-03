#!/usr/bin/env python3
"""Reuse Adobe's parser, filtering and sorting listings before detail hydration."""
import argparse
import importlib.util
from pathlib import Path
import time

from common import timestamp, write_snapshot
from filters import engineering_title, in_india

SPEC = importlib.util.spec_from_file_location("adobe_existing_parser", Path(__file__).resolve().parents[1] / "career portal scripts/fetch_adobe_jobs.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=adapter.DEFAULT_URL)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    first = adapter.fetch_search_page(adapter.page_url(args.url, 0), args.timeout)
    summaries = list(first.get("data", {}).get("jobs", []))
    page_size = int(first.get("hits") or len(summaries) or 10)
    total = int(first.get("totalHits") or len(summaries))
    pages = min(args.max_pages, (total + page_size - 1) // page_size)
    for number in range(1, pages):
        time.sleep(args.delay)
        summaries.extend(adapter.fetch_search_page(adapter.page_url(args.url, number * page_size), args.timeout).get("data", {}).get("jobs", []))
    summaries = list({str(j.get("reqId") or j.get("jobId")): j for j in summaries}.values())
    selected = [j for j in summaries if engineering_title(j) and in_india({**j, "locations": j.get("multi_location")})]
    selected.sort(key=lambda j: timestamp(j.get("postedDate")), reverse=True)
    if args.max_jobs:
        selected = selected[:args.max_jobs]
    jobs = []
    for summary in selected:
        ident = str(summary.get("reqId") or summary.get("jobId"))
        print(f"Adobe India detail {len(jobs) + 1}/{len(selected)}: {ident}", flush=True)
        detail = adapter.fetch_detail(ident, summary["title"], args.timeout)
        job = adapter.normalise_job(summary, detail)
        if job:
            job["locations"] = detail.get("multi_location") or summary.get("multi_location") or []
            jobs.append(job)
        time.sleep(args.delay)
    complete = len(summaries) >= total
    reason = None if complete else "listing_page_limit" if pages * page_size < total else "inconsistent_listing_count"
    write_snapshot(args.output, jobs, source="Adobe public server-rendered data", input_url=args.url,
                   complete=complete, stopped_reason=reason,
                   listing_candidates=len(summaries), total_listing_results=total,
                   sort="Posting date descending after Engineering/India filtering, before detail hydration")
    print(f"Adobe: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
