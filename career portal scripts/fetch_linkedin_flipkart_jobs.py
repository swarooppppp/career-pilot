#!/usr/bin/env python3
"""Fetch publicly visible Flipkart jobs from a LinkedIn company-filtered search.

This adapter uses only LinkedIn's anonymous, server-rendered job pages. It
does not log in or send cookies. If LinkedIn restricts this public surface,
disable the adapter rather than attempting to circumvent access controls.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


DEFAULT_URL = "https://www.linkedin.com/jobs/search?keywords=Flipkart%20Software%20Engineer&location=Worldwide&geoId=92000000&f_C=321062&activeFilter=f_C&position=1&pageNum=0"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
JOB_URL_RE = re.compile(r'href=["\'](https?://[^"\']+/jobs/view/[^"\'?]+)[^"\']*["\']', re.IGNORECASE)


class LinkedInRateLimitError(RuntimeError):
    """LinkedIn declined additional anonymous requests for this run."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


def canonical_url(url: str) -> str:
    parsed = urlsplit(html.unescape(url))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def fetch_text(url: str, timeout: int, attempts: int = 3) -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
        except HTTPError as error:
            if error.code == 429:
                try:
                    retry_after = int(error.headers.get("Retry-After", ""))
                except ValueError:
                    try:
                        retry_at = parsedate_to_datetime(error.headers.get("Retry-After", ""))
                        if retry_at.tzinfo is None:
                            retry_at = retry_at.replace(tzinfo=timezone.utc)
                        retry_after = max(0, int((retry_at - datetime.now(timezone.utc)).total_seconds()))
                    except (TypeError, ValueError, IndexError):
                        retry_after = None
                raise LinkedInRateLimitError("LinkedIn rate-limited this run (HTTP 429)", retry_after) from error
            if error.code == 403:
                raise RuntimeError(f"LinkedIn restricted anonymous access (HTTP {error.code})") from error
            if attempt == attempts:
                raise RuntimeError(f"LinkedIn returned HTTP {error.code} from {url}") from error
        except URLError as error:
            if attempt == attempts:
                raise RuntimeError(f"Could not reach LinkedIn: {error.reason}") from error
        sleep(attempt)
    raise RuntimeError("LinkedIn request failed")


def extract_job_urls(page_html: str) -> list[str]:
    return list(dict.fromkeys(canonical_url(match.group(1)) for match in JOB_URL_RE.finditer(page_html)))


class JobPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.company = ""
        self.location = ""
        self.posted_date = ""
        self.description_parts: list[str] = []
        self._capture: str | None = None
        self._capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self._capture:
            self._capture_depth += 1
        if "topcard__title" in classes:
            self._capture, self._capture_depth = "title", 1
        elif "topcard__org-name-link" in classes:
            self._capture, self._capture_depth = "company", 1
        elif "topcard__flavor--bullet" in classes and not self.location:
            self._capture, self._capture_depth = "location", 1
        elif "posted-time-ago__text" in classes:
            self._capture, self._capture_depth = "posted_date", 1
        elif "show-more-less-html__markup" in classes:
            self._capture, self._capture_depth = "description", 1
        if self._capture == "description" and tag in {"br", "p", "li", "h1", "h2", "h3", "h4"}:
            self.description_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if not self._capture:
            return
        self._capture_depth -= 1
        if self._capture_depth == 0:
            self._capture = None

    def handle_data(self, data: str) -> None:
        if not self._capture:
            return
        if self._capture == "description":
            self.description_parts.append(data)
        elif self._capture == "title":
            self.title += data
        elif self._capture == "company":
            self.company += data
        elif self._capture == "location":
            self.location += data
        elif self._capture == "posted_date":
            self.posted_date += data

    def job(self, url: str) -> dict[str, str] | None:
        job_id_match = re.search(r"-(\d+)$", urlsplit(url).path)
        description = "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.description_parts).splitlines()) if line)
        job_id = job_id_match.group(1) if job_id_match else ""
        title, company, location = self.title.strip(), self.company.strip(), self.location.strip()
        if not job_id or not title or not company or not description:
            return None
        return {"id": job_id, "title": title, "company": company, "location": location, "application_url": url, "posted_date": self.posted_date.strip(), "jobDescriptionText": description}


def parse_job_page(page_html: str, url: str) -> dict[str, str] | None:
    parser = JobPageParser()
    parser.feed(page_html)
    parser.close()
    return parser.job(url)


def job_id_from_url(url: str) -> str:
    match = re.search(r"-(\d+)$", urlsplit(url).path)
    return match.group(1) if match else ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="LinkedIn public job-search URL filtered to Flipkart")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=Path("flipkart_jobs.json"))
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("max-jobs and delay cannot be negative; timeout must be positive")
    try:
        skip_ids = set(args.skip_job_id)
        urls = [url for url in extract_job_urls(fetch_text(args.url, args.timeout)) if job_id_from_url(url) not in skip_ids]
        if args.max_jobs:
            urls = urls[:args.max_jobs]
        jobs: list[dict[str, str]] = []
        for number, url in enumerate(urls, start=1):
            print(f"Fetching LinkedIn Flipkart job {number}/{len(urls)}: {url}", file=sys.stderr)
            job = parse_job_page(fetch_text(url, args.timeout), url)
            if job and job["company"].casefold() == "flipkart":
                jobs.append(job)
            if args.delay and number < len(urls):
                sleep(args.delay)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"source": "LinkedIn anonymous public job pages", "retrieval": "Server-rendered Flipkart-filtered LinkedIn search plus public job details; no login or cookies", "input_url": args.url, "jobs_fetched": len(jobs), "jobs": jobs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Flipkart jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
