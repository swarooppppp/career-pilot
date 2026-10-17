#!/usr/bin/env python3
"""Fetch Capital One category jobs, optionally using the Bengaluru facet."""
from __future__ import annotations

import argparse, html, json, re, sys, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

DEFAULT_URL = "https://www.capitalonecareers.com/category/engineering-jobs/234/29016/1"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilotCapitalOneFetcher/1.0)"
BENGALURU_FACET_ID = "1269750-1267701-1277333"
BENGALURU_LABEL = "Bengaluru, Karnataka, India"

class JobsPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.jobs: list[dict[str, str]] = []; self.current: dict[str, str] | None = None; self.field = ""; self.pagination: list[str] = []; self.depth = 0
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "nav" and (values.get("aria-label", "").lower() == "pagination" or "pagination" in (values.get("class") or "").split()): self.depth = 1
        elif self.depth: self.depth += 1
        if tag == "a" and values.get("data-job-id"):
            self.current = {"id": values["data-job-id"], "job_url": values.get("href", ""), "title": "", "location": "", "posted_date": ""}
        elif self.current:
            classes = set((values.get("class") or "").split())
            self.field = "title" if tag == "h2" else "location" if "job-location" in classes else "posted_date" if "job-date-posted" in classes else ""
    def handle_endtag(self, tag: str) -> None:
        if self.current and tag == "a": self.jobs.append(self.current); self.current = None; self.field = ""
        elif tag in {"h2", "span"}: self.field = ""
        if self.depth: self.depth -= 1
    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if self.current and self.field and text: self.current[self.field] = f"{self.current[self.field]} {text}".strip()
        if self.depth and text: self.pagination.append(text)

class TextParser(HTMLParser):
    def __init__(self) -> None: super().__init__(convert_charrefs=True); self.parts: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3"}: self.parts.append("\n")
        if tag == "li": self.parts.append("- ")
    def handle_data(self, data: str) -> None: self.parts.append(data)
    def text(self) -> str: return "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.parts).splitlines()) if line)

def get_page(url: str, timeout: int) -> str:
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}), timeout=timeout) as response: return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as error: raise RuntimeError(f"Capital One returned HTTP {error.code} for {url}") from error
    except URLError as error: raise RuntimeError(f"Could not reach Capital One Careers: {error.reason}") from error

def parse_page(document: str, base_url: str) -> tuple[list[dict[str, str]], int]:
    parser = JobsPageParser(); parser.feed(document.replace('\\"', '"')); parser.close()
    for job in parser.jobs: job["job_url"] = urljoin(base_url, job["job_url"])
    match = re.search(r"\bof\s+(\d+)\b", " ".join(parser.pagination), flags=re.I)
    return parser.jobs, int(match.group(1)) if match else 1

def page_url(first_url: str, page: int) -> str: return first_url.rstrip("/") if page == 1 else f"{first_url.rstrip('/')}/{page}"

def bengaluru_search_url() -> str:
    parameters = [("ActiveFacetID", BENGALURU_FACET_ID), ("CurrentPage", "1"), ("RecordsPerPage", "15"), ("Distance", "50"), ("RadiusUnitType", "0"), ("Keywords", ""), ("Location", ""), ("ShowRadius", "False"), ("IsPagination", "False"), ("FacetTerm", "29016"), ("FacetType", "1"), ("FacetFilters[0].ID", BENGALURU_FACET_ID), ("FacetFilters[0].FacetType", "4"), ("FacetFilters[0].Display", BENGALURU_LABEL), ("FacetFilters[0].IsApplied", "true"), ("FacetFilters[1].ID", "29016"), ("FacetFilters[1].FacetType", "1"), ("FacetFilters[1].Display", "Engineering"), ("FacetFilters[1].IsApplied", "true"), ("SearchResultsModuleName", "Search Results"), ("SearchFiltersModuleName", "Search Filters"), ("SearchType", "2"), ("OrganizationIds", "234"), ("ResultsType", "1"), ("SortCriteria", "0"), ("SortDirection", "0")]
    return "https://www.capitalonecareers.com/search-jobs/results?" + urlencode(parameters)

def job_description(document: str) -> str:
    for source in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, flags=re.I | re.S):
        try: items = json.loads(html.unescape(source))
        except json.JSONDecodeError: continue
        for item in items if isinstance(items, list) else [items]:
            if isinstance(item, dict) and (item.get("@type") == "JobPosting" or "JobPosting" in item.get("@type", [])) and item.get("description"): return str(item["description"])
    raise RuntimeError("Capital One job page did not contain a JobPosting description")

def fetch_jobs(first_url: str, max_jobs: int, timeout: int, delay: float, skip_ids: set[str]) -> list[dict[str, Any]]:
    summaries, pages = parse_page(get_page(first_url, timeout), first_url)
    for page in range(2, pages + 1): summaries.extend(parse_page(get_page(page_url(first_url, page), timeout), first_url)[0])
    if max_jobs: summaries = summaries[:max_jobs]
    jobs = []
    for index, summary in enumerate(summaries, 1):
        if summary["id"] in skip_ids:
            print(f"Skipping existing {index}/{len(summaries)}: {summary['id']}", file=sys.stderr); continue
        print(f"Fetching {index}/{len(summaries)}: {summary['id']}", file=sys.stderr)
        description_html = job_description(get_page(summary["job_url"], timeout)); text = TextParser(); text.feed(description_html); text.close()
        jobs.append({"id": summary["id"], "title": summary["title"], "company": "Capital One", "location": summary["location"], "application_url": summary["job_url"], "posted_date": summary["posted_date"], "jobDescriptionHtml": description_html, "jobDescriptionText": html.unescape(text.text())})
        if index != len(summaries): time.sleep(delay)
    return list({job["id"]: job for job in jobs}.values())

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("url", nargs="?", default=DEFAULT_URL); parser.add_argument("--bengaluru", action="store_true"); parser.add_argument("--max-jobs", type=int, default=50); parser.add_argument("--timeout", type=int, default=30); parser.add_argument("--delay", type=float, default=.5); parser.add_argument("--output", type=Path, default=Path("capital_one_jobs.json")); parser.add_argument("--skip-job-id", action="append", default=[]); args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0: parser.error("max-jobs and delay cannot be negative; timeout must be positive")
    try: jobs = fetch_jobs(bengaluru_search_url() if args.bengaluru else args.url, args.max_jobs, args.timeout, args.delay, set(args.skip_job_id))
    except RuntimeError as error: print(f"Error: {error}", file=sys.stderr); return 1
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps({"source": "Capital One Careers public pages", "input_url": args.url, "bengaluru_filter": args.bengaluru, "jobs_fetched": len(jobs), "jobs": jobs}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); print(f"Wrote {len(jobs)} Capital One jobs to {args.output}", file=sys.stderr); return 0
if __name__ == "__main__": raise SystemExit(main())
