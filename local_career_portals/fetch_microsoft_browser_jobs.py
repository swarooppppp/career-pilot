#!/usr/bin/env python3
"""Fetch Microsoft careers in one headless session with detail caching and cooldowns."""
import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import fcntl
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from common import write_snapshot
from filters import in_india

HERE = Path(__file__).resolve().parent
DEFAULT_URL = "https://apply.careers.microsoft.com/careers?query=Software+Engineering&start=0&location=India&sort_by=timestamp&filter_include_remote=1&filter_include_relocation=0&filter_profession=software+engineering&filter_seniority=Mid-Level%2CSenior%2CEntry"
SPEC = importlib.util.spec_from_file_location("microsoft_existing_parser", HERE.parent / "career portal scripts/fetch_microsoft_jobs.py")
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


class CooldownRequired(RuntimeError):
    pass


def retry_seconds(value, now, fallback=60):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - now
        except (TypeError, ValueError, OverflowError):
            seconds = fallback
    return max(0, seconds) if math.isfinite(seconds) else fallback


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False) + "\n")
    temporary.replace(path)


def cache_valid(entry, summary, now, ttl):
    return bool(entry and entry.get("postedTs") == summary.get("postedTs")
                and entry.get("name") == summary.get("name")
                and now - entry.get("fetched_at", 0) < ttl
                and entry.get("job", {}).get("jobDescriptionHtml"))


class BrowserClient:
    def __init__(self, page, args, state):
        self.page, self.args, self.state = page, args, state
        self.last_request = time.monotonic()
        self.requests = 1  # Initial browser search, reused rather than repeated.

    def cooldown(self, header, attempt):
        now = time.time()
        seconds = retry_seconds(header, now, fallback=60 * (2 ** attempt))
        self.state["cooldown_until"] = now + seconds
        save_state(self.args.state_file, self.state)
        if attempt >= self.args.max_retries or seconds > self.args.max_retry_wait:
            raise CooldownRequired(f"Microsoft HTTP 429; next attempt after {datetime.fromtimestamp(now + seconds, timezone.utc).isoformat()}")
        print(f"Microsoft requested a {seconds:g}s cooldown; bounded retry follows.", flush=True)
        time.sleep(seconds)

    def get_json(self, path, params, *unused):
        url = adapter.BASE_URL + path + "?" + urlencode(params, doseq=True)
        for attempt in range(self.args.max_retries + 1):
            time.sleep(max(0, self.args.delay - (time.monotonic() - self.last_request)))
            self.last_request = time.monotonic()
            self.requests += 1
            response = self.page.evaluate("""async ({url, timeout}) => {
                const response = await fetch(url, {credentials: 'same-origin',
                    headers: {Accept: 'application/json'}, signal: AbortSignal.timeout(timeout)});
                return {status: response.status, retryAfter: response.headers.get('Retry-After'), text: await response.text()};
            }""", {"url": url, "timeout": self.args.timeout * 1000})
            if response["status"] == 429:
                self.cooldown(response["retryAfter"], attempt)
                continue
            if response["status"] != 200:
                raise RuntimeError(f"Microsoft {path} returned HTTP {response['status']}")
            payload = json.loads(response["text"])
            if payload.get("status") == 429:
                self.cooldown(response["retryAfter"], attempt)
                continue
            if payload.get("status") != 200 or not isinstance(payload.get("data"), dict):
                raise RuntimeError("Unexpected Microsoft API response")
            return payload["data"]
        raise CooldownRequired("Microsoft retry limit reached")


def configure_url(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != "apply.careers.microsoft.com" or parsed.path != "/careers":
        raise ValueError("Expected Microsoft's https://apply.careers.microsoft.com/careers URL")
    query = parse_qs(parsed.query)
    query.pop("pid", None)  # A selected job, not a search constraint; avoids needless hydration.
    query["start"] = ["0"]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), "")), query


def fetch(args, state):
    from playwright.sync_api import sync_playwright
    url, query = configure_url(args.url)
    namespace = argparse.Namespace(query=query.get("query", [""])[0], location=query.get("location", ["India"])[0],
        sort_by=query.get("sort_by", ["timestamp"])[0], profession=query.get("filter_profession", [""])[0],
        seniority=",".join(query.get("filter_seniority", [])), role_type="", employment_type="",
        include_remote=query.get("filter_include_remote", ["1"])[0] == "1",
        include_relocation=query.get("filter_include_relocation", ["0"])[0] == "1",
        timeout=args.timeout, max_retries=args.max_retries, backoff_seconds=60, locale="en")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            with page.expect_response(lambda response: "/api/pcsx/search?" in response.url, timeout=args.timeout * 1000) as initial:
                navigation = page.goto(url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
                if navigation is not None and navigation.status == 429:
                    BrowserClient(page, args, state).cooldown(navigation.headers.get("retry-after"), args.max_retries)
            response = initial.value
            client = BrowserClient(page, args, state)
            if response.status == 429:
                client.cooldown(response.headers.get("retry-after"), args.max_retries)
            if response.status != 200:
                raise RuntimeError(f"Microsoft initial search returned HTTP {response.status}")
            sent = parse_qs(urlsplit(response.url).query)
            for key in ("query", "location", "sort_by", "filter_profession"):
                if sent.get(key) != query.get(key):
                    raise RuntimeError(f"Microsoft initial search did not apply {key}")
            expected_seniority = set(namespace.seniority.split(",")) - {""}
            if set(sent.get("filter_seniority", [])) != expected_seniority:
                raise RuntimeError("Microsoft initial search did not apply selected seniorities")
            payload = response.json()
            if payload.get("status") == 429:
                client.cooldown(response.headers.get("retry-after"), args.max_retries)
            first = payload.get("data")
            if payload.get("status") != 200 or not isinstance(first, dict) or not isinstance(first.get("positions"), list):
                raise RuntimeError("Unexpected Microsoft initial search response")
            applied = first.get("appliedFilters") or {}
            required = {"includeRemote": ["1" if namespace.include_remote else "0"],
                        "includeRelocation": ["1" if namespace.include_relocation else "0"]}
            if namespace.profession:
                required["profession"] = [namespace.profession]
            if expected_seniority:
                required["seniority"] = list(expected_seniority)
            for key, values in required.items():
                if set(applied.get(key, [])) != set(values):
                    raise RuntimeError(f"Microsoft did not confirm the applied {key} filter")
            adapter.get_json = client.get_json
            total = int(first["count"])
            pages = min(args.max_pages, math.ceil(total / adapter.PAGE_SIZE))
            if args.max_jobs:
                pages = min(pages, math.ceil(args.max_jobs / adapter.PAGE_SIZE))
            summaries = list(first["positions"])
            for number in range(1, pages):
                summaries.extend(adapter.search_jobs(namespace, number * adapter.PAGE_SIZE).get("positions", []))
            summaries = list({str(job["id"]): job for job in summaries}.values())
            summaries = [job for job in summaries if in_india(job)]
            if args.max_jobs:
                summaries = summaries[:args.max_jobs]
            jobs, hits = [], 0
            for summary in summaries:
                ident = str(summary["id"])
                entry = state["details"].get(ident)
                if cache_valid(entry, summary, time.time(), args.cache_hours * 3600):
                    jobs.append(entry["job"])
                    hits += 1
                    continue
                detail = adapter.get_job_details(int(ident), namespace)
                description = detail.get("jobDescription") or ""
                if not description:
                    raise RuntimeError(f"Microsoft job {ident} is missing a full description")
                job = {**summary, **detail, "title": detail.get("name") or summary["name"], "company": "Microsoft",
                       "posted_date": datetime.fromtimestamp(summary["postedTs"], timezone.utc).isoformat() if summary.get("postedTs") else None,
                       "application_url": detail.get("publicUrl") or adapter.BASE_URL + detail.get("positionUrl", summary.get("positionUrl", "")),
                       "jobDescriptionHtml": description, "jobDescriptionText": adapter.html_to_text(description)}
                state["details"][ident] = {"job": job, "fetched_at": time.time(), "postedTs": summary.get("postedTs"), "name": summary.get("name")}
                save_state(args.state_file, state)
                jobs.append(job)
            write_snapshot(args.output, jobs, source=adapter.BASE_URL, input_url=args.url,
                           retrieval="Headless Chromium same-origin API with initial-search reuse and TTL detail cache",
                           total_results_reported_by_api=total, applied_filters=applied, api_requests=client.requests, cached_details_reused=hits)
            print(f"Microsoft: {len(jobs)} jobs; {client.requests} API requests; {hits} cached details reused", flush=True)
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--delay", type=float, default=1)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--cache-hours", type=float, default=24)
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--max-retry-wait", type=float, default=10)
    parser.add_argument("--state-file", type=Path, default=HERE / "data/microsoft_browser_state.json")
    parser.add_argument("--output", type=Path, default=HERE / "data/microsoft_jobs.json")
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_jobs < 0 or args.timeout < 1 or min(args.delay, args.cache_hours, args.max_retry_wait, args.max_retries) < 0:
        parser.error("Invalid limits, timing, or retry settings")
    args.state_file.parent.mkdir(parents=True, exist_ok=True)
    with args.state_file.with_suffix(".lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another Microsoft fetch is already running")
        state = json.loads(args.state_file.read_text()) if args.state_file.exists() else {"details": {}}
        if state.get("cooldown_until", 0) > time.time():
            raise CooldownRequired("Microsoft cooldown is still active; browser was not launched")
        fetch(args, state)


if __name__ == "__main__":
    try:
        main()
    except CooldownRequired as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(75)
