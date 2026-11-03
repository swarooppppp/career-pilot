#!/usr/bin/env python3
"""Public Docusign careers JSON, including full description fields."""
import argparse
import html
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import engineering_title, in_india

API = "https://careers.docusign.com/api/jobs"


def normalize(data):
    if data.get("internal") or not data.get("searchable", True) or not engineering_title(data):
        return None
    if str(data.get("country_code") or "").casefold() != "in" and not in_india({"country": data.get("country"), "location": data.get("full_location")}):
        return None
    description = data.get("description") or ""
    if not description:
        raise RuntimeError("Docusign selected role is missing full description")
    sections = [("Description", description)]
    for key in ("responsibilities", "qualifications"):
        value = data.get(key) or ""
        if value and plain_text(value) not in plain_text(description):
            sections.append((key.title(), value))
    description_html = "\n".join(f"<h2>{name}</h2>" + (value if "<" in value else "<p>" + html.escape(value) + "</p>") for name, value in sections)
    return {"id": str(data["req_id"]), "title": data["title"], "company": "Docusign",
            "source_categories": data.get("categories"), "country": "India",
            "location": data.get("full_location") or f"{data.get('city', '')}, India",
            "application_url": (data.get("meta_data") or {}).get("canonical_url") or f"https://careers.docusign.com/careers-home/jobs/{data['req_id']}",
            "apply_url": data.get("apply_url"), "posted_date": data.get("posted_date"), "updated_date": data.get("update_date"),
            "jobDescriptionHtml": description_html, "jobDescriptionText": plain_text(description_html)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default="https://careers.docusign.com/careers-home/jobs")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    jobs, seen, candidate_ids, total = [], set(), set(), 0
    for number in range(1, args.max_pages + 1):
        payload = json.loads(read(API + "?" + urlencode({"country": "India", "limit": 100, "page": number}), args.timeout))
        if not isinstance(payload.get("jobs"), list) or "totalCount" not in payload:
            raise RuntimeError("Docusign listing response shape changed")
        total = int(payload["totalCount"])
        before = len(candidate_ids)
        for entry in payload["jobs"]:
            data = entry["data"]
            candidate_ids.add(str(data["req_id"]))
            if str(data["req_id"]) in seen:
                continue
            seen.add(str(data["req_id"]))
            job = normalize(data)
            if job:
                jobs.append(job)
        if len(candidate_ids) >= total:
            break
        if not payload["jobs"] or len(candidate_ids) == before:
            raise RuntimeError("Docusign pagination did not advance to totalCount")
        time.sleep(args.delay)
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    complete = len(candidate_ids) >= total
    write_snapshot(args.output, jobs, input_url=args.url, source=API, total_candidates=total,
                   complete=complete, stopped_reason=None if complete else "listing_page_limit",
                   filters="Native India query, verified country, engineering-title filter; source category labels retained but not trusted", sort="posted_date descending before cap")
    print(f"Docusign: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
