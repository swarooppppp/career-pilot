#!/usr/bin/env python3
"""Flipkart's current TurboHire portal, capturing its public full-description feed."""
import argparse
import json
from pathlib import Path
import re

from common import newest_first, plain_text, write_snapshot
from filters import in_india

ORG = "4d757ba0-3d57-448a-b82c-238ed87ac90f"
URL = f"https://flipkart.turbohire.co/dashboardv2?orgId={ORG}&type=0"
DEPARTMENTS = {"Technology", "CL-Engg"}


def timestamp(value):
    # TurboHire emits seven fractional digits; Python/DB datetimes store six.
    return re.sub(r"(\.\d{6})\d+(?=Z|[+-]\d\d:\d\d|$)", r"\1", value) if isinstance(value, str) else None


def normalize(item):
    locations = item.get("Location") or []
    if isinstance(locations, str):
        locations = json.loads(locations)
    addresses = [value.get("Address", "") for value in locations]
    if item.get("Department") not in DEPARTMENTS or not in_india({"locations": addresses}):
        return None
    description = item.get("JobDescV2") or ""
    if not isinstance(description, str) or not plain_text(description) or not item.get("JobId") or not item.get("JobTitle") or not item.get("JobIdObfuscated"):
        raise RuntimeError("Flipkart selected job missing full description or identity")
    return {"id": item["JobId"], "title": item["JobTitle"], "company": "Flipkart",
            "department": item["Department"], "country": "India", "locations": addresses,
            "source_job_code": item.get("JobCode"),
            "application_url": "https://flipkart.turbohire.co/job/publicjobs/" + item["JobIdObfuscated"],
            "posted_date": timestamp(item.get("PublishedDate")), "updated_date": timestamp(item.get("UpdatedDate")),
            "source_posted_date": item.get("PublishedDate"),
            "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=URL)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("Invalid limits")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page()
            with page.expect_response(lambda r: "/api/careerpagev2/filteredjobs?" in r.url and f"orgId={ORG}" in r.url,
                                      timeout=args.timeout * 1000) as response:
                page.goto(URL, wait_until="domcontentloaded", timeout=args.timeout * 1000)
            result = response.value
            if result.status != 200:
                raise RuntimeError(f"Flipkart public feed returned HTTP {result.status}")
            payload = result.json()
            if not isinstance(payload.get("Result"), list) or not isinstance(payload.get("Total"), int):
                raise RuntimeError("Flipkart public feed response shape changed")
            if len(payload["Result"]) != payload["Total"]:
                raise RuntimeError("Flipkart feed is paginated or incomplete; refusing to claim complete results")
            jobs = newest_first([job for item in payload["Result"] if (job := normalize(item)) is not None])
        finally:
            browser.close()
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, source=URL, global_results=payload["Total"], complete=True,
                   filters="Native Technology/CL-Engg departments and structured India addresses",
                   sort="PublishedDate descending before cap; UpdatedDate retained separately")
    print(f"Flipkart: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
