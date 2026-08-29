#!/usr/bin/env python3
"""Fetch public Microsoft Careers job listings and their full descriptions.

The careers UI makes these public JSON requests:
  GET /api/pcsx/search             -> page of job summaries
  GET /api/pcsx/position_details   -> one job, including `jobDescription` HTML
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
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://apply.careers.microsoft.com"
DOMAIN = "microsoft.com"
PAGE_SIZE = 10  # The public search endpoint currently returns ten results per page.


class _HTMLToText(HTMLParser):
    """Small dependency-free HTML-to-text converter for the description field."""

    BLOCK_TAGS = {"br", "div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "hr"}

    def __init__(self, *, convert_charrefs: bool = True) -> None:
        super().__init__(convert_charrefs=convert_charrefs)
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
    parser = _HTMLToText(convert_charrefs=True)
    parser.feed(value)
    parser.close()
    return html.unescape(parser.text())


def get_json(path: str, params: dict[str, str], timeout: int) -> dict[str, Any]:
    url = f"{BASE_URL}{path}?{urlencode(params, doseq=True)}"
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} from {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Microsoft Careers: {exc.reason}") from exc

    if payload.get("status") != 200 or "data" not in payload:
        raise RuntimeError(f"Unexpected API response from {url}: {payload}")
    return payload["data"]


def search_jobs(args: argparse.Namespace, start: int) -> dict[str, Any]:
    params = {
        "domain": DOMAIN,
        "query": args.query,
        "location": args.location,
        "start": str(start),
        "sort_by": args.sort_by,
        "filter_include_remote": "1" if args.include_remote else "0",
        "filter_include_relocation": "1" if args.include_relocation else "0",
    }
    return get_json("/api/pcsx/search", params, args.timeout)


def get_job_details(job_id: int, args: argparse.Namespace) -> dict[str, Any]:
    return get_json(
        "/api/pcsx/position_details",
        {"position_id": str(job_id), "domain": DOMAIN, "hl": args.locale},
        args.timeout,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="Software Engineer")
    parser.add_argument("--location", default="India")
    parser.add_argument("--sort-by", default="relevance")
    parser.add_argument("--include-remote", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--include-relocation", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--locale", default="en")
    parser.add_argument("--max-pages", type=int, default=1, help="Use 0 to fetch every result.")
    parser.add_argument("--delay", type=float, default=0.25, help="Seconds between detail requests.")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("microsoft_jobs.json"))
    args = parser.parse_args()

    first_page = search_jobs(args, 0)
    total = int(first_page["count"])
    page_count = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if args.max_pages:
        page_count = min(page_count, args.max_pages)

    summaries = list(first_page.get("positions", []))
    for page in range(1, page_count):
        time.sleep(args.delay)
        summaries.extend(search_jobs(args, page * PAGE_SIZE).get("positions", []))

    jobs: list[dict[str, Any]] = []
    for index, summary in enumerate(summaries, start=1):
        print(f"Fetching {index}/{len(summaries)}: {summary['id']}", file=sys.stderr)
        details = get_job_details(int(summary["id"]), args)
        description_html = details.get("jobDescription", "")
        jobs.append({
            **details,
            "jobDescriptionHtml": description_html,
            "jobDescriptionText": html_to_text(description_html),
        })
        if index != len(summaries):
            time.sleep(args.delay)

    output = {
        "source": BASE_URL,
        "search_endpoint": "/api/pcsx/search",
        "detail_endpoint": "/api/pcsx/position_details",
        "search": {
            "query": args.query,
            "location": args.location,
            "sort_by": args.sort_by,
            "include_remote": args.include_remote,
            "include_relocation": args.include_relocation,
            "total_results_reported_by_api": total,
            "jobs_fetched": len(jobs),
        },
        "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
