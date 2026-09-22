#!/usr/bin/env python3
"""Fetch Databricks Careers jobs from its public Greenhouse board."""

from __future__ import annotations

import argparse
import html
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


DEFAULT_URL = "https://www.databricks.com/company/careers/open-positions?department=Engineering&location=India&search=Software%20Engineer"
API_URL = "https://boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true"


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "li", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")
    def handle_data(self, data: str) -> None:
        self.parts.append(data)
    def text(self) -> str:
        return "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.parts).splitlines()) if line)


def html_to_text(value: str) -> str:
    parser = TextParser(); parser.feed(value); parser.close()
    return html.unescape(parser.text())


def fetch_jobs(timeout: int) -> list[dict[str, Any]]:
    try:
        with urlopen(Request(API_URL, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"}), timeout=timeout) as response:
            payload = json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8"))
    except HTTPError as error:
        raise RuntimeError(f"Databricks Greenhouse board returned HTTP {error.code}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Databricks Careers: {error.reason}") from error
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        raise RuntimeError("Databricks Greenhouse response did not contain a jobs list")
    return [job for job in jobs if isinstance(job, dict)]


def department_names(job: dict[str, Any]) -> list[str]:
    departments = job.get("departments")
    return [str(item.get("name") or "") for item in departments if isinstance(item, dict)] if isinstance(departments, list) else []


def matches(job: dict[str, Any], query: dict[str, list[str]]) -> bool:
    department = query.get("department", [""])[0].casefold()
    location = query.get("location", [""])[0].casefold()
    search = query.get("search", [""])[0].casefold()
    departments = " ".join(department_names(job)).casefold()
    job_location = str((job.get("location") or {}).get("name") or "").casefold()
    searchable = f"{job.get('title', '')} {job.get('content', '')}".casefold()
    return ((not department or department in departments) and (not location or location in job_location)
            and (not search or all(word in searchable for word in search.split())))


def normalise_result(job: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(job.get("id") or "").strip()
    title = str(job.get("title") or "").strip()
    description_html = str(job.get("content") or "").strip()
    application_url = str(job.get("absolute_url") or "").strip()
    location = str((job.get("location") or {}).get("name") or "").strip()
    if not job_id or not title or not description_html or not application_url:
        return None
    return {"id": job_id, "title": title, "company": "Databricks", "location": location,
            "application_url": application_url, "posted_date": job.get("updated_at"),
            "jobDescriptionHtml": description_html, "jobDescriptionText": html_to_text(description_html)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Databricks careers search URL")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path("databricks_jobs.json"))
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-jobs cannot be negative and timeout must be positive")
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or parsed.netloc != "www.databricks.com" or parsed.path != "/company/careers/open-positions":
        parser.error("url must be an https://www.databricks.com/company/careers/open-positions URL")
    try:
        jobs = [result for job in fetch_jobs(args.timeout) if matches(job, parse_qs(parsed.query))
                if (result := normalise_result(job)) is not None]
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr); return 1
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    output = {"source": "Databricks public Greenhouse board", "retrieval": "Public Greenhouse board filtered locally using the supplied careers URL",
              "input_url": args.url, "jobs_fetched": len(jobs), "jobs": jobs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} matching Databricks jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
