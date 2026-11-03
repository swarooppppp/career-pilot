#!/usr/bin/env python3
"""Dynatrace's native Coveo career search and JobPosting detail data."""
import argparse
import html
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read

API = "https://www.dynatrace.com/api/coveo/search/"
FIELDS = ["team", "office_locations", "country", "department", "employment_type", "job_id"]


def search(timeout, filtered=False, offset=0):
    payload = {"q": None, "numberOfResults": 1000, "firstResult": offset, "wildcards": True,
               "fieldsToInclude": FIELDS,
               "facets": [{"field": field, "numberOfValues": 1000,
                           "currentValues": [{"state": "selected", "value": value}] if filtered else []}
                          for field, value in [("country", "India"), ("team", "Engineering")]]}
    request = Request(API, data=json.dumps(payload).encode(), headers={
        "User-Agent": "Mozilla/5.0", "Accept": "application/json", "Content-Type": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result.get("results"), list) or not isinstance(result.get("totalCount"), int):
        raise RuntimeError("Dynatrace search response shape changed")
    return result


def posting(document):
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, re.I | re.S):
        try:
            payload = json.loads(raw)
        except ValueError:
            continue
        stack = [payload]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                kind = value.get("@type")
                if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                    return value
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    raise RuntimeError("Dynatrace full JobPosting data unavailable")


def normalize(item, detail):
    raw = item.get("raw") or {}
    if "India" not in (raw.get("country") or []) or "Engineering" not in (raw.get("team") or []):
        raise RuntimeError("Dynatrace returned a role outside native India/Engineering filters")
    description = detail.get("description") or ""
    identifier = detail.get("identifier") or {}
    ident = identifier.get("value") if isinstance(identifier, dict) else identifier
    url = detail.get("url") or item.get("uri")
    if not description or not url or not ident or not detail.get("title"):
        raise RuntimeError("Dynatrace selected job missing required full detail fields")
    return {"id": str(ident), "title": detail["title"], "company": "Dynatrace",
            "department": "Engineering", "source_departments": raw.get("department"), "country": "India",
            "location": ", ".join([*(raw.get("office_locations") or []), "India"]),
            "application_url": url, "posted_date": detail.get("datePosted"),
            "jobDescriptionHtml": "<p>" + html.escape(description).replace("\n", "<br>") + "</p>",
            "jobDescriptionText": plain_text(description)}


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
    discovery = search(args.timeout)
    if not discovery["totalCount"]:
        raise RuntimeError("Dynatrace global index is empty; cannot verify filtered results")
    teams = next((f.get("values", []) for f in discovery.get("facets", []) if f.get("field") == "team"), [])
    if not any(value.get("value") == "Engineering" for value in teams):
        raise RuntimeError("Dynatrace Engineering taxonomy changed")
    summaries, seen, offset = [], set(), 0
    while True:
        time.sleep(args.delay)
        payload = search(args.timeout, filtered=True, offset=offset)
        for item in payload["results"]:
            uri = item.get("uri")
            if not uri or uri in seen:
                raise RuntimeError("Dynatrace incomplete or repeated search results")
            seen.add(uri)
            summaries.append(item)
        offset += len(payload["results"])
        if offset >= payload["totalCount"]:
            break
        if not payload["results"]:
            raise RuntimeError("Dynatrace pagination ended early")
    jobs = []
    for item in summaries:
        time.sleep(args.delay)
        jobs.append(normalize(item, posting(read(item["uri"], args.timeout))))
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, source=API, complete=True,
                   global_results=discovery["totalCount"], total_filtered_results=len(summaries),
                   filters="Native country=India and team=Engineering; verified search metadata",
                   sort="JobPosting.datePosted descending before cap; index dates are not publication dates")
    print(f"Dynatrace: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
