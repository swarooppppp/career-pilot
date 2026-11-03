#!/usr/bin/env python3
"""ThoughtSpot's current career listing API and Rippling server-rendered details."""
import argparse
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import engineering_title, in_india

API = "https://www.thoughtspot.com/api/getCareersListing"


def eligible(job):
    locations = job.get("locations") or []
    india = any(value.get("countryCode") == "IN" or value.get("country") == "India"
                or in_india({"location": value.get("name")}) for value in locations)
    department = (job.get("department") or {}).get("name", "")
    if re.search(r"sales|customer|marketing|support", department, re.I):
        return False
    # Engineering and Product Management is a mixed department. Keep technical
    # leads but do not accept product/program managers just for this membership.
    technical = engineering_title(job) or re.search(r"\b(?:tech|technical) lead manager\b", job.get("name", ""), re.I)
    return bool(india and technical)


def detail_data(document):
    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', document, re.I | re.S)
    if not match:
        raise RuntimeError("ThoughtSpot Rippling detail data unavailable")
    try:
        job = json.loads(match.group(1))["props"]["pageProps"]["apiData"]["jobPost"]
    except (ValueError, KeyError, TypeError) as error:
        raise RuntimeError("ThoughtSpot Rippling detail shape changed") from error
    if not isinstance(job, dict):
        raise RuntimeError("ThoughtSpot Rippling job data unavailable")
    return job


def normalize(summary, detail):
    if detail.get("companyName") != "ThoughtSpot" or detail.get("uuid") != summary.get("id"):
        raise RuntimeError("Unexpected ThoughtSpot job identity")
    if detail.get("unlistedFromSearch") is True:
        return None
    if not eligible(summary):
        return None
    sections = detail.get("description") or {}
    if not isinstance(sections, dict) or not sections.get("role"):
        raise RuntimeError("ThoughtSpot full role description unavailable")
    description = "\n".join(value for value in sections.values() if isinstance(value, str) and value.strip())
    structured = detail.get("jsonLd") or {}
    if isinstance(structured, str):
        try:
            structured = json.loads(structured)
        except ValueError:
            structured = {}
    posted = structured.get("datePosted") if isinstance(structured, dict) else None
    return {"id": str(summary["id"]), "title": detail.get("name") or summary["name"], "company": "ThoughtSpot",
            "department": (summary.get("department") or {}).get("name"), "country": "India",
            "locations": [v["name"] for v in summary["locations"] if v.get("name")],
            "source_locations": summary["locations"], "application_url": summary["url"],
            "posted_date": posted or detail.get("datePosted") or detail.get("publishedAt"),
            "source_created_date": detail.get("createdOn"),
            "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    payload = json.loads(read(API, args.timeout))
    if not isinstance(payload.get("data"), list) or not payload["data"]:
        raise RuntimeError("ThoughtSpot global listing API is empty or changed")
    seen, jobs = set(), []
    for summary in payload["data"]:
        if not eligible(summary) or summary.get("id") in seen:
            continue
        url = summary.get("url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "ats.rippling.com" or not parsed.path.startswith("/thoughtspot/jobs/"):
            raise RuntimeError("Unexpected ThoughtSpot detail URL")
        seen.add(summary["id"])
        time.sleep(args.delay)
        job = normalize(summary, detail_data(read(url, args.timeout)))
        if job:
            jobs.append(job)
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, source=API, complete=True,
                   global_results=len(payload["data"]), selected_detail_requests=len(seen),
                   filters="Structured India locations; engineering/MTS/technical lead titles; sales/customer departments excluded",
                   sort="Explicit publication dates if supplied; otherwise preserve portal order",
                   limitations="Rippling createdOn is stored separately; not treated as a publication date")
    print(f"ThoughtSpot: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
