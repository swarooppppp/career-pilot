#!/usr/bin/env python3
"""Fetch Engineering roles from Zeta's public Lever postings feed."""
from __future__ import annotations
import argparse, html, json, sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.lever.co/v0/postings/zeta?group=team&mode=json"
class TextParser(HTMLParser):
    def __init__(self) -> None: super().__init__(convert_charrefs=True); self.parts: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"br", "p", "div", "li", "h1", "h2", "h3"}: self.parts.append("\n")
        if tag == "li": self.parts.append("- ")
    def handle_data(self, data: str) -> None: self.parts.append(data)
    def text(self) -> str: return "\n".join(line for line in (" ".join(line.split()) for line in "".join(self.parts).splitlines()) if line)
def html_to_text(value: str) -> str:
    parser=TextParser(); parser.feed(value); parser.close(); return html.unescape(parser.text())
def fetch_jobs(timeout: int) -> list[dict[str, Any]]:
    try:
        with urlopen(Request(API_URL, headers={"Accept":"application/json","User-Agent":"Mozilla/5.0 (compatible; CareerPilotZetaFetcher/1.0)"}), timeout=timeout) as response: groups=json.loads(response.read().decode(response.headers.get_content_charset() or "utf-8"))
    except HTTPError as error: raise RuntimeError(f"Zeta Lever feed returned HTTP {error.code}") from error
    except URLError as error: raise RuntimeError(f"Could not reach Zeta Lever feed: {error.reason}") from error
    if not isinstance(groups,list): raise RuntimeError("Zeta Lever feed did not contain team groups")
    jobs=[]
    for group in groups:
        if not isinstance(group,dict) or str(group.get("title") or "").casefold() != "engineering": continue
        for posting in group.get("postings",[]):
            if not isinstance(posting,dict): continue
            description_html="\n".join(str(value) for value in [posting.get("description") or "", *(item.get("content","") for item in posting.get("lists",[]) if isinstance(item,dict))] if value)
            job_id,title=str(posting.get("id") or "").strip(),str(posting.get("text") or "").strip()
            if not job_id or not title or not description_html: continue
            categories=posting.get("categories") if isinstance(posting.get("categories"),dict) else {}
            jobs.append({"id":job_id,"title":title,"company":"Zeta","location":categories.get("location") or "","application_url":posting.get("hostedUrl") or posting.get("applyUrl") or "","jobDescriptionHtml":description_html,"jobDescriptionText":html_to_text(description_html)})
    return jobs
def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--max-jobs",type=int,default=50); parser.add_argument("--timeout",type=int,default=30); parser.add_argument("--output",type=Path,default=Path("zeta_jobs.json")); args=parser.parse_args()
    try: jobs=fetch_jobs(args.timeout); jobs=jobs[:args.max_jobs] if args.max_jobs else jobs
    except RuntimeError as error: print(f"Error: {error}",file=sys.stderr); return 1
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps({"source":"Zeta public Lever feed","team_filter":"Engineering","jobs_fetched":len(jobs),"jobs":jobs},ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(f"Wrote {len(jobs)} Zeta Engineering jobs to {args.output}",file=sys.stderr); return 0
if __name__ == "__main__": raise SystemExit(main())
