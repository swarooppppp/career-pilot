#!/usr/bin/env python3
"""Fetch recent Amazon Jobs search results into the portal import schema.

Amazon's public search page requests ``/en/search.json``. Each result already
contains the full description and qualifications, so pagination needs one JSON
request per results page rather than one extra request per job.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


BASE_URL = "https://www.amazon.jobs"
SEARCH_FACETS = (
    "normalized_country_code", "normalized_state_name", "normalized_city_name",
    "location", "business_category", "category", "schedule_type_id",
    "employee_class", "normalized_location", "job_function_id", "is_manager", "is_intern",
)


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


def api_url(search_url: str, offset: int, result_limit: int) -> str:
    """Translate the public search-page query into Amazon's JSON API query."""
    parsed = urlparse(search_url)
    params: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key in {"offset", "result_limit", "distanceType"}:
            continue
        if key == "job_type[]":
            key = "schedule_type_id[]"
        elif key == "city[]":
            key = "normalized_city_name[]"
        params.append((key, value))
    params.extend(("facets[]", facet) for facet in SEARCH_FACETS)
    params.extend((("offset", str(offset)), ("result_limit", str(result_limit))))
    path = parsed.path.rstrip("/")
    if not path.endswith("/search"):
        raise ValueError("Amazon search URL must end in /search")
    return urlunparse(parsed._replace(path=f"{path}.json", query=urlencode(params, doseq=True)))


def fetch_json(url: str, timeout: int) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Amazon Jobs: {exc.reason}") from exc


def normalise_result(result: dict[str, Any]) -> dict[str, Any] | None:
    external_id = str(result.get("id_icims") or result.get("id") or "").strip()
    title = str(result.get("title") or "").strip()
    job_path = str(result.get("job_path") or "").strip()
    description_html = "\n".join(
        part for part in (
            result.get("description"),
            result.get("basic_qualifications"),
            result.get("preferred_qualifications"),
        ) if isinstance(part, str) and part.strip()
    )
    if not external_id or not title or not description_html:
        return None
    return {
        "id": external_id,
        "title": title,
        "company": result.get("company_name") or "Amazon",
        "location": result.get("location") or result.get("normalized_location") or "",
        "application_url": urljoin(BASE_URL, job_path),
        "posted_date": result.get("posted_date"),
        "jobDescriptionHtml": description_html,
        "jobDescriptionText": html_to_text(description_html),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Amazon Jobs search URL, enclosed in quotes.")
    parser.add_argument("--max-pages", type=int, default=10, help="Use 0 to fetch all available pages.")
    parser.add_argument("--result-limit", type=int, default=10, help="Amazon results per page.")
    parser.add_argument("--max-jobs", type=int, default=100, help="Keep at most this many unique jobs; 0 keeps all fetched jobs.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("amazon_jobs.json"))
    args = parser.parse_args()
    if args.max_pages < 0 or args.result_limit < 1 or args.max_jobs < 0:
        parser.error("max-pages/max-jobs must be non-negative and result-limit must be positive")

    jobs: list[dict[str, Any]] = []
    hits: int | None = None
    page = 1
    while args.max_pages == 0 or page <= args.max_pages:
        offset = (page - 1) * args.result_limit
        url = api_url(args.url, offset, args.result_limit)
        print(f"Fetching page {page}: {url}", file=sys.stderr)
        payload = fetch_json(url, args.timeout)
        page_results = payload.get("jobs")
        if not isinstance(page_results, list):
            raise RuntimeError("Amazon Jobs response did not contain a jobs list")
        if hits is None:
            hits = int(payload.get("hits") or 0)
        jobs.extend(job for result in page_results if (job := normalise_result(result)) is not None)
        if not page_results or len(page_results) < args.result_limit or (hits and offset + len(page_results) >= hits):
            break
        if args.max_jobs and len(jobs) >= args.max_jobs:
            break
        page += 1

    unique_jobs = list({job["id"]: job for job in jobs}.values())
    if args.max_jobs:
        unique_jobs = unique_jobs[:args.max_jobs]
    output = {
        "source": f"{BASE_URL}/en/search.json",
        "retrieval": "public Amazon Jobs JSON search API, paginated with offset and result_limit",
        "input_url": args.url,
        "total_results_reported_by_api": hits,
        "jobs_fetched": len(unique_jobs),
        "jobs": unique_jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(unique_jobs)} jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
