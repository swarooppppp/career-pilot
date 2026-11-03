#!/usr/bin/env python3
"""Fetch server-rendered Kula or Airbnb listings and public detail-page data."""
from __future__ import annotations
import argparse, html, json, re, sys
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen
UA="Mozilla/5.0 (compatible; CareerPilot/1.0)"
def get(u,t):
    with urlopen(Request(u,headers={"User-Agent":UA,"Accept":"text/html"}),timeout=t) as r:return r.read().decode("utf-8","replace")
def clean(s):return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",s)).split())
def locations_text(value):
 if not isinstance(value,list):value=[value]
 parts=[]
 for item in value:
  if not isinstance(item,dict):
   if item:parts.append(str(item))
   continue
  address=item.get("address")or{}
  if isinstance(address,str):parts.append(address);continue
  country=address.get("addressCountry","")
  if isinstance(country,dict):country=country.get("name","")
  if country=="IN":country="India"
  parts.append(", ".join(str(x) for x in [address.get("addressLocality"),address.get("addressRegion"),country] if x))
 return " | ".join(x for x in parts if x)
def detail(doc):
    for x in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',doc,re.I|re.S):
        try:d=json.loads(x)
        except json.JSONDecodeError:continue
        if isinstance(d,dict) and d.get("@type")=="JobPosting":return d
    return {"title":re.search(r'<h1[^>]*>(.*?)</h1>',doc,re.I|re.S).group(1) if re.search(r'<h1[^>]*>(.*?)</h1>',doc,re.I|re.S) else "", "description":doc}
def main():
 p=argparse.ArgumentParser();p.add_argument("url");p.add_argument("--company",required=True);p.add_argument("--kind",choices=("kula","airbnb"),required=True);p.add_argument("--department",default="");p.add_argument("--max-jobs",type=int,default=50);p.add_argument("--timeout",type=int,default=30);p.add_argument("--skip-job-id",action="append",default=[]);p.add_argument("--output",type=Path,required=True);a=p.parse_args(); listing=get(a.url,a.timeout)
 pattern=r'href=["\']([^"\']+/slice/[0-9]+-[^"\']+)["\']' if a.kind=="kula" else r'href=["\']([^"\']+/positions/[0-9]+/)["\']'
 links=list(dict.fromkeys(urljoin(a.url,x) for x in re.findall(pattern,listing,re.I)))
 jobs=[]
 for u in links:
  ident=(re.search(r'/([0-9]+)(?:-|/)',u) or [None,""])[1]
  if not ident or ident in set(a.skip_job_id):continue
  d=detail(get(u,a.timeout)); desc=str(d.get("description")or""); title=clean(str(d.get("title")or"")); loc=d.get("jobLocation","")
  loc=locations_text(loc)
  if a.department and a.department.casefold() not in (title+" "+desc).casefold():continue
  jobs.append({"id":ident,"title":title,"company":a.company,"location":loc,"application_url":u,"posted_date":d.get("datePosted"),"jobDescriptionHtml":desc,"jobDescriptionText":clean(desc)})
  if a.max_jobs and len(jobs)>=a.max_jobs:break
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({"input_url":a.url,"jobs":jobs},ensure_ascii=False,indent=2)+"\n");print(f"Wrote {len(jobs)} jobs to {a.output}",file=sys.stderr)
if __name__=="__main__":main()
