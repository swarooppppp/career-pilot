#!/usr/bin/env python3
"""Public Ashby feeds, with explicit India eligibility and technical role checks."""
import argparse
import json
from pathlib import Path

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import engineering_title, in_india

BOARDS = {"notion": ("Notion", "Notion"), "anyscale": ("anyscale", "Anyscale"),
          "elevenlabs": ("ElevenLabs", "ElevenLabs"), "snyk": ("Snyk", "Snyk"),
          "redis": ("Redis", "Redis"), "ema": ("Ema", "Ema"),
          "kong": ("kong", "Kong"), "docker": ("docker", "Docker"),
          "clickhouse": ("clickhouse", "ClickHouse"), "openai": ("openai", "OpenAI")}


def location_records(job):
    return [{"location": job.get("location"), "address": job.get("address")}] + (job.get("secondaryLocations") or [])


def india_eligible(job):
    for value in location_records(job):
        address = (value.get("address") or {}).get("postalAddress") or {}
        country = str(address.get("addressCountry") or "").casefold()
        if country in {"india", "in"} or in_india({"location": value.get("location")}):
            return True
    # Remote is not evidence that a role can be performed from India.
    return False


def normalize(jobs, company, department=None, team=None):
    results = []
    for job in jobs:
        if department and job.get("department") != department:
            continue
        if team and job.get("team") != team:
            continue
        if job.get("isListed") is not True or not india_eligible(job) or not engineering_title(job):
            continue
        description = job.get("descriptionHtml") or ""
        if not all(job.get(key) for key in ("id", "title", "jobUrl")) or not description:
            raise RuntimeError("Ashby selected job is missing full description or required fields")
        locations = list(dict.fromkeys(str(value.get("location")) for value in location_records(job) if value.get("location")))
        results.append({"id": job["id"], "title": job["title"], "company": company,
                        "department": job.get("department"), "team": job.get("team"),
                        "location": " | ".join(locations), "locations": locations, "country": "India",
                        "location_scope": "Role explicitly includes India; may also have other permitted locations",
                        "application_url": job["jobUrl"], "apply_url": job.get("applyUrl"),
                        "posted_date": job.get("publishedAt"), "jobDescriptionHtml": description,
                        "jobDescriptionText": job.get("descriptionPlain") or plain_text(description)})
    return newest_first(results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--source", choices=BOARDS, required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("Invalid limits")
    board, company = BOARDS[args.source]
    endpoint = "https://api.ashbyhq.com/posting-api/job-board/" + board
    payload = json.loads(read(endpoint, args.timeout))
    if not isinstance(payload.get("jobs"), list):
        raise RuntimeError("Ashby response is missing jobs")
    jobs = normalize(payload["jobs"], company,
                     department="Engineering" if args.source in {"redis", "ema", "docker", "clickhouse"} else None,
                     team="ENG" if args.source == "kong" else None)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, source=endpoint, input_url=args.url,
                   total_public_jobs=len(payload["jobs"]), filters="Listed engineering roles explicitly eligible in India",
                   sort="Ashby publishedAt descending before limit")
    print(f"{company}: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
