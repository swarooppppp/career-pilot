#!/usr/bin/env python3
"""Fetch a filtered Target Careers search URL through Target's public API."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen


BASE = "https://corporate.target.com"
SEARCH_ENDPOINT = f"{BASE}/api/jobsearch"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilot/1.0)"


def read(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"Target returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Target Careers: {exc.reason}") from exc


def search(url: str, page: int, timeout: int) -> dict:
    query = parse_qs(urlparse(url).query)
    values = {
        "lat": query.get("lat", [""])[0], "lon": query.get("lon", [""])[0],
        "maxdistance": query.get("maxdistance", ["40.225"])[0], "currentPage": str(page),
        "q": query.get("query", query.get("q", [""]))[0], "hierarchy": "", "remotetype": "",
        "jobcategories": "", "workersubtype": "", "scheduletype": "", "basepayfrequency": "",
        "organization": "", "locationname": "", "jobaddress": "", "profiles": "", "city": "",
        "state": "", "country": "", "internshipType": "", "jobfamily": "", "subFamilies": "",
        "culture": "en-us", "filtercondition": "", "compgrade": "",
    }
    request = Request(SEARCH_ENDPOINT, data=urlencode(values).encode(), headers={
        "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": USER_AGENT,
    })
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Target search returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Target search: {exc.reason}") from exc


def job_posting(url: str, timeout: int) -> dict:
    document = read(url, timeout)
    for payload in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', document, re.I | re.S):
        try:
            value = json.loads(html.unescape(payload))
        except json.JSONDecodeError:
            continue
        for candidate in value if isinstance(value, list) else [value]:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                return candidate
    raise RuntimeError(f"Target detail page lacks JobPosting data: {url}")


def fetch_jobs(url: str, max_jobs: int, timeout: int, skip_ids: set[str]) -> list[dict]:
    jobs: list[dict] = []
    page = 1
    while True:
        payload = search(url, page, timeout)
        results = payload.get("results") or []
        if not results:
            break
        for result in results:
            summary = result.get("document") or {}
            job_id = str(summary.get("requisitionid") or "")
            if not job_id or job_id in skip_ids:
                continue
            detail_url = BASE + str(summary.get("url") or "")
            detail = job_posting(detail_url, timeout)
            description_html = str(detail.get("description") or "")
            jobs.append({
                "id": job_id, "title": summary.get("title", ""), "company": "Target",
                "location": summary.get("jobaddress", ""), "posted_date": summary.get("dateposted", ""),
                "employment_type": summary.get("scheduletype", ""), "application_url": summary.get("applyurl", detail_url),
                "jobDescriptionHtml": description_html,
                "jobDescriptionText": " ".join(re.sub(r"<[^>]+>", " ", html.unescape(description_html)).split()),
            })
            if max_jobs and len(jobs) >= max_jobs:
                return jobs
        if page * len(results) >= int(payload.get("count", 0)):
            break
        page += 1
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("target_jobs.json"))
    args = parser.parse_args()
    try:
        jobs = fetch_jobs(args.url, args.max_jobs, args.timeout, set(args.skip_job_id))
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"input_url": args.url, "jobs": jobs}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Target jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
