#!/usr/bin/env python3
"""Fetch Meta Careers results through an isolated browser session.

Meta's search GraphQL requests depend on short-lived browser tokens. This
adapter uses the public search and detail pages in a temporary Playwright
context, without copying a user's existing browser session or its cookies.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


DEFAULT_URL = "https://www.metacareers.com/jobsearch/?sort_by_new=true"
JOB_LINK_SELECTOR = 'a[href^="/profile/job_details/"]'


async def page_jobs(page: Any) -> list[dict[str, str]]:
    jobs = await page.locator(JOB_LINK_SELECTOR).evaluate_all("""links =>
      links.map(link => ({
        title: link.querySelector('h3')?.innerText.trim() || link.innerText.trim().split('\\n')[0],
        job_url: new URL(link.getAttribute('href'), location.origin).href,
        card_text: link.innerText.trim(),
      }))
    """)
    return [job for job in jobs if isinstance(job, dict) and job.get("job_url")]


async def advance(page: Any) -> bool:
    """Click the enabled next control adjacent to Meta's page-status text."""
    buttons = page.locator("button:not([disabled])")
    for index in range(await buttons.count()):
        button = buttons.nth(index)
        context = await button.evaluate("button => button.parentElement?.innerText || ''")
        if "Page " in context and " of " in context:
            await button.click()
            await page.wait_for_timeout(1200)
            return True
    return False


def external_id(job_url: str) -> str:
    parsed = urlparse(job_url)
    match = re.search(r"/profile/job_details/(?:[^/]+/)?([^/?#]+)", parsed.path)
    return match.group(1) if match else parse_qs(parsed.query).get("id", [""])[0]


def normalise_result(job: dict[str, str]) -> dict[str, Any] | None:
    job_id = external_id(job.get("job_url", ""))
    title = str(job.get("title") or "").strip()
    description_text = str(job.get("description_text") or "").strip()
    if not job_id or not title or not description_text:
        return None
    return {
        "id": job_id,
        "title": title,
        "company": "Meta",
        "location": "",  # The card text remains in the raw snapshot; Meta does not expose a stable location selector.
        "application_url": job["job_url"],
        "posted_date": None,
        "jobDescriptionHtml": f"<pre>{html.escape(description_text)}</pre>",
        "jobDescriptionText": description_text,
    }


async def extract(search_url: str, max_pages: int, max_jobs: int, include_details: bool, headed: bool) -> list[dict[str, str]]:
    try:
        from playwright.async_api import Error as PlaywrightError, async_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is required for Meta fetching. Run: python3 -m pip install -r requirements.txt "
            "then: python3 -m playwright install chromium"
        ) from error
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=not headed)
            context = await browser.new_context(viewport={"width": 1440, "height": 1000})
            page = await context.new_page()
            try:
                response = await page.goto(search_url, wait_until="domcontentloaded", timeout=60_000)
                if response is not None and response.status >= 400:
                    raise RuntimeError(f"Meta Careers search page returned HTTP {response.status}")
                # An empty current filter is valid. Give the client-side results
                # time to render, then continue with an empty snapshot if needed.
                await page.wait_for_timeout(1500)
                jobs: list[dict[str, str]] = []
                seen: set[str] = set()
                for _ in range(max_pages):
                    for job in await page_jobs(page):
                        if job["job_url"] not in seen:
                            seen.add(job["job_url"])
                            jobs.append(job)
                        if max_jobs and len(jobs) >= max_jobs:
                            break
                    if (max_jobs and len(jobs) >= max_jobs) or not await advance(page):
                        break
                if include_details and jobs:
                    detail_page = await context.new_page()
                    try:
                        for number, job in enumerate(jobs, start=1):
                            print(f"Fetching Meta job {number}/{len(jobs)}: {job['job_url']}", file=sys.stderr)
                            await detail_page.goto(job["job_url"], wait_until="domcontentloaded", timeout=60_000)
                            await detail_page.wait_for_timeout(500)
                            job["description_text"] = await detail_page.locator("main").inner_text()
                    finally:
                        await detail_page.close()
                return jobs
            finally:
                await context.close()
                await browser.close()
    except PlaywrightError as error:
        raise RuntimeError(f"Meta browser fetch failed: {error}") from error


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Meta Careers public search URL")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--skip-details", action="store_true", help="Write search cards only; not importable without descriptions.")
    parser.add_argument("--headed", action="store_true", help="Show Chromium while fetching.")
    parser.add_argument("--output", type=Path, default=Path("meta_jobs.json"))
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_jobs < 0:
        parser.error("max-pages must be positive and max-jobs cannot be negative")
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or parsed.netloc != "www.metacareers.com" or parsed.path != "/jobsearch/":
        parser.error("url must be an https://www.metacareers.com/jobsearch/ URL")
    try:
        raw_jobs = asyncio.run(extract(args.url, args.max_pages, args.max_jobs, not args.skip_details, args.headed))
    except RuntimeError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    jobs = [result for job in raw_jobs if (result := normalise_result(job)) is not None]
    output = {
        "source": "Meta Careers browser-session public pages",
        "retrieval": "Temporary Playwright browser context using Meta public search and detail pages",
        "input_url": args.url,
        "raw_cards_fetched": len(raw_jobs),
        "jobs_fetched": len(jobs),
        "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not raw_jobs:
        print("Meta returned no jobs for this filter; wrote a valid empty snapshot.", file=sys.stderr)
    else:
        print(f"Wrote {len(jobs)} Meta jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
