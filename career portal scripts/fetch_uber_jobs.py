#!/usr/bin/env python3
"""Fetch Uber job listings through an isolated browser session.

Uber's careers API sometimes presents a Cloudflare challenge to direct Python
HTTP clients. This adapter opens the public search page and makes the same-
origin API requests from that temporary browser context. It never reads or
stores a user's existing browser cookies.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse


BASE_URL = "https://jobs.uber.com"


class HTMLToText(HTMLParser):
    BLOCK_TAGS = {"br", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4"}

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


def _location(locations: Any) -> str:
    if not isinstance(locations, list):
        return ""
    values: list[str] = []
    for location in locations:
        if not isinstance(location, dict):
            continue
        value = str(location.get("Address") or "").strip()
        if not value:
            value = ", ".join(str(location.get(key)) for key in ("City", "Region", "Country") if location.get(key))
        if value and value not in values:
            values.append(value)
    return " + ".join(values)


def _public_url(urls: Any) -> str:
    if not isinstance(urls, list):
        return ""
    selected = next((item for item in urls if isinstance(item, dict) and item.get("IsDefault")), None)
    selected = selected or next((item for item in urls if isinstance(item, dict)), None)
    return urljoin(BASE_URL, str(selected.get("Url") or "")) if selected else ""


def normalise_result(result: dict[str, Any]) -> dict[str, Any] | None:
    """Convert Uber's response object to the project's raw-job snapshot schema."""
    job_id = str(result.get("Id") or result.get("Reference") or "").strip()
    title = str(result.get("Title") or "").strip()
    description_html = str(result.get("Description") or "").strip()
    application_url = _public_url(result.get("Urls"))
    if not job_id or not title or not description_html or not application_url:
        return None
    return {
        "id": job_id,
        "title": title,
        "company": "Uber",
        "location": _location(result.get("Locations")),
        "application_url": application_url,
        "posted_date": result.get("DisplayDate"),
        "jobDescriptionHtml": description_html,
        "jobDescriptionText": html_to_text(description_html),
    }


def validate_search_url(search_url: str) -> None:
    parsed = urlparse(search_url)
    if parsed.scheme != "https" or parsed.netloc != "jobs.uber.com" or not parsed.path.startswith("/en/jobs"):
        raise ValueError("Uber search URL must be an https://jobs.uber.com/en/jobs/ URL")


async def fetch_pages_in_browser(
    search_url: str, max_pages: int, timeout_ms: int, headed: bool
) -> list[dict[str, Any]]:
    """Retrieve bounded API pages using cookies created only in this browser context."""
    try:
        from playwright.async_api import Error as PlaywrightError, async_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is required for Uber fetching. Run: python3 -m pip install -r requirements.txt "
            "then: python3 -m playwright install chromium"
        ) from error

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not headed)
            context = await browser.new_context(viewport={"width": 1440, "height": 900})
            page = await context.new_page()
            try:
                response = await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
                body = await page.content()
                if "Just a moment..." in body or "challenge-platform" in body:
                    raise RuntimeError("Uber Jobs displayed a Cloudflare verification challenge; retry with --headed later")
                if response is not None and response.status >= 400:
                    raise RuntimeError(f"Uber Jobs search page returned HTTP {response.status}")
                await page.wait_for_selector("a.js-view-job", timeout=timeout_ms)
                pages = await page.evaluate("""async ({ maxPages }) => {
                  const parameters = new URLSearchParams(location.search);
                  parameters.delete('page');
                  parameters.delete('pagesize');
                  const results = [];
                  for (let page = 1; page <= maxPages; page += 1) {
                    const query = new URLSearchParams(parameters);
                    query.set('page', String(page));
                    query.set('pagesize', '10');
                    const response = await fetch(`/api/jobs/search/?${query}`, {
                      credentials: 'same-origin',
                      headers: { Accept: 'application/json' },
                    });
                    if (!response.ok) throw new Error(`Uber API returned HTTP ${response.status} on page ${page}`);
                    const data = await response.json();
                    results.push(data);
                    if (!Array.isArray(data.jobs) || data.jobs.length === 0) break;
                  }
                  return results;
                }""", {"maxPages": max_pages})
                return [item for item in pages if isinstance(item, dict)]
            finally:
                await context.close()
                await browser.close()
    except PlaywrightError as error:
        raise RuntimeError(f"Uber browser fetch failed: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Uber public job-search URL, enclosed in quotes.")
    parser.add_argument("--max-pages", type=int, default=10, help="Maximum API pages to retrieve (default: 10).")
    parser.add_argument("--max-jobs", type=int, default=50, help="Maximum normalized jobs to write; 0 keeps all fetched jobs.")
    parser.add_argument("--timeout", type=int, default=60, help="Browser navigation/selector timeout in seconds.")
    parser.add_argument("--headed", action="store_true", help="Show Chromium; useful when diagnosing a verification challenge.")
    parser.add_argument("--output", type=Path, default=Path("uber_jobs.json"))
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-pages and timeout must be positive; max-jobs cannot be negative")
    try:
        validate_search_url(args.url)
        print(f"Opening Uber Careers in a temporary browser session (up to {args.max_pages} pages)...", file=sys.stderr)
        pages = asyncio.run(fetch_pages_in_browser(args.url, args.max_pages, args.timeout * 1000, args.headed))
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    jobs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for page_number, data in enumerate(pages, start=1):
        raw_jobs = data.get("jobs", [])
        if not isinstance(raw_jobs, list):
            print(f"Warning: Uber API page {page_number} had no jobs list", file=sys.stderr)
            continue
        print(f"Fetched Uber API page {page_number}: {len(raw_jobs)} listings", file=sys.stderr)
        for raw_job in raw_jobs:
            job = normalise_result(raw_job) if isinstance(raw_job, dict) else None
            if job is None or job["id"] in seen_ids:
                continue
            seen_ids.add(job["id"])
            jobs.append(job)
            if args.max_jobs and len(jobs) >= args.max_jobs:
                break
        if args.max_jobs and len(jobs) >= args.max_jobs:
            break

    output = {
        "source": "Uber Careers browser-session API",
        "retrieval": "Temporary Playwright browser context calling Uber's same-origin paginated jobs API",
        "input_url": args.url,
        "jobs_fetched": len(jobs),
        "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
