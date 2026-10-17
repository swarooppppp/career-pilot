#!/usr/bin/env python3
"""Fetch India jobs from a Palo Alto Networks public search URL.

Palo Alto's country facet is browser-session dependent. This adapter pages the
public search results and enforces the India scope using each job page's public
JobPosting structured data before a record is emitted.
"""
from __future__ import annotations
import argparse, html, json, re, sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen

BASE = "https://jobs.paloaltonetworks.com"
USER_AGENT = "Mozilla/5.0 (compatible; CareerPilot/1.0)"

def read(url: str, timeout: int) -> str:
    try:
        with urlopen(Request(url, headers={"User-Agent":USER_AGENT,"Accept":"text/html"}),timeout=timeout) as response:
            return response.read().decode(response.headers.get_content_charset() or "utf-8",errors="replace")
    except HTTPError as exc: raise RuntimeError(f"Palo Alto Networks returned HTTP {exc.code} for {url}") from exc
    except URLError as exc: raise RuntimeError(f"Could not reach Palo Alto Networks Careers: {exc.reason}") from exc

def page_url(url: str, page: int) -> str:
    parsed=urlsplit(url); path=re.sub(r"/\d+/?$",f"/{page}",parsed.path)
    return urlunsplit((parsed.scheme,parsed.netloc,path,parsed.query,parsed.fragment))

def job_posting(document: str, url: str) -> dict:
    for payload in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',document,re.I|re.S):
        try: value=json.loads(html.unescape(payload))
        except json.JSONDecodeError: continue
        for candidate in value if isinstance(value,list) else [value]:
            if isinstance(candidate,dict) and candidate.get("@type")=="JobPosting": return candidate
    raise RuntimeError(f"Palo Alto detail page lacks JobPosting data: {url}")

def is_india(posting: dict) -> bool:
    location=posting.get("jobLocation") or []
    if isinstance(location,dict): location=[location]
    for entry in location:
        address=(entry or {}).get("address") or {}
        country=str(address.get("addressCountry") or "").casefold()
        if country in {"in","india"}: return True
    return False

def fetch_jobs(url: str, max_pages: int, max_jobs: int, timeout: int, skip_ids: set[str]) -> list[dict]:
    jobs=[]; seen=set()
    for page in range(1,max_pages+1):
        listing=read(page_url(url,page),timeout)
        links=re.findall(r'href=["\']([^"\']*/en/job/[^"\']+/\d+/\d+)["\']',listing,re.I)
        if not links: break
        new_links=0
        for href in links:
            detail_url=urljoin(BASE,html.unescape(href)); match=re.search(r"/(\d+)$",urlsplit(detail_url).path)
            if not match or match.group(1) in seen: continue
            new_links+=1; job_id=match.group(1); seen.add(job_id)
            if job_id in skip_ids: continue
            posting=job_posting(read(detail_url,timeout),detail_url)
            if not is_india(posting): continue
            description=str(posting.get("description") or "")
            location=posting.get("jobLocation") or []; location=location if isinstance(location,list) else [location]
            locations=" | ".join(", ".join(filter(None,[(item.get("address") or {}).get("addressLocality"),(item.get("address") or {}).get("addressRegion"),(item.get("address") or {}).get("addressCountry")])) for item in location)
            jobs.append({"id":job_id,"title":posting.get("title", ""),"company":"Palo Alto Networks","location":locations,"posted_date":posting.get("datePosted", ""),"employment_type":posting.get("employmentType", ""),"application_url":detail_url,"jobDescriptionHtml":description,"jobDescriptionText":" ".join(re.sub(r"<[^>]+>"," ",html.unescape(description)).split())})
            if max_jobs and len(jobs)>=max_jobs: return jobs
        if new_links==0: break
    return jobs

def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("url");parser.add_argument("--max-pages",type=int,default=10);parser.add_argument("--max-jobs",type=int,default=50);parser.add_argument("--timeout",type=int,default=30);parser.add_argument("--skip-job-id",action="append",default=[]);parser.add_argument("--output",type=Path,default=Path("palo_alto_jobs.json"));args=parser.parse_args()
    try: jobs=fetch_jobs(args.url,args.max_pages,args.max_jobs,args.timeout,set(args.skip_job_id))
    except RuntimeError as exc: print(f"Error: {exc}",file=sys.stderr);return 1
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({"input_url":args.url,"jobs":jobs},indent=2)+"\n",encoding="utf-8");print(f"Wrote {len(jobs)} India-only Palo Alto Networks jobs to {args.output}",file=sys.stderr);return 0
if __name__=="__main__":raise SystemExit(main())
