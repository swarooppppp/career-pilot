#!/usr/bin/env python3
"""Fetch Postman Engineering openings in Bangalore and Hyderabad."""
from __future__ import annotations

import argparse
import html
import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FEED = "https://www.postman.com/_mk-www-next/api-cache/careers-jobs.json"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilot/1.0)"


def read_json(url: str, timeout: int) -> dict:
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}), timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Postman returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Postman Careers: {exc.reason}") from exc


def workday_detail(url: str, timeout: int) -> str:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    tenant = parsed.netloc.split(".", 1)[0]
    site, *path = [segment for segment in parsed.path.split("/") if segment]
    endpoint = f"https://{parsed.netloc}/wday/cxs/{tenant}/{site}/" + "/".join(path)
    return str(read_json(endpoint, timeout).get("jobPostingInfo", {}).get("jobDescription") or "")


def fetch_jobs(max_jobs: int, timeout: int, skip_ids: set[str], locations: set[str]) -> list[dict]:
    jobs = []
    for summary in read_json(FEED, timeout).get("jobs", []):
        job_id, location = str(summary.get("id") or ""), str(summary.get("location") or "")
        if (summary.get("department") != "Engineering" or not any(city.lower() in location.lower() for city in locations)
                or not job_id or job_id in skip_ids):
            continue
        description_html = workday_detail(str(summary["url"]), timeout)
        jobs.append({
            "id": job_id, "title": summary.get("title", ""), "company": "Postman", "location": location,
            "department": summary.get("department", ""), "posted_date": summary.get("updated_at", ""),
            "application_url": summary["url"], "jobDescriptionHtml": description_html,
            "jobDescriptionText": " ".join(re.sub(r"<[^>]+>", " ", html.unescape(description_html)).split()),
        })
        if max_jobs and len(jobs) >= max_jobs:
            break
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--location", action="append", default=["Bangalore", "Hyderabad"])
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("postman_jobs.json"))
    args = parser.parse_args()
    try:
        jobs = fetch_jobs(args.max_jobs, args.timeout, set(args.skip_job_id), set(args.location))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr); return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"source": "Postman public careers feed", "jobs": jobs}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Postman jobs to {args.output}", file=sys.stderr); return 0


if __name__ == "__main__":
    raise SystemExit(main())
