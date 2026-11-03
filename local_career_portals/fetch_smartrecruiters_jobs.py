#!/usr/bin/env python3
"""PhonePe and ServiceNow public feeds with full SmartRecruiters descriptions."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlencode, urlparse

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import in_india

API = "https://api.smartrecruiters.com/v1/companies"
PHONEPE_FEED = "https://www.phonepe.com/apollo/job-postings/latest.json"


def city_key(value):
    return value.strip().casefold().replace("bengaluru", "bangalore").replace("gurugram", "gurgaon").split(",")[0]


def phonepe_summaries(payload):
    if not isinstance(payload.get("results"), list):
        raise RuntimeError("PhonePe feed is missing results")
    jobs = []
    for item in payload["results"]:
        if item.get("status") != "PUBLIC" or item.get("department") != "Engineering" or not in_india(item):
            continue
        match = re.fullmatch(r"https://jobs\.smartrecruiters\.com/PHONEPELIMITED/(\d+)-.*", item.get("applyUrl") or "")
        if not match:
            raise RuntimeError("PhonePe public apply URL format changed")
        date = re.fullmatch(r"/Date\((\d+)\)/", item.get("updatedAt") or "")
        jobs.append({**item, "id": match.group(1), "updated_date": datetime.fromtimestamp(int(date.group(1)) / 1000, timezone.utc).isoformat() if date else None})
    return newest_first(jobs)


def servicenow_matches(item, locations):
    location = item.get("location") or {}
    return (location.get("country", "").casefold() == "in"
            and (item.get("function") or {}).get("id") == "engineering"
            and (not locations or city_key(location.get("city", "")) in locations))


def description_html(detail):
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    description = (sections.get("jobDescription") or {}).get("text") or ""
    if not description:
        raise RuntimeError("SmartRecruiters full job description unavailable")
    return "\n".join(f"<h2>{(sections.get(key) or {}).get('title') or key}</h2>" + (sections.get(key) or {}).get("text", "")
                      for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation") if (sections.get(key) or {}).get("text"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--source", choices=("phonepe", "servicenow"), required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits or delay")
    if args.source == "phonepe":
        company, tenant = "PhonePe", "PHONEPELIMITED"
        summaries = phonepe_summaries(json.loads(read(PHONEPE_FEED, args.timeout)))
    else:
        company, tenant = "ServiceNow", "ServiceNow"
        query = parse_qs(urlparse(args.url).query)
        locations = {city_key(value) for value in query.get("location", []) if value}
        summaries, offset = [], 0
        while True:
            params = {"limit": 100, "offset": offset, "country": "in", "keyword": query.get("search", ["Software Engineer"])[0]}
            payload = json.loads(read(f"{API}/{tenant}/postings?{urlencode(params)}", args.timeout))
            if not isinstance(payload.get("content"), list) or "totalFound" not in payload:
                raise RuntimeError("ServiceNow listing response shape changed")
            for item in payload["content"]:
                if servicenow_matches(item, locations):
                    summaries.append({**item, "posted_date": item.get("releasedDate")})
            offset += len(payload["content"])
            if offset >= payload["totalFound"]:
                break
            if not payload["content"]:
                raise RuntimeError("ServiceNow pagination ended before totalFound")
            time.sleep(args.delay)
        summaries = newest_first(summaries)
    if args.max_jobs:
        summaries = summaries[:args.max_jobs]
    jobs = []
    for item in summaries:
        detail = json.loads(read(f"{API}/{tenant}/postings/{item['id']}", args.timeout))
        if (detail.get("company") or {}).get("identifier", "").casefold() != tenant.casefold():
            raise RuntimeError("Unexpected SmartRecruiters company")
        location = detail.get("location") or {}
        if location.get("country", "").casefold() != "in":
            continue
        description = description_html(detail)
        display_location = location.get("fullLocation") or ""
        if not re.search(r"[A-Za-z]", display_location):
            city = location.get("city") or (item.get("location") if isinstance(item.get("location"), str) else "")
            display_location = f"{city}, India" if city else "India"
        jobs.append({"id": str(item["id"]), "title": detail.get("name") or item.get("title"), "company": company,
                     "department": "Engineering", "country": "India", "location": display_location,
                     "application_url": detail.get("postingUrl") or item.get("applyUrl"),
                     "posted_date": detail.get("releasedDate"), "updated_date": item.get("updated_date"),
                     "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
        time.sleep(args.delay)
    jobs = newest_first(jobs)
    write_snapshot(args.output, jobs, source=f"{API}/{tenant}/postings", input_url=args.url,
                   filters="Native Engineering department/function and India; supplied ServiceNow city filters",
                   sort="Publication dates descending; PhonePe candidates first selected by feed update time")
    print(f"{company}: wrote {len(jobs)} filtered jobs")


if __name__ == "__main__":
    main()
