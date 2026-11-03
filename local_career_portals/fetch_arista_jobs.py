#!/usr/bin/env python3
"""Arista's public SmartRecruiters India feed and full description sections."""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from fetch_smartrecruiters_jobs import description_html
from filters import engineering_title

API = "https://api.smartrecruiters.com/v1/companies/AristaNetworks/postings"


def eligible(item):
    return (item.get("location") or {}).get("country", "").casefold() == "in" and engineering_title({"title": item.get("name")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://www.arista.com/en/careers")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    summaries, offset = [], 0
    while True:
        payload = json.loads(read(API + "?" + urlencode({"country": "in", "limit": 100, "offset": offset}), args.timeout))
        if not isinstance(payload.get("content"), list) or "totalFound" not in payload:
            raise RuntimeError("Arista feed shape changed")
        summaries.extend({**item, "posted_date": item.get("releasedDate")} for item in payload["content"] if eligible(item))
        offset += len(payload["content"])
        if offset >= int(payload["totalFound"]):
            break
        if not payload["content"]:
            raise RuntimeError("Arista pagination ended prematurely")
        time.sleep(args.delay)
    summaries = newest_first(summaries)
    if args.max_jobs:
        summaries = summaries[:args.max_jobs]
    jobs = []
    for item in summaries:
        time.sleep(args.delay)
        detail = json.loads(read(API + "/" + item["id"], args.timeout))
        if (detail.get("company") or {}).get("identifier") != "AristaNetworks" or not eligible(detail):
            raise RuntimeError("Arista selected detail changed employer or country/role scope")
        description = description_html(detail)
        location = detail.get("location") or {}
        jobs.append({"id": detail["id"], "title": detail["name"], "company": "Arista Networks", "country": "India",
                     "department": (detail.get("department") or {}).get("label"),
                     "location": location.get("fullLocation") or f"{location.get('city', '')}, India",
                     "posted_date": detail.get("releasedDate"), "application_url": detail.get("postingUrl"),
                     "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
    write_snapshot(args.output, jobs, input_url=args.url, source=API, filters="Native country IN and conservative technical titles", sort="releasedDate descending before cap")
    print(f"Arista Networks: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
