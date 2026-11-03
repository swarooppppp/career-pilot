#!/usr/bin/env python3
"""Reuse Workday transport with explicit Engineering/India detail validation."""
import argparse
import importlib.util
from pathlib import Path
import time

from common import newest_first, plain_text, write_snapshot
from filters import engineering_title, in_india

SPEC = importlib.util.spec_from_file_location("workday_existing_transport", Path(__file__).resolve().parents[1] / "career portal scripts/fetch_workday_jobs.py")
workday = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workday)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    host, tenant, site, query = workday.site_config(args.url)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    summaries, total = [], 0
    for number in range(args.max_pages):
        page = workday.request_json(base + "/jobs", workday.search_payload(query, 20, number * 20), args.timeout)
        if not isinstance(page.get("jobPostings"), list):
            raise RuntimeError("Workday response is missing jobPostings")
        total = int(page["total"])
        summaries.extend(j for j in page["jobPostings"] if engineering_title(j))
        if (number + 1) * 20 >= total or not page["jobPostings"]:
            break
        time.sleep(args.delay)
    jobs = []
    for summary in summaries:
        path = summary["externalPath"]
        detail = workday.request_json(base + path, None, args.timeout).get("jobPostingInfo", {})
        locations = [detail.get("location") or summary.get("locationsText", "")] + (detail.get("additionalLocations") or [])
        country = (detail.get("country") or {}).get("descriptor", "")
        if not in_india({"locations": locations, "country": country}):
            continue
        description = detail.get("jobDescription") or ""
        if not description:
            raise RuntimeError("Workday full description unavailable")
        jobs.append({"id": detail.get("jobReqId") or (summary.get("bulletFields") or [detail.get("id")])[0],
                     "title": detail.get("title") or summary["title"], "company": "CrowdStrike", "location": " | ".join(locations),
                     "country": country, "posted_date": detail.get("startDate"),
                     "application_url": detail.get("externalUrl") or f"https://{host}/{site}{path}",
                     "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
        time.sleep(args.delay)
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, total_results=total, date_basis="Workday startDate; absent dates retained as unknown")
    print(f"CrowdStrike: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
