#!/usr/bin/env python3
"""Fetch Uber job listings through an isolated browser session.

Uber's careers API sometimes presents a Cloudflare challenge to direct Python
HTTP clients. This adapter opens the public search page and makes the same-
origin API requests from a dedicated browser context. An optional profile retains its own cookies;
it never reads the user's regular browser profile.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import signal
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
    search_url: str, max_pages: int, timeout_ms: int, headed: bool,
    profile: Path | None = None, diagnostics: Path | None = None,
    minimized: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve bounded API pages; optional persistent profiles require an external lock."""
    try:
        from playwright.async_api import Error as PlaywrightError, async_playwright
    except ImportError as error:
        raise RuntimeError(
            "Playwright is required for Uber fetching. Run: python3 -m pip install -r requirements.txt "
            "then: python3 -m playwright install chromium"
        ) from error

    try:
        async with async_playwright() as playwright:
            browser = None
            if profile:
                profile.mkdir(parents=True, exist_ok=True, mode=0o700)
                context = await playwright.chromium.launch_persistent_context(
                    str(profile.resolve()), headless=not headed,
                    viewport={"width": 1440, "height": 900},
                    **({"args": ["--start-minimized"]} if minimized else {}),
                )
            else:
                browser = await playwright.chromium.launch(headless=not headed, **({"args": ["--start-minimized"]} if minimized else {}))
                context = await browser.new_context(viewport={"width": 1440, "height": 900})
            page = None
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                if minimized:
                    session = await context.new_cdp_session(page)
                    window = await session.send("Browser.getWindowForTarget")
                    await session.send("Browser.setWindowBounds", {"windowId": window["windowId"], "bounds": {"windowState": "minimized"}})
                response = await page.goto(search_url, wait_until="domcontentloaded", timeout=timeout_ms)
                body = await page.content()
                if "Just a moment..." in body or "challenge-platform" in body:
                    raise RuntimeError("Uber Jobs requires manual verification; scheduled execution stopped without attempting the challenge")
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
            except Exception as error:
                if diagnostics:
                    import traceback
                    diagnostics.mkdir(parents=True, exist_ok=True, mode=0o700)
                    frames = traceback.extract_tb(error.__traceback__)
                    (diagnostics / "error.json").write_text(json.dumps({
                        "exception": type(error).__name__,
                        "frames": [{"file": f.filename, "line": f.lineno, "function": f.name} for f in frames],
                    }, indent=2))
                if diagnostics and page:
                    diagnostics.mkdir(parents=True, exist_ok=True, mode=0o700)
                    try:
                        await page.screenshot(path=str(diagnostics / "failure.png"), timeout=5000)
                    except Exception:
                        pass
                raise
            finally:
                await context.close()
                if browser:
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
    parser.add_argument("--minimized", action="store_true", help="With --headed, minimize this dedicated browser window before navigation")
    parser.add_argument("--output", type=Path, default=Path("uber_jobs.json"))
    parser.add_argument("--profile", type=Path, help="Dedicated persistent profile; caller must serialize access.")
    parser.add_argument("--diagnostics", type=Path, help="Private failure screenshot directory.")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, lambda *_: os.kill(os.getpid(), signal.SIGINT))
    os.umask(0o077)
    # A detached worker must not survive a crashed supervisor indefinitely.
    parent_pid = os.environ.get("UBER_SUPERVISOR_PID")
    if parent_pid:
        import threading
        import time
        def watch_parent():
            while os.getppid() == int(parent_pid):
                time.sleep(1)
            os.kill(os.getpid(), signal.SIGTERM)
        threading.Thread(target=watch_parent, daemon=True).start()
    if args.max_pages < 1 or args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-pages and timeout must be positive; max-jobs cannot be negative")
    if args.minimized and not args.headed:
        parser.error("--minimized requires --headed")
    try:
        validate_search_url(args.url)
        print(f"Opening Uber Careers in a dedicated browser session (up to {args.max_pages} pages)...", file=sys.stderr)
        options = {"minimized": True} if args.minimized else {}
        pages = asyncio.run(fetch_pages_in_browser(args.url, args.max_pages, args.timeout * 1000, args.headed, args.profile, args.diagnostics, **options))
    except (RuntimeError, ValueError) as error:
        if "requires manual verification" in str(error):
            print("MANUAL_VERIFICATION_REQUIRED: Uber challenge detected; no challenge attempted.", file=sys.stderr)
        else:
            print(f"Error ({type(error).__name__}): Uber fetch failed; inspect private diagnostics or run manually.", file=sys.stderr)
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
        "retrieval": "Dedicated Playwright browser context calling Uber's same-origin paginated jobs API",
        "input_url": args.url,
        "jobs_fetched": len(jobs),
        "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(args.output)
    print(f"Wrote {len(jobs)} jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
