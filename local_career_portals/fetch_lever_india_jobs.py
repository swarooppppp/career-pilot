#!/usr/bin/env python3
"""Zeta fintech's public Lever feed, complete descriptions and explicit posting dates."""
import argparse
from datetime import datetime, timezone
import html
import importlib.util
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import engineering_title, in_india
import portal_http

SPEC = importlib.util.spec_from_file_location("local_lever_transport", Path(__file__).resolve().parents[1] / "career portal scripts/fetch_lever_jobs.py")
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)
API = "https://api.lever.co/v0/postings/zeta"
SOURCES = {"zeta": ("Zeta", "zeta"), "cred": ("CRED", "cred"), "meesho": ("Meesho", "meesho")}


def posting_date(document):
    for raw in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', document, re.I | re.S):
        try:
            stack = [json.loads(raw)]
        except ValueError:
            continue
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                kind = value.get("@type")
                if (kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind) and value.get("datePosted"):
                    return value["datePosted"]
                stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return None


def created_date(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    return value if isinstance(value, str) else None


def normalize(item, source="zeta"):
    company, board = SOURCES[source]
    categories = item.get("categories") or {}
    locations = list(dict.fromkeys([categories.get("location") or "", *(categories.get("allLocations") or [])]))
    if not in_india({"locations": locations}):
        return None
    if source == "zeta" and categories.get("team", "").casefold() != "engineering":
        return None
    if source != "zeta" and re.search(r"sales|support|customer|business development", " ".join(str(categories.get(k) or "") for k in ("team", "department")), re.I):
        return None
    if not engineering_title({"title": item.get("text")}):
        return None
    if re.search(r"\b(?:talent community|talent pool|general application|expressions? of interest)\b", item.get("text", ""), re.I):
        return None
    sections = [item.get("description") or ""]
    sections.extend("<h2>" + html.escape(str(section.get("text") or "")) + "</h2>" + str(section.get("content") or "")
                    for section in item.get("lists") or [] if isinstance(section, dict) and section.get("content"))
    sections.append(item.get("additional") or "")
    description = "\n".join(value for value in sections if value)
    url = item.get("hostedUrl") or item.get("applyUrl") or ""
    parsed = urlparse(url)
    if not item.get("id") or not item.get("text") or not description:
        raise RuntimeError("Zeta selected posting is missing full description or identity")
    if parsed.scheme != "https" or parsed.netloc != "jobs.lever.co" or not parsed.path.startswith(f"/{board}/"):
        raise RuntimeError(f"Unexpected {company} Lever URL")
    return {"id": str(item["id"]), "title": item["text"], "company": company,
            "department": categories.get("team"), "source_categories": categories,
            "location": " | ".join(v for v in locations if v), "locations": locations, "country": "India",
            "application_url": url, "apply_url": item.get("applyUrl"),
            "posted_date": item.get("datePosted") or item.get("publishedAt"),
            "source_created_date": created_date(item.get("createdAt")),
            "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)}


def collect_postings(timeout, source="zeta"):
    results, seen, offset = [], set(), 0
    while True:
        url = f"https://api.lever.co/v0/postings/{SOURCES[source][1]}?mode=json&limit=100&skip={offset}"
        page = json.loads(portal_http.read(url, timeout)) if portal_http.browser_enabled() else transport.get(url, timeout)
        if not isinstance(page, list):
            raise RuntimeError("Zeta Lever feed response shape changed")
        for item in page:
            ident = item.get("id")
            if not ident or ident in seen:
                raise RuntimeError("Zeta Lever pagination repeated or omitted posting IDs")
            seen.add(ident)
            results.append(item)
        if len(page) < 100:
            return results
        offset += len(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--source", choices=SOURCES, default="zeta")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    postings = collect_postings(args.timeout, args.source)
    jobs = [job for item in postings if (job := normalize(item, args.source)) is not None]
    date_errors = []
    for job in jobs:
        if job["posted_date"]:
            continue
        time.sleep(args.delay)
        try:
            job["posted_date"] = posting_date(read(job["application_url"], args.timeout))
        except (HTTPError, URLError, TimeoutError, RuntimeError) as error:
            # Full descriptions are already available from the public feed.
            # A failed optional date lookup must not erase those valid jobs.
            match = re.search(r"HTTP (\d{3})", str(error))
            code = getattr(error, "code", None) or (int(match.group(1)) if match else None)
            date_errors.append({"id": job["id"], "error": str(error), "http_status": code})
            if code == 429:
                break
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, source=f"https://api.lever.co/v0/postings/{SOURCES[args.source][1]}", input_url=args.url, complete=True,
                   global_results=len(postings), publication_date_lookup_errors=date_errors,
                   filters="Technical titles and explicit India locations; Zeta exact Engineering team; sales/support excluded for CRED and Meesho",
                   sort="Explicit publication dates descending before cap; unknown dates preserve feed order",
                   limitations="createdAt retained separately; full descriptions include lists/additional sections; optional detail-date failures recorded")
    print(f"{SOURCES[args.source][0]}: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
