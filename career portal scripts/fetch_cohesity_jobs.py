#!/usr/bin/env python3
"""Fetch Cohesity Engineering jobs in India from its public jobs feed."""
from __future__ import annotations
import argparse, html, json, re, sys, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://www.cohesity.com/bin/cohesity/open-positions/"
class TextParser(HTMLParser):
    def __init__(self) -> None: super().__init__(convert_charrefs=True); self.parts: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3"}: self.parts.append("\n")
    def handle_data(self, data: str) -> None: self.parts.append(data)
    def text(self) -> str: return "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.parts).splitlines()) if line)
def fetch(url: str, accept: str, timeout: int) -> str:
    try:
        with urlopen(Request(url, headers={"Accept": accept, "User-Agent": "Mozilla/5.0 (compatible; CareerPilotCohesityFetcher/1.0)"}), timeout=timeout) as response: return response.read().decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as error: raise RuntimeError(f"Cohesity returned HTTP {error.code} for {url}") from error
    except URLError as error: raise RuntimeError(f"Could not reach Cohesity Careers: {error.reason}") from error
def job_description(document: str) -> str:
    for source in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, flags=re.I|re.S):
        try: item = json.loads(html.unescape(source))
        except json.JSONDecodeError: continue
        for candidate in item if isinstance(item, list) else [item]:
            if isinstance(candidate, dict) and candidate.get("@type") == "JobPosting" and candidate.get("description"): return str(candidate["description"])
    raise RuntimeError("Cohesity job page did not contain a JobPosting description")
def fetch_jobs(timeout: int, delay: float, skip_ids: set[str], max_jobs: int) -> list[dict[str, Any]]:
    try: groups = json.loads(fetch(API_URL, "application/json", timeout))["job_data"]
    except (KeyError, json.JSONDecodeError) as error: raise RuntimeError("Cohesity jobs feed had an unexpected shape") from error
    listings = [job for job in groups.get("Engineering", []) if isinstance(job, dict) and str(job.get("country") or "").casefold() == "india"]
    if max_jobs:
        listings = listings[:max_jobs]
    jobs = []
    for index, job in enumerate(listings, 1):
        job_id, url = str(job.get("req_id") or "").strip(), str(job.get("jobUrl") or "").strip()
        if not job_id or not url: continue
        if job_id in skip_ids: print(f"Skipping existing {index}/{len(listings)}: {job_id}", file=sys.stderr); continue
        print(f"Fetching {index}/{len(listings)}: {job_id}", file=sys.stderr)
        description_html = job_description(fetch(url, "text/html", timeout)); parser = TextParser(); parser.feed(description_html); parser.close()
        jobs.append({"id": job_id, "title": job.get("title", ""), "company": job.get("company", "Cohesity"), "location": job.get("primaryLocation", ""), "application_url": url, "jobDescriptionHtml": description_html, "jobDescriptionText": html.unescape(parser.text())})
        if index != len(listings): time.sleep(delay)
    return jobs
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--max-jobs", type=int, default=50); parser.add_argument("--timeout", type=int, default=30); parser.add_argument("--delay", type=float, default=.5); parser.add_argument("--skip-job-id", action="append", default=[]); parser.add_argument("--output", type=Path, default=Path("cohesity_jobs.json")); args=parser.parse_args()
    try: jobs=fetch_jobs(args.timeout,args.delay,set(args.skip_job_id),args.max_jobs)
    except RuntimeError as error: print(f"Error: {error}", file=sys.stderr); return 1
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps({"source":"Cohesity public open-positions feed and Workday job pages","jobs_fetched":len(jobs),"jobs":jobs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); return 0
if __name__ == "__main__": raise SystemExit(main())
