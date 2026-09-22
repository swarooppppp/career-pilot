#!/usr/bin/env python3
"""Fetch public Google Careers search results, including full job descriptions.

Google Careers server-renders the job records into the results-page HTML.  Each
result page contains up to 20 complete records, and `page=1`, `page=2`, ...
selects subsequent pages. This uses only Python's standard library.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


PAGE_SIZE = 20
JOB_START = re.compile(r'\["\d{10,}","')


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


def page_url(search_url: str, page: int) -> str:
    parsed = urlparse(search_url)
    params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "page"]
    params.append(("page", str(page)))
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def job_detail_url(search_url: str, job_id: str, title: str) -> str:
    """Build the public job-description URL, not Google's sign-in/apply URL."""
    parsed = urlparse(search_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "page"]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    base_path = parsed.path.rstrip("/")
    return urlunparse(parsed._replace(path=f"{base_path}/{job_id}-{slug}", query=urlencode(query, doseq=True)))


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Google Careers: {exc.reason}") from exc


def matching_bracket_end(source: str, start: int) -> int:
    """Return the closing bracket of a JSON array while respecting strings."""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        else:
            if char == '"':
                in_string = True
            elif char == "[":
                depth += 1
            elif char == "]":
                depth -= 1
                if depth == 0:
                    return index
    raise ValueError("Unclosed job record in Google Careers response")


def parse_jobs(page_html: str, search_url: str) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for match in JOB_START.finditer(page_html):
        raw = page_html[match.start() : matching_bracket_end(page_html, match.start()) + 1]
        record = json.loads(raw)
        # Google currently serializes records as:
        # [id, title, apply_url, [_, responsibilities], [_, qualifications],
        #  company_resource, _, company, locale, locations, [_, overview], ...]
        if len(record) < 11 or not isinstance(record[1], str):
            continue
        locations = [location[0] for location in record[9] if location and location[0]]
        responsibilities_html = record[3][1] if len(record[3]) > 1 else ""
        qualifications_html = record[4][1] if len(record[4]) > 1 else ""
        overview_html = record[10][1] if len(record[10]) > 1 else ""
        description_html = (
            f"<h2>About the job</h2>{overview_html}"
            f"<h2>Responsibilities</h2>{responsibilities_html}"
            f"<h2>Qualifications</h2>{qualifications_html}"
        )
        jobs.append({
            "id": record[0],
            "title": record[1],
            "applyUrl": record[2],
            "application_url": job_detail_url(search_url, record[0], record[1]),
            "company": record[7],
            "locale": record[8],
            "locations": locations,
            "overviewHtml": overview_html,
            "responsibilitiesHtml": responsibilities_html,
            "qualificationsHtml": qualifications_html,
            "jobDescriptionHtml": description_html,
            "jobDescriptionText": html_to_text(description_html),
        })
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Google Careers results URL, enclosed in quotes.")
    parser.add_argument("--max-pages", type=int, default=1, help="Use 0 to fetch all pages.")
    parser.add_argument("--max-jobs", type=int, default=0, help="Keep at most this many unique jobs; 0 keeps all fetched jobs.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("google_jobs.json"))
    args = parser.parse_args()
    if args.max_jobs < 0:
        parser.error("max-jobs must be non-negative")

    jobs: list[dict[str, Any]] = []
    page = 1
    while args.max_pages == 0 or page <= args.max_pages:
        url = page_url(args.url, page)
        print(f"Fetching page {page}: {url}", file=sys.stderr)
        page_jobs = parse_jobs(fetch_html(url, args.timeout), url)
        if not page_jobs:
            break
        jobs.extend(page_jobs)
        if len(page_jobs) < PAGE_SIZE:
            break
        page += 1

    # A job can appear in multiple location-filtered pages; retain its first occurrence.
    unique_jobs = list({job["id"]: job for job in jobs}.values())
    if args.max_jobs:
        unique_jobs = unique_jobs[:args.max_jobs]
    output = {
        "source": "https://www.google.com/about/careers/applications/jobs/results",
        "retrieval": "server-rendered Google Careers results HTML, paginated with the page query parameter",
        "input_url": args.url,
        "jobs_fetched": len(unique_jobs),
        "jobs": unique_jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(unique_jobs)} jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
