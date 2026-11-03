#!/usr/bin/env python3
"""Automattic's embedded live job data; explicit India or worldwide hiring only."""
import argparse
import html
import json
from pathlib import Path
import re

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import engineering_title, in_india


def listings(document):
    match = re.search(r"const\s+ghJobsData\s*=\s*", document)
    if not match:
        raise RuntimeError("Automattic live listings data unavailable")
    jobs, _ = json.JSONDecoder().raw_decode(document[match.end():])
    if not isinstance(jobs, list) or not jobs:
        raise RuntimeError("Automattic global listings are empty or invalid")
    return jobs


def normalize(job):
    categories = (job.get("metadata") or {}).get("Category") or []
    if not engineering_title(job) or not set(categories).intersection({"Engineering", "Infrastructure"}):
        return None
    description = html.unescape(job.get("content") or "")
    text = plain_text(description)
    # Require a hiring statement addressed to applicants, rather than a generic
    # mention of global users, compensation or a fully remote company.
    evidence = re.search(r"[^.]*\b(?:hiring|recruiting|looking for)[^.]{0,180}\b(?:engineers|candidates|applicants|talent)\s+worldwide\b[^.]*", text, re.I)
    explicit_india = in_india({"location": job.get("location"), "locations": job.get("locations")})
    if not explicit_india and (job.get("location") or job.get("locations")):
        # A worldwide phrase must not override a narrower explicit role location.
        return None
    if not explicit_india and not evidence:
        return None
    if not all(job.get(key) for key in ("id", "title", "href")) or not description:
        raise RuntimeError("Automattic selected job missing required fields")
    return {"id": str(job["id"]), "title": job["title"], "company": "Automattic",
            "department": " | ".join(categories), "country": "India",
            "location": job.get("location") if explicit_india else "Remote, Worldwide (India eligible)",
            "source_location": job.get("location"),
            "location_scope": "Explicit India location" if explicit_india else "Worldwide hiring statement; India eligible, not India-specific",
            "location_evidence": None if explicit_india else evidence.group(0).strip(),
            "application_url": job["href"], "posted_date": job.get("first_published") or job.get("datePosted"),
            "updated_date": job.get("updated_at"),
            "jobDescriptionHtml": description, "jobDescriptionText": text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("Invalid limits")
    source_jobs = listings(read(args.url, args.timeout))
    jobs = newest_first([result for job in source_jobs if (result := normalize(job)) is not None])
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, source=args.url, complete=True,
                   global_results=len(source_jobs),
                   filters="Engineering/Infrastructure category and technical titles; explicit India or role-specific worldwide hiring statement",
                   limitations="Unknown geography is excluded; worldwide roles retain hiring evidence; no WordPress page dates used as job publication dates",
                   sort="Available publication dates descending; undated roles preserve portal order")
    print(f"Automattic: wrote {len(jobs)} India-eligible engineering jobs")


if __name__ == "__main__":
    main()
