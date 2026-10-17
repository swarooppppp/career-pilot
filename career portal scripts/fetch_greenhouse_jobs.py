#!/usr/bin/env python3
"""Fetch a public Greenhouse board, filtering before emitting job records."""
from __future__ import annotations
import argparse, html, json, re, sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

UA = "Mozilla/5.0 (compatible; CareerPilot/1.0)"
def get(url: str, timeout: int) -> dict:
    try:
        with urlopen(Request(url, headers={"Accept":"application/json", "User-Agent":UA}), timeout=timeout) as r: return json.load(r)
    except HTTPError as e: raise RuntimeError(f"Greenhouse returned HTTP {e.code}") from e
    except URLError as e: raise RuntimeError(f"Could not reach Greenhouse: {e.reason}") from e
def text(value: str) -> str: return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value)).split())
def fetch(board: str, company: str, query: str, location: str, department: str, max_jobs: int, timeout: int, skip: set[str]) -> list[dict]:
    payload = get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true", timeout)
    jobs=[]
    for item in payload.get("jobs", []):
        ident=str(item.get("id") or ""); title=str(item.get("title") or ""); loc=str((item.get("location") or {}).get("name") or "")
        departments=" ".join(x.get("name", "") for x in item.get("departments", []) if isinstance(x,dict))
        haystack=f"{title} {loc} {departments}".casefold()
        if not ident or ident in skip or (query and query.casefold() not in title.casefold()) or (location and location.casefold() not in loc.casefold()) or (department and department.casefold() not in departments.casefold()): continue
        desc=str(item.get("content") or "")
        jobs.append({"id":ident,"title":title,"company":company,"location":loc,"department":departments,"updated_date":item.get("updated_at", ""),"application_url":item.get("absolute_url", ""),"jobDescriptionHtml":desc,"jobDescriptionText":text(desc)})
        if max_jobs and len(jobs)>=max_jobs: break
    return jobs
def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--board",required=True); p.add_argument("--company",required=True); p.add_argument("--query",default=""); p.add_argument("--location",default=""); p.add_argument("--department",default=""); p.add_argument("--max-jobs",type=int,default=50); p.add_argument("--timeout",type=int,default=30); p.add_argument("--skip-job-id",action="append",default=[]); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    try: jobs=fetch(a.board,a.company,a.query,a.location,a.department,a.max_jobs,a.timeout,set(a.skip_job_id))
    except RuntimeError as e: print(f"Error: {e}",file=sys.stderr); return 1
    a.output.parent.mkdir(parents=True,exist_ok=True); a.output.write_text(json.dumps({"source":"Greenhouse public board API","jobs":jobs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(f"Wrote {len(jobs)} jobs to {a.output}",file=sys.stderr); return 0
if __name__=="__main__": raise SystemExit(main())
