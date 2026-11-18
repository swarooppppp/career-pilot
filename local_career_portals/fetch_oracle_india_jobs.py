#!/usr/bin/env python3
"""Collect public Oracle Candidate Experience jobs with complete descriptions."""
import argparse
import json
from pathlib import Path
import time
from urllib.parse import urlencode, urlsplit

from common import newest_first, plain_text, write_snapshot
from filters import engineering_title, in_india
from portal_http import read


def normalize(detail, company, origin, site):
    locations = [detail.get("PrimaryLocation") or ""] + [
        v.get("LocationName") or v.get("PrimaryLocation") or ""
        for v in detail.get("secondaryLocations") or []]
    country = detail.get("PrimaryLocationCountry")
    job = {"id": str(detail["Id"]), "title": detail["Title"], "company": company,
           "location": " | ".join(filter(None, locations)),
           "country": "India" if country == "IN" else country,
           "department": detail.get("JobFunction"),
           "posted_date": detail.get("ExternalPostedStartDate"),
           "application_url": f"{origin}/hcmUI/CandidateExperience/en/sites/{site}/job/{detail['Id']}"}
    if not in_india(job) or not engineering_title(job):
        return None
    parts = [detail.get(k) or "" for k in (
        "ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr")]
    if not plain_text(parts[0]):
        raise RuntimeError("Selected Oracle job lacks its full description")
    job["jobDescriptionHtml"] = "\n".join(v for v in parts if v)
    job["jobDescriptionText"] = plain_text(job["jobDescriptionHtml"])
    return job


def collect(url, company, site="CX_1", timeout=30, max_pages=100, delay=0.3, title_facet=None, reader=None):
    read_source = reader or read
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    base = origin + "/hcmRestApi/resources/latest/"
    jobs, seen = [], set()
    for number in range(max_pages):
        finder = f"findReqs;siteNumber={site},limit=100,offset={number * 100},sortBy=POSTING_DATES_DESC"
        if title_facet:
            finder += f",selectedTitlesFacet={title_facet}"
        payload = json.loads(read_source(base + "recruitingCEJobRequisitions?" + urlencode({
            "onlyData": "true", "expand": "requisitionList", "finder": finder}), timeout))
        items = payload.get("items")
        if not items or not isinstance(items[0].get("requisitionList"), list):
            raise RuntimeError("Oracle listing response shape changed")
        data = items[0]
        if title_facet and data.get("SelectedTitlesFacet") != title_facet:
            raise RuntimeError("Oracle did not confirm the requested job-function facet")
        total = int(data["TotalJobsCount"])
        listings = data["requisitionList"]
        if not listings and number * 100 < total:
            raise RuntimeError("Oracle pagination ended before the reported total")
        for summary in listings:
            ident = str(summary["Id"])
            if ident in seen:
                raise RuntimeError("Oracle returned a repeated job across pages")
            seen.add(ident)
            if not engineering_title({"title": summary.get("Title")}):
                continue
            time.sleep(delay)
            details = json.loads(read_source(base + "recruitingCEJobRequisitionDetails?" + urlencode({
                "onlyData": "true", "expand": "all", "finder": f"ById;Id={ident},siteNumber={site}"}), timeout))
            if not details.get("items") or str(details["items"][0].get("Id")) != ident:
                raise RuntimeError("Oracle returned a missing or mismatched job detail")
            job = normalize(details["items"][0], company, origin, site)
            if job:
                jobs.append(job)
        if len(seen) >= total:
            return newest_first(jobs), total
        time.sleep(delay)
    raise RuntimeError("Oracle pagination limit reached before the reported total")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--company", required=True)
    parser.add_argument("--site", default="CX_1")
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    jobs, total = collect(args.url, args.company, args.site, args.timeout, args.max_pages, args.delay)
    write_snapshot(args.output, jobs[:args.max_jobs] if args.max_jobs else jobs,
                   input_url=args.url, source_total=total,
                   ordering="Publication date descending after complete listing scan")


if __name__ == "__main__":
    main()
