#!/usr/bin/env python3
"""Fetch Stripe's server-rendered filtered careers results and JSON-LD details."""
from __future__ import annotations
import argparse, html, json, re, sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
UA="Mozilla/5.0 (compatible; CareerPilot/1.0)"
def page(url:str,timeout:int)->str:
    try:
        with urlopen(Request(url,headers={"User-Agent":UA,"Accept":"text/html"}),timeout=timeout) as r:return r.read().decode("utf-8","replace")
    except HTTPError as e:raise RuntimeError(f"Stripe returned HTTP {e.code}") from e
    except URLError as e:raise RuntimeError(f"Could not reach Stripe: {e.reason}") from e
def ld(html_doc:str)->dict:
    for raw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',html_doc,re.I|re.S):
        # JSON-LD uses JSON escapes (not HTML entities); unescaping first can
        # turn a valid escaped quote inside the description into invalid JSON.
        try: item=json.loads(raw)
        except json.JSONDecodeError:continue
        if isinstance(item,dict) and item.get("@type")=="JobPosting":return item
    raise RuntimeError("Stripe detail page did not contain JobPosting JSON-LD")
def clean(v:str)->str:return " ".join(html.unescape(re.sub(r"<[^>]+>"," ",v)).split())
def filtered_links(url: str, timeout: int) -> list[tuple[str, str]]:
    """Let Stripe apply the supplied URL filters, then read stable role URLs."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True, executable_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
            tab=browser.new_page(); tab.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            hrefs=tab.locator('a[href*="/careers/listing/"]').evaluate_all("els => els.map(e => e.getAttribute('href'))")
            browser.close()
        return list(dict.fromkeys((m.group(1),m.group(2)) for href in hrefs if href and (m:=re.search(r"/careers/listing/([^?#/]+)/([0-9]+)",href))))
    except Exception:
        # The raw document remains a useful server-rendered fallback when a
        # local browser is unavailable.
        document=page(url,timeout)
        return list(dict.fromkeys(re.findall(r'/careers/listing/([^"?#/]+)/([0-9]+)',document)))
def main()->int:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("url");p.add_argument("--max-jobs",type=int,default=50);p.add_argument("--timeout",type=int,default=30);p.add_argument("--skip-job-id",action="append",default=[]);p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    try:
        links=filtered_links(a.url,a.timeout)
        jobs=[];skip=set(a.skip_job_id)
        for slug,ident in links:
            if ident in skip:continue
            try:item=ld(page(f"https://stripe.com/careers/listing/{slug}/{ident}",a.timeout))
            except RuntimeError:continue
            desc=str(item.get("description")or"")
            jobs.append({"id":ident,"title":item.get("title", ""),"company":"Stripe","location":", ".join(x.get("address",{}).get("addressLocality","") for x in item.get("jobLocation",[]) if isinstance(x,dict)),"employment_type":item.get("employmentType", ""),"posted_date":item.get("datePosted", ""),"application_url":f"https://stripe.com/careers/listing/{slug}/{ident}","jobDescriptionHtml":desc,"jobDescriptionText":clean(desc)})
            if a.max_jobs and len(jobs)>=a.max_jobs:break
    except RuntimeError as e:print(f"Error: {e}",file=sys.stderr);return 1
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({"source":"Stripe server-rendered careers pages and JobPosting JSON-LD","input_url":a.url,"jobs":jobs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(f"Wrote {len(jobs)} Stripe jobs to {a.output}",file=sys.stderr);return 0
if __name__=="__main__":raise SystemExit(main())
