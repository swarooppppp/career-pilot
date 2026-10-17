#!/usr/bin/env python3
"""Fetch a filtered Rippling Careers URL into Career Pilot job records."""

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
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen


DEFAULT_URL = "https://www.rippling.com/en-GB/careers/open-roles?search=Software%20Engineer&department=Engineering&location=Bangalore%2C%20India"
ALGOLIA_ENDPOINT = "https://6fnax3tbef-1.algolianet.com/1/indexes/*/queries"
ALGOLIA_APPLICATION_ID = "6FNAX3TBEF"
ALGOLIA_API_KEY = "416caa4690f002ff6fe4a2097623640b"
ALGOLIA_INDEX = "careers_en-US_production"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilotRipplingFetcher/1.0)"


class HTMLToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3"}: self.parts.append("\n")
        if tag == "li": self.parts.append("- ")
    def handle_data(self, data: str) -> None: self.parts.append(data)
    def text(self) -> str:
        return "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.parts).splitlines()) if line)


def html_to_text(value: str) -> str:
    parser = HTMLToText(); parser.feed(value); parser.close()
    return html.unescape(parser.text())


def fetch_bytes(request: Request, timeout: int) -> bytes:
    try:
        with urlopen(request, timeout=timeout) as response: return response.read()
    except HTTPError as error: raise RuntimeError(f"Rippling returned HTTP {error.code} for {request.full_url}") from error
    except URLError as error: raise RuntimeError(f"Could not reach Rippling Careers: {error.reason}") from error


def search_page(search_url: str, page: int, timeout: int) -> dict[str, Any]:
    filters = parse_qs(urlparse(search_url).query)
    facet_filters = []
    if department := filters.get("department", [""])[0]: facet_filters.append([f"departmentName:{department}"])
    if location := filters.get("location", [""])[0]: facet_filters.append([f"locationNames:{location}"])
    parameters = {"query": filters.get("search", [""])[0], "facets": "*", "hitsPerPage": "100", "page": str(page)}
    if facet_filters: parameters["facetFilters"] = json.dumps(facet_filters, separators=(",", ":"))
    body = json.dumps({"requests": [{"indexName": ALGOLIA_INDEX, "params": urlencode(parameters)}]}).encode()
    request = Request(ALGOLIA_ENDPOINT, data=body, headers={"Content-Type": "application/json", "X-Algolia-Application-Id": ALGOLIA_APPLICATION_ID, "X-Algolia-API-Key": ALGOLIA_API_KEY})
    try:
        result = json.loads(fetch_bytes(request, timeout))["results"][0]
    except (KeyError, IndexError, json.JSONDecodeError) as error:
        raise RuntimeError("Rippling's jobs index returned an unexpected response") from error
    if not isinstance(result, dict): raise RuntimeError("Rippling's jobs index returned an unexpected response")
    return result


def job_posting_description(document: str) -> str:
    """Extract the public JobPosting JSON-LD description from a detail page."""
    for payload in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, flags=re.I | re.S):
        try: items = json.loads(html.unescape(payload))
        except json.JSONDecodeError: continue
        for item in items if isinstance(items, list) else [items]:
            if isinstance(item, dict) and (item.get("@type") == "JobPosting" or "JobPosting" in item.get("@type", [])):
                description = str(item.get("description") or "").strip()
                if description: return description
    # Rippling migrated some detail pages from JSON-LD to Next.js page data.
    # Keep the JSON-LD path first, then read the server-rendered role field.
    next_data = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', document, flags=re.I | re.S)
    if next_data:
        try:
            payload = json.loads(html.unescape(next_data.group(1)))
            api_data = payload["props"]["pageProps"].get("apiData", {})
        except (KeyError, TypeError, json.JSONDecodeError):
            api_data = {}
        stack = [api_data]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                role = value.get("role")
                if isinstance(role, str) and role.strip():
                    return role
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    raise RuntimeError("Rippling job page did not contain a public job description")


def fetch_detail(url: str, timeout: int) -> str:
    request = Request(url, headers={"Accept": "text/html", "User-Agent": USER_AGENT})
    return job_posting_description(fetch_bytes(request, timeout).decode("utf-8", errors="replace"))


def fetch_jobs(url: str, max_jobs: int, timeout: int, delay: float, skip_ids: set[str]) -> list[dict[str, Any]]:
    first = search_page(url, 0, timeout); pages = [first]
    for page in range(1, int(first.get("nbPages") or 1)): pages.append(search_page(url, page, timeout))
    summaries = [hit for result in pages for hit in result.get("hits", []) if isinstance(hit, dict)]
    if max_jobs: summaries = summaries[:max_jobs]
    jobs = []
    for index, hit in enumerate(summaries, start=1):
        job_id, title = str(hit.get("jobId") or "").strip(), str(hit.get("name") or "").strip()
        detail_url = urljoin("https://www.rippling.com", str(hit.get("url") or ""))
        if not job_id or not title or not detail_url: continue
        if job_id in skip_ids:
            print(f"Skipping existing {index}/{len(summaries)}: {job_id}", file=sys.stderr); continue
        print(f"Fetching {index}/{len(summaries)}: {job_id}", file=sys.stderr)
        description_html = fetch_detail(detail_url, timeout)
        jobs.append({"id": job_id, "title": title, "company": "Rippling", "location": " | ".join(hit.get("locationNames") or []),
                     "application_url": detail_url, "jobDescriptionHtml": description_html, "jobDescriptionText": html_to_text(description_html)})
        if index != len(summaries): time.sleep(delay)
    return list({job["id"]: job for job in jobs}.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL); parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30); parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=Path("rippling_jobs.json")); parser.add_argument("--skip-job-id", action="append", default=[]); args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0: parser.error("max-jobs and delay cannot be negative; timeout must be positive")
    try: jobs = fetch_jobs(args.url, args.max_jobs, args.timeout, args.delay, set(args.skip_job_id))
    except RuntimeError as error: print(f"Error: {error}", file=sys.stderr); return 1
    output = {"source": "Rippling Careers public Algolia index and job pages", "input_url": args.url, "jobs_fetched": len(jobs), "jobs": jobs}
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Rippling jobs to {args.output}", file=sys.stderr); return 0


if __name__ == "__main__": raise SystemExit(main())
