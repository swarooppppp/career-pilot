#!/usr/bin/env python3
"""Workday transport with tenant-discovered India and engineering facets."""
import argparse
import importlib.util
from pathlib import Path
import re
import time

from common import newest_first, plain_text, write_snapshot
from filters import engineering_title, in_india
import portal_http

SPEC = importlib.util.spec_from_file_location("shared_workday_transport", Path(__file__).resolve().parents[1] / "career portal scripts/fetch_workday_jobs.py")
transport = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transport)


def request_json(url, payload, timeout):
    return portal_http.request_json(url, payload, timeout) if portal_http.browser_enabled() else transport.request_json(url, payload, timeout)


def facet_nodes(value):
    if isinstance(value, dict):
        if value.get("facetParameter"):
            yield value
        for child in value.values():
            yield from facet_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from facet_nodes(child)


def native_facets(facets):
    nodes = list(facet_nodes(facets))
    country, locations, engineering = {}, {}, {}
    geography_seen = False
    for node in nodes:
        parameter = node["facetParameter"]
        label = str(node.get("descriptor") or "").casefold()
        values = [v for v in node.get("values", []) if isinstance(v, dict) and v.get("id")]
        if "country" in parameter.casefold() or "country" in label:
            geography_seen = True
            ids = [v["id"] for v in values if v.get("descriptor", "").casefold() == "india"]
            if ids:
                country[parameter] = ids
        elif parameter.casefold() == "locations":
            geography_seen = True
            ids = [v["id"] for v in values if in_india({"location": v.get("descriptor")}) or v.get("descriptor", "").startswith("IND-")]
            if ids:
                locations[parameter] = ids
        elif parameter in {"jobFamilyGroup", "jobFamilies"} or label in {"job function", "job category", "job families"}:
            ids = [v["id"] for v in values if re.search(r"engineering|r&d", v.get("descriptor", ""), re.I)
                   and not re.search(r"sales|support", v.get("descriptor", ""), re.I)]
            if ids:
                engineering[parameter] = ids
    if not geography_seen:
        raise RuntimeError("No discoverable Workday geographic facets")
    return {**(country or locations), **engineering} if (country or locations) else None


def display(value):
    return str(value.get("descriptor") or value.get("name") or value.get("location") or "") if isinstance(value, dict) else str(value or "")


def brand_evidence(detail, required):
    text = plain_text(detail.get("jobDescription") or "") + " " + display(detail.get("company"))
    pattern = r"\b" + r"\s*".join(re.escape(part) for part in required.split()) + r"\b"
    match = re.search(pattern, text, re.I)
    return text[max(0, match.start() - 80):match.end() + 120] if match else None


def normalize(summary, detail, host, site, company):
    locations = [display(detail.get("location") or summary.get("locationsText"))] + [display(v) for v in detail.get("additionalLocations") or []]
    country = display(detail.get("country"))
    if not in_india({"locations": locations, "country": country}):
        return None
    description = detail.get("jobDescription") or ""
    if not description:
        raise RuntimeError("Workday selected job is missing a full description")
    return {"id": detail.get("jobReqId") or (summary.get("bulletFields") or [detail.get("id")])[0],
            "title": detail.get("title") or summary["title"], "company": company, "country": country,
            "location": " | ".join(v for v in locations if v), "posted_date": detail.get("startDate"),
            "application_url": detail.get("externalUrl") or f"https://{host}/{site}{summary['externalPath']}",
            "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--company", required=True)
    parser.add_argument("--search-text", help="Override keyword search; empty string discovers all technical titles")
    parser.add_argument("--require-brand", help="Require this business-unit brand in hydrated details")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    host, tenant, site, query = transport.site_config(args.url)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    payload = {"limit": 20, "offset": 0, "searchText": args.search_text if args.search_text is not None else query.get("q", "Engineer")}
    discovery = request_json(base + "/jobs", payload, args.timeout)
    if not isinstance(discovery.get("facets"), list) or not isinstance(discovery.get("jobPostings"), list):
        raise RuntimeError("Workday discovery response shape changed")
    facets = native_facets(discovery["facets"])
    jobs, summaries, seen, total, scanned = [], [], set(), 0, 0
    if facets:
        for number in range(args.max_pages):
            time.sleep(args.delay)
            page = request_json(base + "/jobs", {**payload, "offset": number * 20, "appliedFacets": facets}, args.timeout)
            if not isinstance(page.get("jobPostings"), list) or "total" not in page:
                raise RuntimeError("Workday filtered response shape changed")
            # Some tenants (including eBay) report total=0 on every page after
            # offset zero, even while returning more listings. Keep the count
            # learned from the first page so pagination cannot stop early.
            total = max(total, int(page["total"]))
            scanned += len(page["jobPostings"])
            for summary in page["jobPostings"]:
                ident = summary.get("externalPath")
                if ident and ident not in seen and engineering_title(summary):
                    summaries.append(summary)
                    seen.add(ident)
            if scanned >= total or not page["jobPostings"]:
                break
        for summary in summaries:
            time.sleep(args.delay)
            detail = request_json(base + summary["externalPath"], None, args.timeout).get("jobPostingInfo", {})
            job = normalize(summary, detail, host, site, args.company)
            if job and args.require_brand:
                evidence = brand_evidence(detail, args.require_brand)
                if not evidence:
                    continue
                job["brand_evidence"] = evidence
                job["employer_name"] = display(detail.get("company")) or args.company
            if job and engineering_title(job):
                jobs.append(job)
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    complete = scanned >= total
    write_snapshot(args.output, jobs, input_url=args.url, source=base, discovered_applied_facets=facets,
                   total_filtered_results=total, complete=complete, stopped_reason=None if complete else "listing_page_limit",
                   sort="Workday startDate descending before cap; missing dates stay unknown")
    print(f"{args.company}: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
