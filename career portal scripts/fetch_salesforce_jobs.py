#!/usr/bin/env python3
"""Fetch Salesforce Careers jobs from its public static datasets.

The Salesforce careers search page downloads two JSON datasets, then filters
and paginates them in the browser. This adapter performs the same filtering
locally and writes Career Pilot's normalized raw-job snapshot.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


DATASET_URLS = (
    "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_1.json",
    "https://a.sfdcstatic.com/digital/xsf/careers/prod/jobs_2.json",
)
DEFAULT_URL = (
    "https://www.salesforce.com/company/careers/jobs/?country=India&pagesize=20&"
    "employeeTypes=Regular&team=Software+Engineering&page=1"
)


class HTMLToText(HTMLParser):
    BLOCK_TAGS = {"br", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "hr"}

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


def fetch_dataset(timeout: int) -> list[dict[str, Any]]:
    """Load and merge Salesforce's two browser-requested public datasets."""
    jobs: dict[str, dict[str, Any]] = {}
    cache_bust = str(int(time.time()))
    for dataset_url in DATASET_URLS:
        request = Request(
            f"{dataset_url}?v={cache_bust}",
            headers={"Accept": "application/json", "Cache-Control": "no-cache", "User-Agent": "Mozilla/5.0"},
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8"))
        except HTTPError as error:
            raise RuntimeError(f"Salesforce returned HTTP {error.code} for the jobs dataset.") from error
        except URLError as error:
            raise RuntimeError(f"Could not reach Salesforce's jobs dataset: {error.reason}") from error
        entries = payload.get("Report_Entry", [])
        if not isinstance(entries, list):
            raise RuntimeError("Salesforce jobs dataset did not contain a Report_Entry list.")
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            job_id = str(entry.get("Job_Requisition_Ref_ID") or "").strip()
            if not job_id:
                continue
            jobs.setdefault(job_id, {}).update(
                {key: value for key, value in entry.items() if value not in (None, "", [], {})}
            )
    return list(jobs.values())


def values(query: dict[str, list[str]], key: str) -> set[str]:
    return {value.casefold() for value in query.get(key, []) if value}


def has_match(item_values: Any, expected: set[str]) -> bool:
    if not expected:
        return True
    if isinstance(item_values, str):
        item_values = [item_values]
    return isinstance(item_values, list) and bool(
        {str(value).casefold() for value in item_values if value} & expected
    )


def matches(job: dict[str, Any], query: dict[str, list[str]]) -> bool:
    teams = values(query, "team")
    countries = values(query, "country")
    employee_types = values(query, "employeeTypes")
    contract_types = values(query, "contractTypes")
    keywords = " ".join(query.get("keywords", [])).casefold().strip()
    if teams and str(job.get("Job_Family_Group") or "").casefold() not in teams:
        return False
    if employee_types and str(job.get("Employee_Type") or "").casefold() not in employee_types:
        return False
    if contract_types and str(job.get("Time_Type") or "").casefold() not in contract_types:
        return False
    if not has_match(job.get("Countries"), countries):
        return False
    if keywords:
        searchable = " ".join(
            (str(job.get("Job_Posting_Title") or ""), str(job.get("Job_Description") or ""))
        ).casefold()
        if keywords not in searchable:
            return False
    return True


def normalise_result(job: dict[str, Any]) -> dict[str, Any] | None:
    job_id = str(job.get("Job_Requisition_Ref_ID") or "").strip()
    title = str(job.get("Job_Posting_Title") or "").strip()
    description_html = str(job.get("Job_Description") or "").strip()
    application_url = str(job.get("External_Job_Posting_Site") or "").strip()
    if not job_id or not title or not description_html or not application_url:
        return None
    locations = job.get("Locations") if isinstance(job.get("Locations"), list) else []
    location = str(job.get("Job_Requisition_Primary_Location") or "").strip()
    if not location:
        location = " + ".join(str(value) for value in locations if value)
    return {
        "id": job_id,
        "title": title,
        "company": "Salesforce",
        "location": location,
        "application_url": application_url,
        "posted_date": job.get("External_Job_Posting_Start_Date"),
        "jobDescriptionHtml": description_html,
        "jobDescriptionText": html_to_text(description_html),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Salesforce careers search URL")
    parser.add_argument("--max-pages", type=int, default=10, help="Maximum filtered pages to include from the requested page.")
    parser.add_argument("--max-jobs", type=int, default=50, help="Maximum matching jobs to write; 0 keeps all selected pages.")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", type=Path, default=Path("salesforce_jobs.json"))
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-pages and timeout must be positive; max-jobs cannot be negative")
    query = parse_qs(urlparse(args.url).query)
    try:
        page_size = max(1, int(query.get("pagesize", ["20"])[0]))
        start_page = max(1, int(query.get("page", ["1"])[0]))
        filtered = [result for job in fetch_dataset(args.timeout) if matches(job, query)
                    if (result := normalise_result(job)) is not None]
    except (RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    start = (start_page - 1) * page_size
    selected = filtered[start:start + args.max_pages * page_size]
    if args.max_jobs:
        selected = selected[:args.max_jobs]
    output = {
        "source": "Salesforce Careers public static jobs datasets",
        "retrieval": "Merged jobs_1.json and jobs_2.json; filtered locally using the supplied careers search URL",
        "input_url": args.url,
        "matching_jobs": len(filtered),
        "jobs_fetched": len(selected),
        "jobs": selected,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(selected)} of {len(filtered)} matching Salesforce jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
