#!/usr/bin/env python3
"""NVIDIA PCSx and Millennium v2 public careers adapters."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from common import newest_first, plain_text, write_snapshot
from fetch_filtered_board_jobs import read
from filters import engineering_title, in_india

SOURCES = {"nvidia": ("https://jobs.nvidia.com", "nvidia.com", "NVIDIA", "pcsx"),
           "millennium": ("https://career.mlp.com", "mlp.com", "Millennium Management", "v2")}


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if isinstance(value, (int, float)) and value > 0 else None


def unwrap(payload, version):
    if version == "pcsx":
        if payload.get("status") != 200 or not isinstance(payload.get("data"), dict):
            raise RuntimeError("Unexpected Eightfold PCSx response")
        return payload["data"]
    return payload


def normalize(summary, detail, origin, company, version):
    description = detail.get("jobDescription") or detail.get("job_description") or ""
    if not description:
        raise RuntimeError("Full job description unavailable")
    result = {"id": str(summary["id"]), "title": detail.get("name") or summary.get("name"), "company": company,
              "department": detail.get("department") or summary.get("department"),
              "location": detail.get("location") or summary.get("location") or "",
              "locations": detail.get("locations") or summary.get("locations") or [],
              "application_url": urljoin(origin, detail.get("canonicalPositionUrl") or detail.get("publicUrl") or detail.get("positionUrl") or summary.get("positionUrl") or f"/careers/job/{summary['id']}"),
              "posted_date": iso(summary.get("postedTs")), "updated_date": iso(detail.get("t_update") or summary.get("t_update")),
              "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--source", choices=SOURCES, required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    origin, domain, company, version = SOURCES[args.source]
    query = parse_qs(urlsplit(args.url).query)
    summaries, seen, total = [], set(), 0
    for page_number in range(args.max_pages):
        params = {"domain": domain, "query": query.get("query", ["Software Engineer"])[0], "location": "India", "start": page_number * 10, "sort_by": "timestamp"}
        if version == "pcsx":
            endpoint = "/api/pcsx/search"
            params["filter_job_category"] = "engineering"
        else:
            endpoint = "/api/apply/v2/jobs"
            params["num"] = 10
        data = unwrap(json.loads(read(origin + endpoint + "?" + urlencode(params), args.timeout)), version)
        if not isinstance(data.get("positions"), list) or "count" not in data:
            raise RuntimeError("Careers listing shape changed")
        if version == "pcsx" and "engineering" not in (data.get("appliedFilters") or {}).get("jobCategory", []):
            raise RuntimeError("NVIDIA did not confirm the Engineering facet")
        total = int(data["count"])
        for summary in data["positions"]:
            ident = str(summary["id"])
            if ident not in seen and in_india(summary) and engineering_title({"title": summary.get("name")}):
                summaries.append(summary)
                seen.add(ident)
        if (args.max_jobs and len(summaries) >= args.max_jobs) or (page_number + 1) * 10 >= total or not data["positions"]:
            break
        time.sleep(args.delay)
    if args.max_jobs:
        summaries = summaries[:args.max_jobs]
    jobs = []
    for summary in summaries:
        time.sleep(args.delay)
        path = "/api/pcsx/position_details" if version == "pcsx" else f"/api/apply/v2/jobs/{summary['id']}"
        params = {"domain": domain}
        if version == "pcsx":
            params.update(position_id=summary["id"], hl="en")
        detail = unwrap(json.loads(read(origin + path + "?" + urlencode(params), args.timeout)), version)
        job = normalize(summary, detail, origin, company, version)
        if in_india(job):
            jobs.append(job)
    write_snapshot(args.output, newest_first(jobs), input_url=args.url, source=origin, api_version=version,
                   total_results=total, filters="India and conservative engineering titles; native NVIDIA Engineering facet",
                   date_basis="postedTs" if version == "pcsx" else "t_update (update date, not publication date)")
    print(f"{company}: wrote {len(jobs)} Engineering/India jobs")


if __name__ == "__main__":
    main()
