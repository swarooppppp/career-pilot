#!/usr/bin/env python3
"""Fetch Cornerstone careers jobs through a temporary Playwright guest session."""
from __future__ import annotations
import argparse, asyncio, html, json, sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright
DEFAULT_URL="https://cornerstone.csod.com/ux/ats/careersite/2/home?c=cornerstone&sq=software%20engineer&lq=India&pl=ChIJkbeSa_BfYzARphNChaFPjNc"
class T(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.p=[]
 def handle_data(self,d):self.p.append(d)
 def text(self):return " ".join("".join(self.p).split())
async def fetch(url:str,headed:bool,timeout:int)->list[dict[str,Any]]:
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=not headed);page=await b.new_page(); captured=[]
  async def response(r):
   if "rec-job-search/external/jobs" in r.url and r.status==200:
    try: captured.append(await r.json())
    except: pass
  page.on("response",response); await page.goto(url,wait_until="networkidle",timeout=timeout*1000); await page.wait_for_timeout(1500); await b.close()
 if not captured: raise RuntimeError("Cornerstone did not return a jobs response; retry with --headed")
 return captured[-1].get("data",{}).get("requisitions",[])
def normalise(row:dict[str,Any])->dict[str,Any]|None:
 jid=str(row.get("requisitionId") or "");desc=str(row.get("externalDescription") or "");title=str(row.get("displayJobTitle") or "")
 if not jid or not title or not desc:return None
 t=T();t.feed(desc);t.close(); loc=" + ".join(f"{x.get('city','')}, {x.get('country','')}".strip(", ") for x in row.get("locations",[]) if isinstance(x,dict))
 return {"id":jid,"title":title,"company":"Cornerstone","location":loc,"posted_date":row.get("postingEffectiveDate"),"application_url":str(row.get("externalUrl") or ""),"jobDescriptionHtml":desc,"jobDescriptionText":html.unescape(t.text())}
def main()->int:
 a=argparse.ArgumentParser(description=__doc__);a.add_argument("url",nargs="?",default=DEFAULT_URL);a.add_argument("--max-jobs",type=int,default=50);a.add_argument("--timeout",type=int,default=45);a.add_argument("--headed",action="store_true");a.add_argument("--output",type=Path,default=Path("cornerstone_jobs.json"));x=a.parse_args()
 try: jobs=[j for r in asyncio.run(fetch(x.url,x.headed,x.timeout)) if (j:=normalise(r))][:x.max_jobs or None]
 except Exception as e:print(f"Error: {e}",file=sys.stderr);return 1
 x.output.parent.mkdir(parents=True,exist_ok=True);x.output.write_text(json.dumps({"source":"Cornerstone guest browser session","input_url":x.url,"jobs_fetched":len(jobs),"jobs":jobs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8");return 0
if __name__=="__main__":raise SystemExit(main())
