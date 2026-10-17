#!/usr/bin/env python3
"""Fetch Adobe Careers results and hydrate them into Career Pilot job records.

Adobe server-renders both category/search results and individual job details in
the public ``phApp.ddo`` JSON object. No browser is required.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_URL = "https://careers.adobe.com/us/en/c/engineering-and-product-jobs?from=10&s=1"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilotAdobeFetcher/1.0)"


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


def page_url(search_url: str, offset: int) -> str:
    """Set Adobe's server-rendered offset without changing other URL filters."""
    parsed = urlparse(search_url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "from"]
    query.append(("from", str(offset)))
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def fetch_html(url: str, timeout: int) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as error:
        raise RuntimeError(f"Adobe returned HTTP {error.code} for {url}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Adobe Careers: {error.reason}") from error


def embedded_data(html_document: str, key: str) -> dict[str, Any]:
    marker = "phApp.ddo = "
    if marker not in html_document:
        raise RuntimeError("Adobe's embedded job data was not found")
    try:
        data, _ = json.JSONDecoder().raw_decode(html_document.split(marker, 1)[1])
        result = data[key]
    except (KeyError, json.JSONDecodeError) as error:
        raise RuntimeError("Adobe's embedded job data could not be parsed") from error
    if not isinstance(result, dict):
        raise RuntimeError("Adobe's embedded job data had an unexpected shape")
    return result


def fetch_search_page(url: str, timeout: int) -> dict[str, Any]:
    return embedded_data(fetch_html(url, timeout), "eagerLoadRefineSearch")


def job_url(job_id: str, title: str) -> str:
    slug = quote(title.replace(" ", "-"), safe="-")
    return f"https://careers.adobe.com/us/en/job/{quote(job_id, safe='')}/{slug}"


def fetch_detail(job_id: str, title: str, timeout: int) -> dict[str, Any]:
    result = embedded_data(fetch_html(job_url(job_id, title), timeout), "jobDetail")
    job = result.get("data", {}).get("job")
    if not isinstance(job, dict):
        raise RuntimeError(f"Adobe detail response did not contain job {job_id}")
    return job


def normalise_job(summary: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(detail.get("reqId") or summary.get("reqId") or summary.get("jobId") or "").strip()
    title = str(detail.get("title") or summary.get("title") or "").strip()
    description_html = str(detail.get("description") or "").strip()
    if not job_id or not title or not description_html:
        return None
    location = str(detail.get("location") or detail.get("cityStateCountry") or summary.get("location") or "").strip()
    return {"id": job_id, "title": title, "company": "Adobe", "location": location,
            "application_url": str(detail.get("applyUrl") or job_url(job_id, title)),
            "posted_date": detail.get("postedDate") or summary.get("postedDate"),
            "jobDescriptionHtml": description_html, "jobDescriptionText": html_to_text(description_html)}


def fetch_jobs(search_url: str, max_jobs: int, timeout: int, delay: float, skip_ids: set[str]) -> list[dict[str, Any]]:
    first = fetch_search_page(page_url(search_url, 0), timeout)
    page_jobs = first.get("data", {}).get("jobs", [])
    if not isinstance(page_jobs, list) or not page_jobs:
        return []
    jobs_per_page = int(first.get("hits") or len(page_jobs))
    total = int(first.get("totalHits") or jobs_per_page)
    summaries = list(page_jobs)
    desired = min(total, max_jobs) if max_jobs else total
    for offset in range(jobs_per_page, desired, jobs_per_page):
        summaries.extend(fetch_search_page(page_url(search_url, offset), timeout).get("data", {}).get("jobs", []))
    summaries = summaries[:desired]
    jobs: list[dict[str, Any]] = []
    for index, summary in enumerate(summaries, start=1):
        job_id, title = str(summary.get("reqId") or summary.get("jobId") or "").strip(), str(summary.get("title") or "").strip()
        if not job_id or not title:
            continue
        if job_id in skip_ids:
            print(f"Skipping existing {index}/{len(summaries)}: {job_id}", file=sys.stderr)
            continue
        print(f"Fetching {index}/{len(summaries)}: {job_id}", file=sys.stderr)
        result = normalise_job(summary, fetch_detail(job_id, title, timeout))
        if result is not None:
            jobs.append(result)
        if index != len(summaries):
            time.sleep(delay)
    return list({job["id"]: job for job in jobs}.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Adobe Careers category or search URL")
    parser.add_argument("--max-jobs", type=int, default=50, help="Maximum jobs to fetch; 0 fetches every result")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between detail requests")
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("adobe_jobs.json"))
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("max-jobs and delay cannot be negative; timeout must be positive")
    if parsed.scheme != "https" or parsed.netloc != "careers.adobe.com":
        parser.error("url must be an https://careers.adobe.com URL")
    try:
        jobs = fetch_jobs(args.url, args.max_jobs, args.timeout, args.delay, set(args.skip_job_id))
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    output = {"source": "Adobe Careers public server-rendered data", "retrieval": "Public category/search results plus public job-detail pages",
              "input_url": args.url, "jobs_fetched": len(jobs), "jobs": jobs}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Adobe jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
