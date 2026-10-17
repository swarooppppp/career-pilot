#!/usr/bin/env python3
"""Fetch filtered jobs from a public Workday Careers site.

This adapter uses Workday's public Candidate Experience endpoints, rather
than browser automation.  It retains search parameters from the supplied
Workday URL and fetches a description only for jobs not already in the DB.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "Mozilla/5.0 (compatible; CareerPilot/1.0)"


def site_config(url: str) -> tuple[str, str, str, dict[str, str]]:
    """Return Workday host, tenant, site and query parameters from a job URL."""
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme != "https" or not parsed.netloc.endswith("myworkdayjobs.com") or not parts:
        raise ValueError("Expected an https://<tenant>.myworkdayjobs.com/<site> URL")
    tenant = parsed.netloc.split(".", 1)[0]
    return parsed.netloc, tenant, parts[0], {key: values[-1] for key, values in parse_qs(parsed.query).items()}


def request_json(url: str, payload: dict | None, timeout: int) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT,
                 **({"Content-Type": "application/json"} if payload is not None else {})},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Workday returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Workday: {exc.reason}") from exc


def clean_html(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


def search_payload(query: dict[str, str], limit: int, offset: int) -> dict:
    payload: dict[str, object] = {"limit": limit, "offset": offset, "searchText": query.get("q", "")}
    # Workday's public search accepts these same browser URL values as facets.
    facets: dict[str, list[str]] = {}
    for name in ("locationCountry", "timeType", "jobFamilyGroup", "jobProfile"):
        if query.get(name):
            facets[name] = [query[name]]
    if facets:
        payload["appliedFacets"] = facets
    return payload


def fetch_jobs(url: str, max_jobs: int, page_size: int, timeout: int, skip_ids: set[str]) -> list[dict]:
    host, tenant, site, query = site_config(url)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    results: list[dict] = []
    offset = 0
    total = None
    while total is None or offset < total:
        page = request_json(f"{base}/jobs", search_payload(query, page_size, offset), timeout)
        total = int(page.get("total", 0))
        postings = page.get("jobPostings", [])
        if not postings:
            break
        for posting in postings:
            external_path = str(posting.get("externalPath") or "")
            job_id = str((posting.get("bulletFields") or [""])[0])
            if not job_id or not external_path:
                continue
            if job_id in skip_ids:
                print(f"Skipping existing: {job_id}", file=sys.stderr)
                continue
            detail = request_json(f"{base}{external_path}", None, timeout).get("jobPostingInfo", {})
            description_html = str(detail.get("jobDescription") or "")
            results.append({
                "id": job_id,
                "title": posting.get("title", ""),
                "company": tenant.replace("-", " ").title(),
                "location": posting.get("locationsText", ""),
                "posted_date": posting.get("postedOn", ""),
                "application_url": f"https://{host}{external_path}",
                "jobDescriptionHtml": description_html,
                "jobDescriptionText": clean_html(description_html),
            })
            if max_jobs and len(results) >= max_jobs:
                return results
        offset += len(postings)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Filtered public Workday Careers URL")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("workday_jobs.json"))
    args = parser.parse_args()
    try:
        jobs = fetch_jobs(args.url, args.max_jobs, args.page_size, args.timeout, set(args.skip_job_id))
    except (RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"input_url": args.url, "jobs": jobs}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Workday jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
