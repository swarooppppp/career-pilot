#!/usr/bin/env python3
"""HashiCorp-scoped IBM career search, retaining the actual hiring employer."""
import argparse
from pathlib import Path
import re
import time
from urllib.parse import parse_qs, urlparse

from common import newest_first, plain_text, write_snapshot
from fetch_ibm_jobs import API, job_schema, search_payload
from filters import engineering_title, in_india
import portal_http


def normalize(summary, detail):
    description = detail.get("description") or ""
    text = plain_text(description)
    title = detail.get("title") or summary.get("title")
    if not engineering_title({"title": title}):
        return None
    locations = detail.get("jobLocation") or []
    locations = locations if isinstance(locations, list) else [locations]
    india = in_india({"location": summary.get("field_keyword_19"), "jobLocation": locations})
    for location in locations:
        address = location.get("address") or {} if isinstance(location, dict) else {}
        country = address.get("addressCountry") if isinstance(address, dict) else None
        if isinstance(country, dict):
            country = country.get("name") or country.get("identifier")
        india = india or str(country or "").casefold() in {"in", "india"}
    if not india:
        return None
    evidence = re.search(r".{0,120}\bHashiCorp\b.{0,180}", text, re.I)
    if not evidence:
        return None
    url = summary.get("url") or ""
    parsed = urlparse(url)
    ident = parse_qs(parsed.query).get("jobId", [""])[0]
    if parsed.scheme != "https" or parsed.netloc != "careers.ibm.com" or not ident or not description:
        raise RuntimeError("HashiCorp/IBM job missing full detail or trusted identity")
    employer = detail.get("hiringOrganization") or {}
    return {"id": ident, "title": title, "company": "HashiCorp", "employer_name": employer.get("name") or "IBM",
            "country": "India", "location": summary.get("field_keyword_19") or "India", "jobLocation": locations,
            "application_url": url, "posted_date": detail.get("datePosted"),
            "brand_evidence": evidence.group(0), "brand_scope": "HashiCorp keyword-scoped IBM vacancy; source employer retained",
            "jobDescriptionHtml": description, "jobDescriptionText": text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1:
        parser.error("Invalid limits")
    if parse_qs(urlparse(args.url).query).get("q") != ["hashicorp"]:
        parser.error("HashiCorp search keyword is required")
    jobs, seen, scanned, total = [], set(), 0, 0
    for number in range(args.max_pages):
        data = portal_http.request_json(API, search_payload(args.url, number * 30, 30), args.timeout)
        hits = (data.get("hits") or {}).get("hits")
        if not isinstance(hits, list) or data.get("timed_out"):
            raise RuntimeError("HashiCorp/IBM listing response incomplete")
        raw_total = (data.get("hits") or {}).get("total", 0)
        total = raw_total.get("value", 0) if isinstance(raw_total, dict) else raw_total
        scanned += len(hits)
        for hit in hits:
            summary = hit["_source"]
            url = summary.get("url") or ""
            if url in seen:
                raise RuntimeError("HashiCorp/IBM pagination repeated jobs")
            seen.add(url)
            if urlparse(url).netloc != "careers.ibm.com":
                raise RuntimeError("Unexpected HashiCorp detail host")
            detail = job_schema(portal_http.read(url, args.timeout))
            if detail is None and portal_http.browser_enabled():
                page = portal_http.browser_page()
                page.wait_for_selector('script[type="application/ld+json"]', state="attached", timeout=args.timeout * 1000)
                detail = job_schema(page.content())
            if detail is None:
                raise RuntimeError("HashiCorp/IBM full JobPosting detail unavailable")
            job = normalize(summary, detail)
            if job:
                jobs.append(job)
        if scanned >= total or not hits:
            break
        time.sleep(0.5)
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, source=API, input_url=args.url, total_filtered_results=total,
                   complete=scanned >= total, stopped_reason=None if scanned >= total else "listing_page_limit",
                   filters="HashiCorp search keyword, native Software Engineering/India facets, detail country and brand evidence",
                   sort="Explicit JobPosting.datePosted descending; search index dates not substituted")
    print(f"HashiCorp: wrote {len(jobs)} scoped Engineering/India jobs")


if __name__ == "__main__":
    main()
