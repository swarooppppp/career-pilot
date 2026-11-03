#!/usr/bin/env python3
"""Fetch Rubrik Engineering directly from its public Greenhouse feed."""
import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

from common import newest_first, plain_text, write_snapshot
from filters import in_india

URL = "https://www.rubrik.com/company/careers/departments/engineering"
API = "https://boards-api.greenhouse.io/v1/boards/rubrik/jobs?content=true"


def normalize(jobs, location=""):
    results = []
    for job in jobs:
        departments = [d.get("name", "") for d in job.get("departments", [])]
        loc = (job.get("location") or {}).get("name", "")
        matches_location = in_india({"location": loc, "offices": job.get("offices", [])}) if location.casefold() == "india" else not location or location.casefold() in loc.casefold()
        if "Engineering" not in departments or not matches_location:
            continue
        if not all(job.get(k) for k in ("id", "title", "absolute_url", "content")):
            continue
        results.append({"id": str(job["id"]), "title": job["title"], "company": "Rubrik",
                        "location": loc, "offices": job.get("offices", []), "department": "Engineering", "application_url": job["absolute_url"],
                        "posted_date": job.get("first_published"), "updated_date": job.get("updated_at"),
                        "jobDescriptionHtml": job["content"], "jobDescriptionText": plain_text(job["content"])})
    return newest_first(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", default="", help="Optional location substring; default preserves the supplied global engineering page")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "data/rubrik_jobs.json")
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-jobs must be nonnegative and timeout positive")
    with urlopen(Request(API, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}), timeout=args.timeout) as response:
        payload = json.load(response)
    if not isinstance(payload.get("jobs"), list):
        raise RuntimeError("Rubrik feed is missing its jobs list")
    jobs = normalize(payload["jobs"], args.location)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, source=API, input_url=URL, sort="first publication descending; update date fallback")
    print(f"Rubrik: wrote {len(jobs)} jobs to {args.output}")


if __name__ == "__main__":
    main()
