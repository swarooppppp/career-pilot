#!/usr/bin/env python3
"""Fetch D. E. Shaw India's public, embedded technical job records."""
import argparse
from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import in_india

DEPARTMENTS = {"Core Tech", "Front Office Tech", "Quality and Test Engineering", "Systems"}


def normalize(document):
    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', document, re.S)
    if not match:
        raise RuntimeError("D. E. Shaw public job data unavailable")
    props = json.loads(match.group(1))["props"]["pageProps"]
    if props.get("jobsFetchingError") or not isinstance(props.get("regularJobs"), list):
        raise RuntimeError("D. E. Shaw returned incomplete job data")
    jobs = []
    for record in props["regularJobs"]:
        data = record["data"]
        meta = data.get("jobMetadata") or {}
        department = (data.get("department") or {}).get("name", "")
        if not data.get("activeOnJobsListing") or meta.get("isExploratory") or department not in DEPARTMENTS:
            continue
        locations = [x["name"] for x in meta.get("jobLocations", [])]
        if not in_india({"locations": locations}):
            continue
        description = data.get("jobDescription") or {}
        parts = []
        for title, fields in (("Summary", ["websiteDescription"]), ("Responsibilities", ["responsibilitiesHtml", "responsibilities"]),
                              ("Qualifications", ["peopleWeAreLookingForHtml", "peopleWeAreLookingForStr", "peopleWeAreLookingFor"])):
            value = next((description.get(key) for key in fields if description.get(key)), "")
            if isinstance(value, list):
                value = "\n".join(str(x) for x in value)
            if value:
                parts.append(f"<h2>{title}</h2>" + (value if "<" in value else "<p>" + html.escape(value) + "</p>"))
        if not parts:
            raise RuntimeError("D. E. Shaw technical job lacks description")
        jobs.append({"id": str(data["id"]), "title": data["displayName"], "company": "D. E. Shaw",
                     "department": department, "location": " | ".join(locations), "country": "India",
                     "application_url": "https://www.deshawindia.com/careers/" + data["jobUrl"].lower(),
                     "posted_date": None, "jobDescriptionHtml": "\n".join(parts), "jobDescriptionText": plain_text("\n".join(parts))})
    return jobs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://www.deshawindia.com/careers")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("Invalid limits")
    jobs = normalize(read(args.url, args.timeout))
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, filters="Native technical departments and India; excludes exploratory applications",
                   sort="Posting dates unavailable; source order retained")
    print(f"D. E. Shaw: wrote {len(jobs)} technical India jobs")


if __name__ == "__main__":
    main()
