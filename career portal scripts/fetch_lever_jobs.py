#!/usr/bin/env python3
"""Fetch a public Lever board and retain supplied department/location filters."""
from __future__ import annotations
import argparse, html, json, re, sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
UA="Mozilla/5.0 (compatible; CareerPilot/1.0)"
def get(url:str,timeout:int)->list[dict]:
    try:
        with urlopen(Request(url,headers={"Accept":"application/json","User-Agent":UA}),timeout=timeout) as r:return json.load(r)
    except HTTPError as e:raise RuntimeError(f"Lever returned HTTP {e.code}") from e
    except URLError as e:raise RuntimeError(f"Could not reach Lever: {e.reason}") from e
def clean(v:str)->str:return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",v)).split())
def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--site",required=True);p.add_argument("--company",required=True);p.add_argument("--team",default="");p.add_argument("--location",default="");p.add_argument("--query",default="");p.add_argument("--max-jobs",type=int,default=50);p.add_argument("--timeout",type=int,default=30);p.add_argument("--skip-job-id",action="append",default=[]);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    try: postings=get(f"https://api.lever.co/v0/postings/{a.site}?mode=json",a.timeout)
    except RuntimeError as e:print(f"Error: {e}",file=sys.stderr);return 1
    jobs=[]; skip=set(a.skip_job_id)
    for x in postings:
        ident=str(x.get("id")or""); title=str(x.get("text")or""); cats=x.get("categories")or{}; loc=str(cats.get("location")or""); team=str(cats.get("team")or"")
        if not ident or ident in skip or (a.team and a.team.casefold() not in team.casefold()) or (a.location and a.location.casefold() not in loc.casefold()) or (a.query and a.query.casefold() not in title.casefold()):continue
        desc=str(x.get("description")or"")+str(x.get("additional")or"")
        jobs.append({"id":ident,"title":title,"company":a.company,"location":loc,"department":team,"employment_type":cats.get("commitment", ""),"application_url":x.get("hostedUrl", ""),"jobDescriptionHtml":desc,"jobDescriptionText":clean(desc)})
        if a.max_jobs and len(jobs)>=a.max_jobs:break
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({"source":"Lever public postings API","jobs":jobs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(f"Wrote {len(jobs)} jobs to {a.output}",file=sys.stderr);return 0
if __name__=="__main__":raise SystemExit(main())
