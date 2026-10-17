#!/usr/bin/env python3
"""Fetch a filtered public Eightfold PCSx tenant into Career Pilot records."""
from __future__ import annotations
import argparse, html, json, sys, time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
BASE_URL="https://app.eightfold.ai"; PAGE_SIZE=10
class TextParser(HTMLParser):
    def __init__(self)->None: super().__init__(convert_charrefs=True); self.parts:list[str]=[]
    def handle_starttag(self,tag:str,attrs:list[tuple[str,str|None]])->None:
        if tag in {"br","p","div","li","h1","h2","h3"}: self.parts.append("\n")
        if tag=="li": self.parts.append("- ")
    def handle_data(self,data:str)->None:self.parts.append(data)
    def text(self)->str:return "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.parts).splitlines()) if line)
def get_json(path:str,params:dict[str,Any],timeout:int)->dict[str,Any]:
    url=f"{BASE_URL}{path}?{urlencode(params,doseq=True)}"
    try:
        with urlopen(Request(url,headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 (compatible; CareerPilotEightfoldFetcher/1.0)"}),timeout=timeout) as response: payload=json.load(response)
    except HTTPError as error: raise RuntimeError(f"Eightfold returned HTTP {error.code} for {url}") from error
    except URLError as error: raise RuntimeError(f"Could not reach Eightfold: {error.reason}") from error
    if payload.get("status")!=200 or not isinstance(payload.get("data"),dict): raise RuntimeError("Eightfold returned an unexpected response")
    return payload["data"]
def search(args:argparse.Namespace,start:int)->dict[str,Any]:
    params:dict[str,Any]={"domain":args.domain,"query":args.query,"location":args.location,"start":str(start),"sort_by":args.sort_by,"filter_include_remote":"1" if args.include_remote else "0","filter_include_relocation":"1" if args.include_relocation else "0"}
    if args.seniority: params["filter_seniority"]=[x.strip() for x in args.seniority.split(",") if x.strip()]
    for value in args.filter:
        key, separator, filter_value = value.partition("=")
        if not separator or not key or not filter_value:
            raise ValueError("--filter values must use name=value")
        params[key] = [item.strip() for item in filter_value.split(",") if item.strip()]
    return get_json("/api/pcsx/search",params,args.timeout)
def detail(job_id:str,args:argparse.Namespace)->dict[str,Any]: return get_json("/api/pcsx/position_details",{"position_id":job_id,"domain":args.domain,"hl":args.locale,"queried_location":args.location},args.timeout)
def main()->int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--domain",default="volkscience.com"); p.add_argument("--company",default=""); p.add_argument("--query",default=""); p.add_argument("--location",default="Bengaluru, KA, India"); p.add_argument("--sort-by",default="timestamp"); p.add_argument("--seniority",default="1,2"); p.add_argument("--filter",action="append",default=[],help="Public Eightfold search filter, e.g. filter_job_family=software engineering"); p.add_argument("--include-remote",action=argparse.BooleanOptionalAction,default=True); p.add_argument("--include-relocation",action=argparse.BooleanOptionalAction,default=False); p.add_argument("--locale",default="en"); p.add_argument("--max-pages",type=int,default=5); p.add_argument("--max-jobs",type=int,default=50); p.add_argument("--timeout",type=int,default=30); p.add_argument("--delay",type=float,default=.5); p.add_argument("--skip-job-id",action="append",default=[]); p.add_argument("--output",type=Path,default=Path("eightfold_jobs.json")); args=p.parse_args()
    try:
        first=search(args,0); summaries=list(first.get("positions",[])); total=int(first.get("count") or len(summaries)); pages=min(args.max_pages,(total+PAGE_SIZE-1)//PAGE_SIZE)
        for page in range(1,pages): summaries.extend(search(args,page*PAGE_SIZE).get("positions",[])); time.sleep(args.delay)
        if args.max_jobs:summaries=summaries[:args.max_jobs]
        jobs=[]; known=set(args.skip_job_id)
        for i,summary in enumerate(summaries,1):
            job_id=str(summary.get("id") or "")
            if not job_id or job_id in known: print(f"Skipping existing {i}/{len(summaries)}: {job_id}",file=sys.stderr); continue
            print(f"Fetching {i}/{len(summaries)}: {job_id}",file=sys.stderr); item=detail(job_id,args); description=str(item.get("jobDescription") or ""); parser=TextParser(); parser.feed(description); parser.close()
            if description: jobs.append({"id":job_id,"title":item.get("title") or summary.get("title") or "","company":args.company or args.domain,"location":item.get("location") or summary.get("location") or "","application_url":item.get("publicUrl") or item.get("positionUrl") or "","jobDescriptionHtml":description,"jobDescriptionText":html.unescape(parser.text())})
            if i!=len(summaries):time.sleep(args.delay)
    except RuntimeError as error: print(f"Error: {error}",file=sys.stderr); return 1
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps({"source":"Eightfold PCSx public API","domain":args.domain,"jobs_fetched":len(jobs),"jobs":jobs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); return 0
if __name__=="__main__":raise SystemExit(main())
