#!/usr/bin/env python3
"""Fetch filtered Goldman Sachs roles from its public Higher GraphQL API."""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ENDPOINT = "https://api-higher.gs.com/gateway/api/v1/graphql"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilot/1.0)"
SEARCH = """query GetRoles($searchQueryInput: RoleSearchQueryInput!) { roleSearch(searchQueryInput: $searchQueryInput) { totalCount items { roleId corporateTitle jobTitle jobFunction locations { primary state country city } status division skills jobType { code description } externalSource { sourceId } } } }"""
DETAIL = """query GetRoleById($externalSourceId: String!, $externalSourceFetch: Boolean) { role(externalSourceId: $externalSourceId externalSourceFetch: $externalSourceFetch) { roleId corporateTitle jobTitle jobFunction locations { primary state country city } division descriptionHtml jobType { code description } skillset externalSource { externalApplicationUrl sourceId } } }"""


def graphql(operation: str, variables: dict, query: str, timeout: int) -> dict:
    request = Request(ENDPOINT, data=json.dumps({"operationName": operation, "variables": variables, "query": query}).encode(), headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=timeout) as response: payload = json.load(response)
    except HTTPError as exc: raise RuntimeError(f"Goldman Sachs returned HTTP {exc.code}") from exc
    except URLError as exc: raise RuntimeError(f"Could not reach Goldman Sachs Careers: {exc.reason}") from exc
    if payload.get("errors"): raise RuntimeError(f"Goldman Sachs GraphQL error: {payload['errors'][0].get('message', 'unknown')}")
    return payload["data"]


def filters_from_url(url: str) -> tuple[str, list[dict]]:
    query = parse_qs(urlparse(url).query)
    filters = []
    for category in ("EXPERIENCE_LEVEL", "JOB_FUNCTION"):
        values = query.get(category, [""])[0].split("|")
        if values != [""]: filters.append({"filterCategoryType": category, "filters": [{"filter": value, "subFilters": []} for value in values]})
    location_paths = {
        "Bengaluru": ("India", "Karnataka"), "Hyderabad": ("India", "Telangana"),
        "Mumbai": ("India", "Maharashtra"),
    }
    locations = query.get("LOCATION", [""])[0].split("|")
    if locations != [""]:
        countries: dict[str, dict[str, list[str]]] = {}
        for city in locations:
            country, state = location_paths.get(city, (city, ""))
            countries.setdefault(country, {}).setdefault(state, []).append(city)
        nested = []
        for country, states in countries.items():
            nested.append({"filter": country, "subFilters": [
                {"filter": state, "subFilters": [{"filter": city, "subFilters": []} for city in cities]}
                if state else {"filter": city, "subFilters": []}
                for state, cities in states.items()
            ]})
        filters.append({"filterCategoryType": "LOCATION", "filters": nested})
    return query.get("search", [""])[0], filters


def fetch_jobs(url: str, max_jobs: int, timeout: int, skip_ids: set[str]) -> list[dict]:
    search_term, filters = filters_from_url(url); jobs = []; page = 0
    while not max_jobs or len(jobs) < max_jobs:
        input_ = {"page": {"pageSize": 20, "pageNumber": page}, "sort": {"sortStrategy": "RELEVANCE", "sortOrder": "DESC"}, "filters": filters, "experiences": ["EARLY_CAREER", "PROFESSIONAL"], "searchTerm": search_term}
        role_search = graphql("GetRoles", {"searchQueryInput": input_}, SEARCH, timeout)["roleSearch"]
        items = role_search.get("items", [])
        if not items: break
        for role in items:
            source_id = str((role.get("externalSource") or {}).get("sourceId") or "")
            if not source_id or source_id in skip_ids: continue
            detail = graphql("GetRoleById", {"externalSourceId": source_id, "externalSourceFetch": True}, DETAIL, timeout)["role"]
            description_html = str(detail.get("descriptionHtml") or "")
            locations = ", ".join(", ".join(filter(None, [item.get("city"), item.get("state"), item.get("country")])) for item in detail.get("locations", []))
            jobs.append({"id": source_id, "title": detail.get("jobTitle", ""), "company": "Goldman Sachs", "location": locations, "department": detail.get("jobFunction", ""), "employment_type": (detail.get("jobType") or {}).get("description", ""), "application_url": (detail.get("externalSource") or {}).get("externalApplicationUrl", f"https://higher.gs.com/roles/{source_id}"), "jobDescriptionHtml": description_html, "jobDescriptionText": " ".join(re.sub(r"<[^>]+>", " ", html.unescape(description_html)).split())})
            if max_jobs and len(jobs) >= max_jobs: return jobs
        page += 1
        if page * 20 >= int(role_search.get("totalCount", 0)): break
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("url"); parser.add_argument("--max-jobs", type=int, default=50); parser.add_argument("--timeout", type=int, default=30); parser.add_argument("--skip-job-id", action="append", default=[]); parser.add_argument("--output", type=Path, default=Path("goldman_sachs_jobs.json")); args = parser.parse_args()
    try: jobs = fetch_jobs(args.url, args.max_jobs, args.timeout, set(args.skip_job_id))
    except RuntimeError as exc: print(f"Error: {exc}", file=sys.stderr); return 1
    args.output.parent.mkdir(parents=True, exist_ok=True); args.output.write_text(json.dumps({"input_url": args.url, "jobs": jobs}, indent=2) + "\n", encoding="utf-8"); print(f"Wrote {len(jobs)} Goldman Sachs jobs to {args.output}", file=sys.stderr); return 0


if __name__ == "__main__": raise SystemExit(main())
