#!/usr/bin/env python3
"""Fetch a provided LinkedIn public job-search group into Career Pilot JSON.

Only anonymous, server-rendered LinkedIn pages are read. The adapter does not
log in or send cookies; disable it if LinkedIn restricts this public surface.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from random import uniform
from time import sleep
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


SIBLING = Path(__file__).with_name("fetch_linkedin_flipkart_jobs.py")
SPEC = importlib.util.spec_from_file_location("linkedin_public_parser", SIBLING)
assert SPEC and SPEC.loader
linkedin = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = linkedin
SPEC.loader.exec_module(linkedin)


def scroll_page_url(search_url: str, start: int) -> str:
    """Build the same offset request LinkedIn issues after scrolling."""
    parsed = urlsplit(search_url)
    if parsed.scheme != "https" or not parsed.netloc.endswith("linkedin.com") or parsed.path != "/jobs/search":
        raise ValueError("LinkedIn URL must be an https://*.linkedin.com/jobs/search URL")
    parameters = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "start"]
    parameters.append(("start", str(start)))
    return urlunsplit((parsed.scheme, parsed.netloc, "/jobs-guest/jobs/api/seeMoreJobPostings/search", urlencode(parameters), ""))


def retry_delay(error: linkedin.LinkedInRateLimitError, retry_number: int, initial_seconds: float, max_seconds: float) -> tuple[float, bool]:
    """Return the capped exponential delay, preferring a valid Retry-After."""
    exponential = min(initial_seconds * (2 ** (retry_number - 1)), max_seconds)
    retry_after = getattr(error, "retry_after", None)
    if retry_after is not None and retry_after >= 0:
        return min(float(retry_after), max_seconds), True
    return exponential, False


def fetch_with_429_retries(fetch, label: str, retries: int, initial_seconds: float, max_seconds: float) -> str:
    """Retry one public LinkedIn request, preserving caller state between tries."""
    for retry_number in range(1, retries + 2):
        try:
            return fetch()
        except linkedin.LinkedInRateLimitError as error:
            if retry_number > retries:
                raise
            seconds, used_retry_after = retry_delay(error, retry_number, initial_seconds, max_seconds)
            suffix = " (Retry-After)" if used_retry_after else ""
            print(f"LinkedIn rate-limited {label}; retry {retry_number}/{retries} in {seconds:g}s{suffix}.", file=sys.stderr)
            sleep(seconds)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="LinkedIn public job-search URL")
    parser.add_argument("--max-pages", type=int, default=20, help="Maximum search-result pages, including the initial page")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--min-delay", type=float, default=None, help="Minimum randomized delay between detail requests")
    parser.add_argument("--max-delay", type=float, default=None, help="Maximum randomized delay between detail requests")
    parser.add_argument("--429-max-retries", type=int, default=10)
    parser.add_argument("--429-initial-backoff-seconds", type=float, default=60)
    parser.add_argument("--429-max-backoff-seconds", type=float, default=480)
    parser.add_argument("--output", type=Path, default=Path("linkedin_jobs.json"))
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_jobs < 0 or args.timeout < 1 or args.delay < 0 or args.__dict__["429_max_retries"] < 0 or args.__dict__["429_initial_backoff_seconds"] < 0 or args.__dict__["429_max_backoff_seconds"] < 0:
        parser.error("max-pages and timeout must be positive; max-jobs and delay cannot be negative")
    if (args.min_delay is None) != (args.max_delay is None):
        parser.error("min-delay and max-delay must be provided together")
    delay_min = args.min_delay if args.min_delay is not None else args.delay
    delay_max = args.max_delay if args.max_delay is not None else args.delay
    retry_count = args.__dict__["429_max_retries"]
    initial_backoff = args.__dict__["429_initial_backoff_seconds"]
    max_backoff = args.__dict__["429_max_backoff_seconds"]
    if delay_min < 0 or delay_max < delay_min:
        parser.error("delay values must be non-negative and max-delay must be at least min-delay")
    if max_backoff < initial_backoff:
        parser.error("429 max backoff must be at least the initial backoff")
    rate_limited = False
    pages_fetched = 0
    jobs = []
    urls = []
    try:
        skip_ids = set(args.skip_job_id)
        urls = linkedin.extract_job_urls(fetch_with_429_retries(lambda: linkedin.fetch_text(args.url, args.timeout), "initial search", retry_count, initial_backoff, max_backoff))
        pages_fetched = 1
        for page in range(1, args.max_pages):
            if args.max_jobs and len([url for url in urls if linkedin.job_id_from_url(url) not in skip_ids]) >= args.max_jobs:
                break
            if delay_max:
                sleep(uniform(delay_min, delay_max))
            offset = page * 25
            print(f"Fetching LinkedIn search page {page + 1}: start={offset}", file=sys.stderr)
            try:
                page_urls = linkedin.extract_job_urls(fetch_with_429_retries(lambda: linkedin.fetch_text(scroll_page_url(args.url, offset), args.timeout), f"search page {page + 1}", retry_count, initial_backoff, max_backoff))
            except linkedin.LinkedInRateLimitError:
                rate_limited = True
                print("LinkedIn exhausted retries for search pagination; continuing with previously discovered jobs.", file=sys.stderr)
                break
            pages_fetched += 1
            if not page_urls:
                break
            urls = list(dict.fromkeys([*urls, *page_urls]))
        urls = [url for url in urls if linkedin.job_id_from_url(url) not in skip_ids]
        if args.max_jobs:
            urls = urls[:args.max_jobs]
        for number, url in enumerate(urls, start=1):
            print(f"Fetching LinkedIn job {number}/{len(urls)}: {url}", file=sys.stderr)
            try:
                job = linkedin.parse_job_page(fetch_with_429_retries(lambda: linkedin.fetch_text(url, args.timeout), f"job detail {number}/{len(urls)}", retry_count, initial_backoff, max_backoff), url)
            except linkedin.LinkedInRateLimitError:
                rate_limited = True
                print(
                    f"LinkedIn rate-limited this run after {len(jobs)} jobs; saving a partial snapshot for the next sync.",
                    file=sys.stderr,
                )
                break
            if job:
                jobs.append(job)
            if delay_max and number < len(urls):
                sleep(uniform(delay_min, delay_max))
    except linkedin.LinkedInRateLimitError:
        rate_limited = True
        print("LinkedIn exhausted retries for the initial search; saving a partial snapshot.", file=sys.stderr)
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "source": "LinkedIn anonymous public job pages",
        "retrieval": "Server-rendered public search group plus public job details; no login or cookies",
        "input_url": args.url,
        "pages_fetched": pages_fetched,
        "jobs_fetched": len(jobs),
        "complete": not rate_limited,
        "stopped_reason": "rate_limited" if rate_limited else None,
        "jobs": jobs,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = "partial" if rate_limited else "complete"
    print(f"Wrote {state} snapshot with {len(jobs)} LinkedIn jobs from {pages_fetched} pages to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
