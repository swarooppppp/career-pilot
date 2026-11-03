#!/usr/bin/env python3
"""Fetch jobs from a filtered Nutanix Careers URL using its public web page."""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, async_playwright


BASE = "https://careers.nutanix.com"
DEFAULT_URL = "https://careers.nutanix.com/en/jobs/?search=&country=India&team=Engineering&type=Full-Time&pagesize=20"


class BrowserAccessRequired(RuntimeError):
    pass


def posting(document: str) -> dict:
    for payload in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, re.I | re.S):
        try:
            values = json.loads(html.unescape(payload))
        except json.JSONDecodeError:
            continue
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, dict) and value.get("@type") == "JobPosting" and value.get("description"):
                return value
    raise RuntimeError("Nutanix detail page lacks a public JobPosting description")


def description(document: str) -> str:
    return str(posting(document)["description"])


def locations(value) -> str:
    if isinstance(value, dict):
        value = [value]
    results = []
    for item in value or []:
        address = item.get("address") or {}
        country = address.get("addressCountry") or ""
        if isinstance(country, dict):
            country = country.get("name", "")
        if country == "IN":
            country = "India"
        results.append(", ".join(str(x) for x in [address.get("addressLocality"), address.get("addressRegion"), country] if x))
    return " | ".join(results)


def text_from_html(value: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())


async def fetch_jobs(url: str, max_jobs: int, timeout: int, skip_ids: set[str], headed: bool) -> list[dict]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=not headed, args=["--start-minimized"] if headed else [])
        page = await browser.new_page()
        navigation_timeout = min(timeout, 15) * 1000
        page.set_default_timeout(navigation_timeout)
        try:
            if headed:
                session = await page.context.new_cdp_session(page)
                window = await session.send("Browser.getWindowForTarget")
                await session.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "minimized"}})
            # The careers site keeps analytics connections open, so networkidle
            # never settles even though the server-rendered job links are ready.
            response = await page.goto(url, wait_until="domcontentloaded", timeout=navigation_timeout)
            if response is not None and response.status == 403:
                raise BrowserAccessRequired("Nutanix rejected this browser session (HTTP 403); verification may be required")
            if response is not None and response.status >= 400:
                raise RuntimeError(f"Nutanix returned HTTP {response.status}; no immediate retry")
            await page.locator('a[href*="/en/jobs/"]').first.wait_for(state="attached", timeout=5_000)
            links = await page.locator('a[href*="/en/jobs/"]').evaluate_all(
                "elements => elements.map(element => ({href: element.getAttribute('href'), title: element.textContent.trim()}))"
            )
            seen: set[str] = set()
            summaries = []
            for link in links:
                href = str(link.get("href") or "")
                match = re.fullmatch(r"/en/jobs/(\d+)/[^/]+/?", href)
                if not match or match.group(1) in seen:
                    continue
                seen.add(match.group(1))
                summaries.append((match.group(1), str(link.get("title") or "").strip(), urljoin(BASE, href)))
            jobs = []
            for job_id, title, detail_url in summaries[:max_jobs or None]:
                if job_id in skip_ids:
                    print(f"Skipping existing: {job_id}", file=sys.stderr)
                    continue
                print(f"Fetching Nutanix job: {job_id}", file=sys.stderr)
                await page.goto(detail_url, wait_until="domcontentloaded", timeout=navigation_timeout)
                schema = posting(await page.content())
                detail = str(schema["description"])
                jobs.append({"id": job_id, "title": title, "company": "Nutanix", "application_url": detail_url,
                             "location": locations(schema.get("jobLocation")), "posted_date": schema.get("datePosted"),
                             "jobDescriptionHtml": detail, "jobDescriptionText": text_from_html(detail)})
            return jobs
        finally:
            await browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--headed", action="store_true", help="Show the browser while fetching")
    parser.add_argument("--headed-fallback", action="store_true", help="After a headless HTTP 403, try headed once with its dedicated window minimized before navigation")
    parser.add_argument("--output", type=Path, default=Path("nutanix_jobs.json"))
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-jobs cannot be negative and timeout must be positive")
    try:
        try:
            jobs = asyncio.run(fetch_jobs(args.url, args.max_jobs, args.timeout, set(args.skip_job_id), args.headed))
        except BrowserAccessRequired:
            if args.headed or not args.headed_fallback:
                raise
            print("Nutanix rejected headless access; trying one minimized headed session.", file=sys.stderr)
            jobs = asyncio.run(fetch_jobs(args.url, args.max_jobs, args.timeout, set(args.skip_job_id), True))
    except (RuntimeError, PlaywrightError, PlaywrightTimeoutError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"source": "Nutanix public careers pages", "input_url": args.url, "jobs": jobs}, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Nutanix jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
