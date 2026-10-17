#!/usr/bin/env python3
"""Fetch American Express jobs from its public Oracle Recruiting endpoint."""
from __future__ import annotations
import argparse, html, json, re, sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlparse
from urllib.request import Request, urlopen

BASE = "https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilot/1.0)"

def get(url: str, timeout: int) -> dict:
    try:
        with urlopen(Request(url, headers={"Accept":"application/json","User-Agent":USER_AGENT}), timeout=timeout) as response: return json.load(response)
    except HTTPError as exc: raise RuntimeError(f"American Express returned HTTP {exc.code}") from exc
    except URLError as exc: raise RuntimeError(f"Could not reach American Express Careers: {exc.reason}") from exc

def fetch_jobs(url: str, max_jobs: int, timeout: int, skip_ids: set[str]) -> list[dict]:
    query = parse_qs(urlparse(url).query); keyword=query.get("keyword",[""])[0]; location=query.get("locationId",[""])[0]
    jobs=[]; offset=0; limit=20
    while not max_jobs or len(jobs)<max_jobs:
        finder=("findReqs;siteNumber=CX_1,facetsList=WORK_LOCATIONS%3BWORKPLACE_TYPES%3BTITLES%3BCATEGORIES%3BORGANIZATIONS%3BPOSTING_DATES%3BFLEX_FIELDS%3BLOCATIONS,"
                f"limit={limit},offset={offset},keyword={json.dumps(keyword)},locationId={location},sortBy=POSTING_DATES_DESC")
        search=get(f"{BASE}/recruitingCEJobRequisitions?onlyData=true&expand=requisitionList.workLocation&finder={quote(finder, safe=';,%')}",timeout)
        item=(search.get("items") or [{}])[0]; postings=item.get("requisitionList") or []
        if not postings: break
        for posting in postings:
            job_id=str(posting.get("Id") or "")
            if not job_id or job_id in skip_ids: continue
            detail_response=get(f"{BASE}/recruitingCEJobRequisitionDetails?expand=all&onlyData=true&finder=ById;Id={json.dumps(job_id)},siteNumber=CX_1",timeout)
            detail=(detail_response.get("items") or [{}])[0]
            description="\n".join(str(detail.get(field) or "") for field in ("ExternalDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
            jobs.append({"id":job_id,"title":posting.get("Title", ""),"company":"American Express","location":posting.get("PrimaryLocation", ""),"posted_date":posting.get("PostedDate", ""),"employment_type":posting.get("WorkplaceType", ""),"application_url":f"https://careers.americanexpress.com/en/sites/CX_1/job/{job_id}","jobDescriptionHtml":description,"jobDescriptionText":" ".join(re.sub(r"<[^>]+>"," ",html.unescape(description)).split())})
            if max_jobs and len(jobs)>=max_jobs: return jobs
        offset += len(postings)
        if offset>=int(item.get("TotalJobsCount",0)): break
    return jobs

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("url");parser.add_argument("--max-jobs",type=int,default=50);parser.add_argument("--timeout",type=int,default=30);parser.add_argument("--skip-job-id",action="append",default=[]);parser.add_argument("--output",type=Path,default=Path("american_express_jobs.json"));args=parser.parse_args()
    try: jobs=fetch_jobs(args.url,args.max_jobs,args.timeout,set(args.skip_job_id))
    except RuntimeError as exc: print(f"Error: {exc}",file=sys.stderr);return 1
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({"input_url":args.url,"jobs":jobs},indent=2)+"\n",encoding="utf-8");print(f"Wrote {len(jobs)} American Express jobs to {args.output}",file=sys.stderr);return 0
if __name__=="__main__":raise SystemExit(main())
