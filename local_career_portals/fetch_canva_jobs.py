#!/usr/bin/env python3
"""Canva's current public SmartRecruiters feed, restricted to India engineering."""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from fetch_smartrecruiters_jobs import description_html
from filters import engineering_title

API = "https://api.smartrecruiters.com/v1/companies/Canva/postings"


def selected(item):
    return (item.get("location") or {}).get("country", "").casefold() == "in" and engineering_title({"title": item.get("name")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://www.lifeatcanva.com/en/jobs/")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    offset, summaries = 0, []
    while True:
        payload = json.loads(read(API + "?" + urlencode({"country": "in", "limit": 100, "offset": offset}), args.timeout))
        if not isinstance(payload.get("content"), list) or "totalFound" not in payload:
            raise RuntimeError("Canva listing response shape changed")
        summaries.extend({**item, "posted_date": item.get("releasedDate")} for item in payload["content"] if selected(item))
        offset += len(payload["content"])
        if offset >= int(payload["totalFound"]):
            break
        if not payload["content"]:
            raise RuntimeError("Canva pagination incomplete")
        time.sleep(args.delay)
    if not summaries:
        health = json.loads(read(API + "?limit=1", args.timeout))
        if not health.get("totalFound"):
            raise RuntimeError("Canva board is globally empty; cannot verify a valid India-empty result")
    summaries = newest_first(summaries)
    if args.max_jobs:
        summaries = summaries[:args.max_jobs]
    jobs = []
    for summary in summaries:
        detail = json.loads(read(API + "/" + summary["id"], args.timeout))
        if (detail.get("company") or {}).get("identifier", "").casefold() != "canva" or not selected(detail):
            raise RuntimeError("Canva detail company or filters changed")
        description = description_html(detail)
        loc = detail.get("location") or {}
        jobs.append({"id": detail["id"], "title": detail["name"], "company": "Canva", "country": "India",
                     "location": loc.get("fullLocation") or f"{loc.get('city', '')}, India",
                     "application_url": detail.get("postingUrl"), "posted_date": detail.get("releasedDate"),
                     "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
        time.sleep(args.delay)
    write_snapshot(args.output, jobs, source=API, input_url=args.url, filters="India country and conservative engineering titles", sort="releasedDate descending before detail hydration")
    print(f"Canva: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
