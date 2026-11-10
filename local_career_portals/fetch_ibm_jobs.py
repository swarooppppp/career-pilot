#!/usr/bin/env python3
"""Fetch IBM's filtered public search API, hydrating full JobPosting details."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

# The local collector routes all network I/O through its shared Chrome session.
import os as _transport_os
if _transport_os.environ.get("CAREER_PORTAL_TRANSPORT") == "browser":
    from portal_http import browser_urlopen as urlopen


from common import plain_text, write_snapshot

API = "https://www-api.ibm.com/search/api/v2"
DEFAULT_URL = "https://www.ibm.com/in-en/careers/search?field_keyword_08%5B0%5D=Software%20Engineering&field_keyword_18%5B0%5D=Professional&field_keyword_05%5B0%5D=India&sort=dcdate_desc"


def search_payload(url, offset, size):
    query = parse_qs(urlparse(url).query)
    filters = []
    for field in ("field_keyword_08", "field_keyword_18", "field_keyword_05"):
        values = query.get(field + "[0]", [])
        if values:
            filters.append({"terms": {field: values}})
    keyword = query.get("q", [""])[0]
    must = [{"simple_query_string": {"query": keyword, "fields": ["keywords^1", "body^1", "url^2", "description^2", "h1s_content^2", "title^3", "field_text_01"]}}] if keyword else []
    return {"appId": "careers", "scopes": ["careers2"], "query": {"bool": {"must": must}},
            "post_filter": {"bool": {"must": filters}}, "from": offset, "size": size,
            "sort": [{"dcdate": "desc"}, {"_score": "desc"}], "lang": "zz",
            "localeSelector": {}, "sm": {"query": keyword, "lang": "zz"},
            "_source": ["title", "url", "description", "field_keyword_19"]}


def job_schema(document):
    for raw in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, re.I | re.S):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        queue = payload if isinstance(payload, list) else [payload]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "JobPosting" and item.get("description"):
                return item
            queue.extend(item.get("@graph", []))
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "data/ibm_jobs.json")
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits, timeout, or delay")
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or parsed.netloc != "www.ibm.com" or not parsed.path.endswith("/careers/search"):
        parser.error("Expected an https://www.ibm.com/.../careers/search URL")
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json", "Accept": "application/json"}
    jobs, seen = [], set()
    browser = None
    with ExitStack() as stack:
        for page_number in range(args.max_pages):
            request = Request(API, data=json.dumps(search_payload(args.url, page_number * 30, 30)).encode(), headers=headers)
            with urlopen(request, timeout=args.timeout) as response:
                payload = json.load(response)
            hits = payload.get("hits", {}).get("hits")
            if not isinstance(hits, list) or payload.get("timed_out"):
                raise RuntimeError("IBM returned an incomplete or unexpected search response")
            for hit in hits:
                summary = hit["_source"]
                url = summary["url"]
                detail_url = urlparse(url)
                if detail_url.scheme != "https" or detail_url.netloc != "careers.ibm.com":
                    raise RuntimeError("Unexpected IBM detail host")
                ident = parse_qs(detail_url.query).get("jobId", [""])[0]
                if not ident or ident in seen:
                    continue
                seen.add(ident)
                with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=args.timeout) as response:
                    document = response.read().decode("utf-8", errors="replace")
                detail = job_schema(document)
                if not detail:
                    if browser is None:
                        from playwright.sync_api import sync_playwright
                        playwright = stack.enter_context(sync_playwright())
                        browser = playwright.chromium.launch(headless=True)
                        stack.callback(browser.close)
                        context = browser.new_context()
                        tab = context.new_page()
                    tab.goto(url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
                    tab.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=args.timeout * 1000)
                    detail = job_schema(tab.content())
                if not detail:
                    raise RuntimeError(f"IBM job {ident} is missing a full JobPosting description")
                epoch = (hit.get("sort") or [None])[0]
                date = detail.get("datePosted") or (datetime.fromtimestamp(epoch / 1000, timezone.utc).isoformat() if isinstance(epoch, (int, float)) else None)
                jobs.append({"id": ident, "title": summary["title"], "company": "IBM", "location": summary.get("field_keyword_19", ""),
                             "application_url": url, "posted_date": date, "jobDescriptionHtml": detail["description"],
                             "jobDescriptionText": plain_text(detail["description"])})
                if args.max_jobs and len(jobs) >= args.max_jobs:
                    break
                time.sleep(args.delay)
            if len(hits) < 30 or (args.max_jobs and len(jobs) >= args.max_jobs):
                break
    write_snapshot(args.output, jobs, source=API, input_url=args.url, sort="portal dcdate descending")
    print(f"IBM: wrote {len(jobs)} jobs to {args.output}")


if __name__ == "__main__":
    main()
