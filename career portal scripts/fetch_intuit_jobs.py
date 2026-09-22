#!/usr/bin/env python3
"""Fetch India-based Intuit jobs from its public careers pages.

Intuit's search URL applies its category facet in the browser. This adapter
keeps that URL, collects its paginated job cards, then performs an additional
deterministic country check before requesting each selected job's public detail
page. JobPosting JSON-LD on that page supplies the full description and date.
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


BASE_URL = "https://jobs.intuit.com"
DEFAULT_URL = "https://jobs.intuit.com/search-jobs?acm=8698512,68357,68358&alrpm=ALL&ascf=%5B%7B%22key%22:%22ALL%22,%22value%22:%22%22%7D%5D"


def fetch_text(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8")
    except HTTPError as error:
        raise RuntimeError(f"Intuit returned HTTP {error.code} from {url}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Intuit Careers: {error.reason}") from error


def page_url(search_url: str, page: int) -> str:
    parsed = urlparse(search_url)
    if parsed.scheme != "https" or parsed.netloc != "jobs.intuit.com" or parsed.path != "/search-jobs":
        raise ValueError("Intuit search URL must be an https://jobs.intuit.com/search-jobs URL")
    parameters = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "p"]
    if page > 1:
        parameters.append(("p", str(page)))
    return urlunparse(parsed._replace(query=urlencode(parameters, doseq=True)))


class SearchResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.jobs: list[dict[str, str]] = []
        self.current: dict[str, str] | None = None
        self.location_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "a" and "sr-item" in classes:
            href = attributes.get("href") or ""
            if href.startswith("/job/"):
                self.current = {"url": urljoin(BASE_URL, href), "title": html.unescape(attributes.get("data-title") or "")}
        elif self.current and tag == "span" and "job-location" in classes:
            self.location_depth = 1
        elif self.location_depth:
            self.location_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.location_depth:
            self.location_depth -= 1
        if tag == "a" and self.current:
            self.jobs.append(self.current)
            self.current = None

    def handle_data(self, data: str) -> None:
        if self.current and self.location_depth:
            self.current["location"] = (self.current.get("location", "") + data).strip()


class JsonLdParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_json_ld = False
        self.parts: list[str] = []
        self.payloads: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self.in_json_ld = True
            self.parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.in_json_ld:
            self.in_json_ld = False
            self.payloads.append("".join(self.parts))

    def handle_data(self, data: str) -> None:
        if self.in_json_ld:
            self.parts.append(data)

    def job_posting(self) -> dict[str, Any] | None:
        for payload in self.payloads:
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            candidates = value if isinstance(value, list) else value.get("@graph", [value]) if isinstance(value, dict) else []
            for candidate in candidates:
                if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting":
                    return candidate
        return None


def extract_results(page_html: str) -> list[dict[str, str]]:
    parser = SearchResultParser()
    parser.feed(page_html)
    parser.close()
    return parser.jobs


def extract_job_posting(page_html: str) -> dict[str, Any] | None:
    parser = JsonLdParser()
    parser.feed(page_html)
    parser.close()
    return parser.job_posting()


def normalise_result(listing: dict[str, str], posting: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(posting.get("identifier") or "").strip()
    title = str(posting.get("title") or listing.get("title") or "").strip()
    description_html = str(posting.get("description") or "").strip()
    application_url = str(posting.get("url") or listing.get("url") or "").strip()
    location = str(listing.get("location") or "").strip()
    if not job_id or not title or not description_html or not application_url or not location:
        return None
    # Extract readable text while retaining the source HTML separately.
    class TextCollector(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in {"br", "p", "li", "h1", "h2", "h3", "h4"}:
                self.parts.append("\n")
        def handle_data(self, data: str) -> None:
            self.parts.append(data)
    collector = TextCollector()
    collector.feed(description_html)
    collector.close()
    description_text = "\n".join(
        line for line in (" ".join(line.split()) for line in "".join(collector.parts).splitlines()) if line
    )
    return {
        "id": job_id, "title": title, "company": "Intuit", "location": location,
        "application_url": application_url, "posted_date": posting.get("datePosted"),
        "jobDescriptionHtml": description_html, "jobDescriptionText": description_text,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Intuit public search URL")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--country", default="India", help="Keep listings whose displayed location contains this country.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("intuit_jobs.json"))
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-pages and timeout must be positive; max-jobs cannot be negative")
    try:
        selected: list[dict[str, str]] = []
        seen_urls: set[str] = set()
        for page in range(1, args.max_pages + 1):
            current_url = page_url(args.url, page)
            print(f"Fetching Intuit search page {page}: {current_url}", file=sys.stderr)
            results = extract_results(fetch_text(current_url, args.timeout))
            if not results:
                break
            for result in results:
                if args.country.casefold() not in result.get("location", "").casefold() or result["url"] in seen_urls:
                    continue
                seen_urls.add(result["url"])
                selected.append(result)
                if args.max_jobs and len(selected) >= args.max_jobs:
                    break
            if args.max_jobs and len(selected) >= args.max_jobs:
                break
        jobs: list[dict[str, Any]] = []
        for number, listing in enumerate(selected, start=1):
            print(f"Fetching Intuit job {number}/{len(selected)}: {listing['url']}", file=sys.stderr)
            posting = extract_job_posting(fetch_text(listing["url"], args.timeout))
            if posting and (job := normalise_result(listing, posting)) is not None:
                jobs.append(job)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    output = {
        "source": "Intuit Careers public HTML and JobPosting JSON-LD",
        "retrieval": "Paginated Intuit search pages plus public job-detail JSON-LD; filtered deterministically by displayed country",
        "input_url": args.url, "country_filter": args.country, "jobs_fetched": len(jobs), "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Intuit jobs in {args.country} to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
