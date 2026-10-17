#!/usr/bin/env python3
"""Fetch Mastercard Engineering jobs from public server-rendered Phenom data."""
from __future__ import annotations
import argparse, html, json, re, sys, time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

BASE="https://careers.mastercard.com"; USER_AGENT="Mozilla/5.0 (compatible; CareerPilot/1.0)"
def read(url:str,timeout:int)->str:
    try:
        with urlopen(Request(url,headers={"User-Agent":USER_AGENT,"Accept":"text/html"}),timeout=timeout) as r:return r.read().decode(r.headers.get_content_charset() or "utf-8",errors="replace")
    except HTTPError as e:raise RuntimeError(f"Mastercard returned HTTP {e.code}") from e
    except URLError as e:raise RuntimeError(f"Could not reach Mastercard Careers: {e.reason}") from e
def embedded(document:str,key:str)->dict:
    try:return json.JSONDecoder().raw_decode(document.split("phApp.ddo = ",1)[1])[0][key]
    except (IndexError,KeyError,json.JSONDecodeError) as e:raise RuntimeError(f"Mastercard page lacks {key} data") from e
def search_url(url:str,offset:int)->str:
    p=urlparse(url);q=[x for x in parse_qsl(p.query,keep_blank_values=True) if x[0] not in {"from","category"}];q.extend([("category","Engineering"),("from",str(offset))]);return urlunparse(p._replace(query=urlencode(q)))
def slug(title:str)->str:return quote(re.sub(r"[^a-z0-9]+","-",title.casefold()).strip("-"),safe="-")
def detail_url(job:dict)->str:return f"{BASE}/us/en/job/{quote(str(job['reqId']),safe='')}/{slug(str(job['title']))}"
def fetch_jobs(url:str,max_jobs:int,timeout:int,delay:float,skip:set[str])->list[dict]:
    first=embedded(read(search_url(url,0),timeout),"eagerLoadRefineSearch"); summaries=list(first["data"]["jobs"]);size=int(first.get("hits") or len(summaries));total=int(first.get("totalHits") or len(summaries));wanted=min(total,max_jobs) if max_jobs else total
    for offset in range(size,wanted,size):summaries.extend(embedded(read(search_url(url,offset),timeout),"eagerLoadRefineSearch")["data"]["jobs"])
    jobs=[]
    for summary in summaries[:wanted]:
        job_id=str(summary.get("reqId") or summary.get("jobId") or "")
        if not job_id or job_id in skip:continue
        detail=embedded(read(detail_url(summary),timeout),"jobDetail").get("data",{}).get("job",{})
        description=str(detail.get("description") or "")
        categories=summary.get("multi_category") or [summary.get("category", "")]
        category_text=" | ".join(str(item.get("category") if isinstance(item,dict) else item) for item in categories)
        jobs.append({"id":job_id,"title":detail.get("title",summary.get("title","")),"company":"Mastercard","location":detail.get("location",summary.get("location", "")),"department":category_text,"employment_type":detail.get("type",summary.get("type", "")),"posted_date":detail.get("postedDate",summary.get("postedDate", "")),"application_url":detail.get("applyUrl",summary.get("applyUrl",detail_url(summary))),"jobDescriptionHtml":description,"jobDescriptionText":" ".join(re.sub(r"<[^>]+>"," ",html.unescape(description)).split())})
        if max_jobs and len(jobs)>=max_jobs:break
        time.sleep(delay)
    return jobs
def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("url");p.add_argument("--max-jobs",type=int,default=50);p.add_argument("--timeout",type=int,default=30);p.add_argument("--delay",type=float,default=.5);p.add_argument("--skip-job-id",action="append",default=[]);p.add_argument("--output",type=Path,default=Path("mastercard_jobs.json"));a=p.parse_args()
    try:jobs=fetch_jobs(a.url,a.max_jobs,a.timeout,a.delay,set(a.skip_job_id))
    except RuntimeError as e:print(f"Error: {e}",file=sys.stderr);return 1
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({"input_url":a.url,"jobs":jobs},indent=2)+"\n",encoding="utf-8");print(f"Wrote {len(jobs)} Mastercard Engineering jobs to {a.output}",file=sys.stderr);return 0
if __name__=="__main__":raise SystemExit(main())
