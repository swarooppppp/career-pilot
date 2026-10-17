#!/usr/bin/env python3
"""Fetch Atlassian careers jobs from a filtered public jobs URL."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen


BASE_URL = "https://www.atlassian.com"
DEFAULT_URL = "https://www.atlassian.com/company/careers/all-jobs?team=Engineering&location=India&search=Software%20Engineer"
API_URL = f"{BASE_URL}/endpoint/careers/listings"


class HTMLToText(HTMLParser):
    BLOCK_TAGS = {"br", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("- ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(line.split()) for line in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def html_to_text(value: str) -> str:
    parser = HTMLToText()
    parser.feed(value)
    parser.close()
    return html.unescape(parser.text())


def fetch_jobs(timeout: int) -> list[dict[str, Any]]:
    request = Request(API_URL, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"Atlassian returned HTTP {error.code} from its public listings endpoint.") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Atlassian Careers: {error.reason}") from error
    if not isinstance(payload, list):
        raise RuntimeError("Atlassian listings response must be a JSON list.")
    return [job for job in payload if isinstance(job, dict)]


def fetch_detail_page(url: str, timeout: int) -> str:
    """Fetch the public role page, which contains its complete requirements."""
    request = Request(url, headers={"Accept": "text/html", "User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as error:
        raise RuntimeError(f"Atlassian returned HTTP {error.code} for job detail {url}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Atlassian job detail: {error.reason}") from error


def detail_description(document: str) -> str:
    """Extract a full JobPosting description from the public role-page schema."""
    scripts = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, flags=re.IGNORECASE | re.DOTALL)
    for script in scripts:
        try:
            payload = json.loads(html.unescape(script))
        except json.JSONDecodeError:
            continue
        for item in payload if isinstance(payload, list) else [payload]:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            if item_type != "JobPosting" and "JobPosting" not in item_type:
                continue
            description = str(item.get("description") or "").strip()
            if description:
                return description
    raise RuntimeError("Atlassian job detail did not contain a JobPosting description")


def locations_text(locations: Any) -> str:
    if not isinstance(locations, list):
        return ""
    values: list[str] = []
    for location in locations:
        value = location if isinstance(location, str) else location.get("name") if isinstance(location, dict) else ""
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)
    return " + ".join(values)


def matches(job: dict[str, Any], query: dict[str, list[str]]) -> bool:
    team = query.get("team", [""])[0].casefold()
    location = query.get("location", [""])[0].casefold()
    search = query.get("search", [""])[0].casefold()
    locations = locations_text(job.get("locations")).casefold()
    searchable = f"{job.get('title', '')} {job.get('overview', '')}".casefold()
    return (
        (not team or str(job.get("category") or "").casefold() == team)
        and (not location or location in locations)
        and (not search or all(word in searchable for word in search.split()))
    )


def normalise_result(job: dict[str, Any], description_html: str | None = None) -> dict[str, Any] | None:
    job_id = str(job.get("id") or "").strip()
    title = str(job.get("title") or "").strip()
    description_html = str(description_html or job.get("overview") or "").strip()
    portal_post = job.get("portalJobPost") if isinstance(job.get("portalJobPost"), dict) else {}
    application_url = str(portal_post.get("portalUrl") or "").strip()
    if not job_id or not title or not description_html or not application_url:
        return None
    return {
        "id": job_id,
        "title": title,
        "company": "Atlassian",
        "location": locations_text(job.get("locations")),
        "application_url": urljoin(BASE_URL, application_url),
        "posted_date": portal_post.get("updatedDate"),
        "jobDescriptionHtml": description_html,
        "jobDescriptionText": html_to_text(description_html),
    }


def hydrate_results(jobs: list[dict[str, Any]], timeout: int, delay: float, skip_ids: set[str]) -> list[dict[str, Any]]:
    """Replace listing overviews with complete public descriptions before import."""
    results: list[dict[str, Any]] = []
    for index, job in enumerate(jobs, start=1):
        if str(job.get("id") or "") in skip_ids:
            print(f"Skipping existing {index}/{len(jobs)}: {job.get('id', '')}", file=sys.stderr)
            continue
        portal_post = job.get("portalJobPost") if isinstance(job.get("portalJobPost"), dict) else {}
        detail_path = str(portal_post.get("portalUrl") or "").strip()
        description_html: str | None = None
        if detail_path:
            try:
                print(f"Fetching {index}/{len(jobs)}: {job.get('id', '')}", file=sys.stderr)
                description_html = detail_description(fetch_detail_page(urljoin(BASE_URL, detail_path), timeout))
            except RuntimeError as error:
                print(f"Skipping detail hydration for {job.get('id', '')}: {error}", file=sys.stderr)
        result = normalise_result(job, description_html)
        if result is not None:
            results.append(result)
        if index != len(jobs):
            time.sleep(delay)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Atlassian public careers jobs URL")
    parser.add_argument("--max-jobs", type=int, default=50, help="Maximum matching jobs to write; 0 keeps all.")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between public job-detail requests.")
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("atlassian_jobs.json"))
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("max-jobs and delay cannot be negative; timeout must be positive")
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or parsed.netloc != "www.atlassian.com" or parsed.path != "/company/careers/all-jobs":
        parser.error("url must be an https://www.atlassian.com/company/careers/all-jobs URL")
    try:
        query = parse_qs(parsed.query)
        matching_jobs = [job for job in fetch_jobs(args.timeout) if matches(job, query)]
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if args.max_jobs:
        matching_jobs = matching_jobs[:args.max_jobs]
    jobs = hydrate_results(matching_jobs, args.timeout, args.delay, set(args.skip_job_id))
    output = {
        "source": "Atlassian Careers public listings API",
        "retrieval": "Public Atlassian careers listings endpoint filtered locally using the supplied careers URL",
        "input_url": args.url,
        "jobs_fetched": len(jobs),
        "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} matching Atlassian jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
