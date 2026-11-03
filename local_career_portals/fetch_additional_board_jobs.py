#!/usr/bin/env python3
"""Filtered public Greenhouse adapters for the third company batch."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from common import newest_first, write_snapshot
from fetch_filtered_board_jobs import normalize, read, metadata
from filters import in_india, engineering_title

SOURCES = {"razorpay": ("razorpaysoftwareprivatelimited", "Razorpay"),
           "fivetran": ("fivetran", "Fivetran"), "cockroach_labs": ("cockroachlabs", "Cockroach Labs"),
           "airbnb": ("airbnb", "Airbnb"), "coinbase": ("coinbase", "Coinbase"),
           "squarepoint": ("squarepointcapital", "Squarepoint Capital"),
           "tower_research": ("towerresearchcapital", "Tower Research"),
           "moloco": ("moloco", "Moloco"), "arcesium": ("arcesiumllc", "Arcesium"),
           "adyen": ("adyen", "Adyen"), "samsara": ("samsara", "Samsara"),
           "wiz": ("wizinc", "Wiz"), "okta": ("okta", "Okta"),
           "jfrog": ("jfrog", "JFrog"), "netskope": ("netskope", "Netskope"),
           "sentinelone": ("sentinellabs", "SentinelOne"),
           "pure_storage": ("purestorage", "Pure Storage (Everpure)"),
           "commvault": ("commvault", "Commvault"), "veeam": ("veeamsoftware", "Veeam Software"),
           "gitlab": ("gitlab", "GitLab"), "grafana_labs": ("grafanalabs", "Grafana Labs"),
           "elastic": ("elastic", "Elastic"),
           "yugabyte": ("yugabyte", "Yugabyte"), "singlestore": ("singlestore", "SingleStore"),
           "startree": ("startree", "StarTree"), "prophecy": ("prophecysimpledatalabs", "Prophecy AI"),
           "devrev": ("devrev", "DevRev"), "endor_labs": ("endorlabs", "Endor Labs"),
           "instabase": ("instabase", "Instabase"),
           "miro": ("realtimeboardglobal", "Miro"), "bloomreach": ("bloomreach", "Bloomreach"),
           "apollo": ("apolloio", "Apollo.io"), "flexport": ("flexport", "Flexport"),
           "bitgo": ("bitgo", "BitGo"), "quince": ("quince", "Quince"),
           "groww": ("groww", "Groww"), "anthropic": ("anthropic", "Anthropic"),
           "digitalocean": ("digitalocean98", "DigitalOcean")}

NATIVE_TEAMS = {"startree": {"Engineering"},
                "devrev": {"Engineering", "Engineering - Applied AI Engineering", "R&D"},
                "endor_labs": {"Engineering"}, "bloomreach": {"Engineering"},
                "apollo": {"Engineering"}, "bitgo": {"Engineering"}}


def department_ids(jobs, roots):
    selected = set(roots)
    departments = {d["id"]: d for job in jobs for d in job.get("departments", [])}
    while True:
        previous = len(selected)
        for ident, department in departments.items():
            if ident in selected:
                selected.update(department.get("child_ids", []))
            if department.get("parent_id") in selected:
                selected.add(ident)
        if len(selected) == previous:
            return selected


def location_key(value):
    value = value.strip().casefold().replace("bangalore", "bengaluru")
    return re.sub(r",\s*(apac|emea|amer)$", "", value)


def select_jobs(jobs, source, url):
    query = parse_qs(urlparse(url).query)
    if source in {"yugabyte", "singlestore", "startree", "prophecy", "devrev", "endor_labs", "instabase",
                  "miro", "bloomreach", "apollo", "flexport", "bitgo", "quince", "groww", "anthropic", "digitalocean"}:
        jobs = [j for j in jobs if not re.search(
            r"\b(?:talent community|talent pool|future opportunities|general application|expressions? of interest)\b",
            j.get("title", ""), re.I)]
    if source in NATIVE_TEAMS:
        roots = {d["id"] for j in jobs for d in j.get("departments", []) if d.get("name") in NATIVE_TEAMS[source]}
        allowed = department_ids(jobs, roots)
        return [j for j in jobs if in_india(j) and any(d["id"] in allowed for d in j.get("departments", []))]
    if source == "quince":
        roots = {d["id"] for j in jobs for d in j.get("departments", []) if re.search(r"\bengineering\b", d.get("name", ""), re.I)}
        allowed = department_ids(jobs, roots)
        return [j for j in jobs if in_india(j) and any(d["id"] in allowed for d in j.get("departments", []))]
    if source in {"yugabyte", "singlestore", "prophecy", "instabase", "miro", "flexport", "groww", "anthropic", "digitalocean"}:
        return [job for job in jobs if in_india(job) and engineering_title(job)
                and not any(re.search(r"\b(?:sales|support|customer success|consulting|professional services)\b|^SA\s*-|\bSE$",
                                      d.get("name", ""), re.I) for d in job.get("departments", []))]
    if source in {"commvault", "veeam", "gitlab", "grafana_labs", "elastic"}:
        return [job for job in jobs if in_india(job) and engineering_title(job)
                and not any(re.search(r"\b(?:sales|support|customer success|consulting|professional services)\b|^SA\s*-",
                                      d.get("name", ""), re.I) for d in job.get("departments", []))]
    if source in {"adyen", "samsara", "wiz", "okta", "jfrog", "netskope", "sentinelone", "pure_storage"}:
        # Their technical departments span Development, Infrastructure, Safety
        # AI, Platform and many SW-Eng subteams. Do not require one literal label.
        return [job for job in jobs if in_india(job) and engineering_title(job)
                and not any(re.search(r"\b(?:sales|support|customer success)\b", d.get("name", ""), re.I)
                            for d in job.get("departments", []))]
    if source == "razorpay":
        roots = {int(value) for value in query.get("departments[]", ["4024806005"])}
        allowed = department_ids(jobs, roots)
        return [j for j in jobs if in_india(j) and any(d["id"] in allowed for d in j.get("departments", []))]
    department = query.get("dept", ["Engineering Department"])[0] if source == "fivetran" else "Engineering"
    if source == "airbnb":
        names = {"Software Engineering", "Engineering & Technology"}
    elif source in {"squarepoint", "arcesium"}:
        names = {"Technology"}
    elif source == "coinbase":
        names = {d["name"] for j in jobs for d in j.get("departments", []) if d.get("name", "").startswith("Engineering")}
    elif source == "tower_research":
        names = {d["name"] for j in jobs for d in j.get("departments", []) if "Engineering" in d.get("name", "")}
    else:
        names = {department}
    roots = {d["id"] for j in jobs for d in j.get("departments", []) if d.get("name") in names}
    allowed = department_ids(jobs, roots)
    results = [j for j in jobs if in_india(j) and
               (any(d["id"] in allowed for d in j.get("departments", []))
                or (source in {"coinbase", "tower_research", "squarepoint"} and engineering_title(j)))]
    if source in {"squarepoint", "arcesium"}:
        results = [j for j in results if engineering_title(j)]
    if source == "fivetran":
        locations = {location_key(value) for value in query.get("loc", [])}
        employment = query.get("type", ["Regular"])[0]
        results = [j for j in results if metadata(j, "Employee Type") == employment
                   and (not locations or location_key((j.get("location") or {}).get("name", "")) in locations)]
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--source", choices=SOURCES, required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("Invalid limit or timeout")
    board, company = SOURCES[args.source]
    endpoint = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
    payload = json.loads(read(endpoint, args.timeout))
    if not isinstance(payload.get("jobs"), list):
        raise RuntimeError("Board response is missing jobs")
    selected = select_jobs(payload["jobs"], args.source, args.url)
    jobs = []
    for original in selected:
        job = normalize(original, company)
        job["source_departments"] = [d["name"] for d in original.get("departments", [])]
        job["employer_name"] = original.get("company_name") or company
        jobs.append(job)
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, source=endpoint,
                   global_results=len(payload["jobs"]), total_filtered_results=len(selected), complete=True,
                   filters="Engineering department (including descendants), India, plus supplied source facets",
                   sort="first publication descending; updated date fallback")
    print(f"{company}: wrote {len(jobs)} filtered jobs")


if __name__ == "__main__":
    main()
