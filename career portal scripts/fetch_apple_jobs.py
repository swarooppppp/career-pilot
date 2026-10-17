#!/usr/bin/env python3
"""Fetch Apple Jobs search results and public detail-page descriptions."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen


DEFAULT_URL = "https://jobs.apple.com/en-in/search?location=india-INDC&key=Software%2520Engineer"
BASE_URL = "https://jobs.apple.com"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilotAppleJobs/1.0)"


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


def fetch_text(url: str, timeout: int) -> str:
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8")
    except HTTPError as error:
        raise RuntimeError(f"Apple returned HTTP {error.code} for {url}") from error
    except URLError as error:
        raise RuntimeError(f"Could not reach Apple Jobs: {error.reason}") from error


def hydration_data(page_html: str) -> dict[str, Any]:
    """Decode the JSON serialized by Apple's public React router page."""
    match = re.search(r"window\.__staticRouterHydrationData\s*=\s*JSON\.parse\((\"(?:\\.|[^\"])*\")\)", page_html)
    if not match:
        raise RuntimeError("Apple's public hydration data was not found in the page.")
    payload = json.loads(match.group(1))
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise RuntimeError("Apple's public hydration data must be an object.")
    return data


def with_page(search_url: str, page: int) -> str:
    parsed = urlparse(search_url)
    if parsed.scheme != "https" or parsed.netloc != "jobs.apple.com" or not parsed.path.endswith("/search"):
        raise ValueError("Apple search URL must be an https://jobs.apple.com/<locale>/search URL")
    params = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "page"]
    if page > 1:
        params.append(("page", str(page)))
    return urlunparse(parsed._replace(query=urlencode(params, doseq=True)))


def detail_url(search_url: str, job: dict[str, Any]) -> str:
    locale = urlparse(search_url).path.strip("/").split("/")[0]
    job_id = str(job.get("id") or "").strip()
    slug = quote(str(job.get("transformedPostingTitle") or "").strip(), safe="-")
    if not locale or not job_id or not slug:
        raise ValueError("Apple search result did not include an id and transformed posting title")
    url = f"{BASE_URL}/{locale}/details/{job_id}/{slug}"
    team = job.get("team") if isinstance(job.get("team"), dict) else {}
    team_code = str(team.get("teamCode") or "").strip()
    return f"{url}?{urlencode({'team': team_code})}" if team_code else url


def section_html(detail: dict[str, Any]) -> str:
    """Build an explicit, readable HTML description from Apple's detail sections."""
    sections = (
        ("Summary", detail.get("jobSummary")),
        ("Description", detail.get("description")),
        ("Responsibilities", detail.get("responsibilities")),
        ("Minimum qualifications", detail.get("minimumQualifications")),
        ("Preferred qualifications", detail.get("preferredQualifications")),
    )
    return "\n".join(
        f"<h2>{heading}</h2>\n{value}" for heading, value in sections
        if isinstance(value, str) and value.strip()
    )


def locations_text(locations: Any) -> str:
    if not isinstance(locations, list):
        return ""
    values: list[str] = []
    for location in locations:
        value = location.get("name") if isinstance(location, dict) else location
        value = str(value or "").strip()
        if value and value not in values:
            values.append(value)
    return " + ".join(values)


def normalise_result(job: dict[str, Any], detail: dict[str, Any], url: str) -> dict[str, Any] | None:
    job_id = str(job.get("id") or "").strip()
    title = str(job.get("postingTitle") or "").strip()
    description_html = section_html(detail)
    if not job_id or not title or not description_html:
        return None
    return {
        "id": job_id,
        "title": title,
        "company": "Apple",
        "location": locations_text(job.get("locations")),
        "application_url": url,
        "posted_date": job.get("postDateInGMT"),
        "jobDescriptionHtml": description_html,
        "jobDescriptionText": html_to_text(description_html),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL, help="Apple public job-search URL")
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-job-id", action="append", default=[])
    parser.add_argument("--output", type=Path, default=Path("apple_jobs.json"))
    args = parser.parse_args()
    if args.max_pages < 1 or args.max_jobs < 0 or args.timeout < 1:
        parser.error("max-pages and timeout must be positive; max-jobs cannot be negative")
    try:
        listings: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for page in range(1, args.max_pages + 1):
            current_url = with_page(args.url, page)
            print(f"Fetching Apple search page {page}: {current_url}", file=sys.stderr)
            search = hydration_data(fetch_text(current_url, args.timeout))["loaderData"]["search"]
            results = search.get("searchResults", [])
            if not isinstance(results, list) or not results:
                break
            for listing in results:
                job_id = str(listing.get("id") or "") if isinstance(listing, dict) else ""
                if job_id and job_id not in seen_ids:
                    seen_ids.add(job_id)
                    listings.append(listing)
                if args.max_jobs and len(listings) >= args.max_jobs:
                    break
            if args.max_jobs and len(listings) >= args.max_jobs:
                break
        jobs: list[dict[str, Any]] = []
        skip_ids = set(args.skip_job_id)
        for number, listing in enumerate(listings, start=1):
            if str(listing.get("id") or "") in skip_ids:
                print(f"Skipping existing Apple job {number}/{len(listings)}: {listing.get('id')}", file=sys.stderr)
                continue
            url = detail_url(args.url, listing)
            print(f"Fetching Apple job {number}/{len(listings)}: {url}", file=sys.stderr)
            details = hydration_data(fetch_text(url, args.timeout))["loaderData"]["jobDetails"]["jobsData"]
            if not isinstance(details, dict):
                raise RuntimeError(f"Apple detail response for {listing.get('id')} was not an object")
            if (job := normalise_result(listing, details, url)) is not None:
                jobs.append(job)
    except (RuntimeError, KeyError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    output = {
        "source": "Apple Jobs public hydration data",
        "retrieval": "Apple public paginated search and public detail-page hydration data",
        "input_url": args.url,
        "jobs_fetched": len(jobs),
        "jobs": jobs,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(jobs)} Apple jobs to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
