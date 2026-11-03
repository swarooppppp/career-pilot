#!/usr/bin/env python3
"""Apply each portal's Engineering category and India location semantics."""
import argparse
import html
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from common import newest_first, plain_text, write_snapshot
from filters import in_india
import portal_http

BOARDS = {"abnormal_ai": "abnormalsecurity", "cloudflare": "cloudflare", "mongodb": "mongodb"}
COMPANIES = {"abnormal_ai": "Abnormal AI", "cloudflare": "Cloudflare", "mongodb": "MongoDB"}


def read(url, timeout):
    return portal_http.read(url, timeout)


def abnormal_categories(document):
    chunks = []
    for match in re.finditer(r'self\.__next_f\.push\((.*?)\)</script>', document, re.S):
        try:
            item = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if len(item) > 1 and isinstance(item[1], str):
            chunks.append(item[1])
    payload = "".join(chunks)
    match = re.search(r'"jobs":\s*\[', payload)
    if not match:
        raise RuntimeError("Abnormal portal category data unavailable; refusing to guess departments")
    jobs, _ = json.JSONDecoder().raw_decode(payload[match.end() - 1:])
    return {str(j["id"]): j for j in jobs}


def metadata(job, name):
    return next((item.get("value") for item in job.get("metadata", []) if item.get("name") == name), None)


def cloudflare_matches(job, location):
    categories = metadata(job, "Career Site Department") or []
    locations = metadata(job, "Job Posting Location") or []
    if isinstance(categories, str):
        categories = [categories]
    if isinstance(locations, str):
        locations = [locations]
    return "Engineering" in categories and any(location.casefold() == value.casefold() for value in locations)


def mongodb_membership(url, timeout):
    """Use the actual UI taxonomy, which differs from Greenhouse departments."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            engineering = page.locator('label[for="department-3"]')
            engineering.wait_for(timeout=timeout * 1000)
            if engineering.inner_text().strip() != "Engineering":
                raise RuntimeError("MongoDB department mapping changed")
            # SSR checkboxes can toggle before event handlers are attached.
            # Wait for hydration and verify the result set actually changes.
            page.wait_for_function("() => Object.keys(document.querySelector('input#department-3') || {}).some(k => k.startsWith('__react') || k === 'l' || k === '__l')", timeout=timeout * 1000)
            initial = re.search(r"Displaying\s*(\d+)\s*positions", page.locator("body").inner_text())
            if not initial:
                raise RuntimeError("MongoDB initial result count unavailable")
            engineering.click()
            page.wait_for_function("previous => { const m = document.body.innerText.match(/Displaying\\s*(\\d+)\\s*positions/); return m && m[1] !== previous; }", arg=initial.group(1), timeout=timeout * 1000)
            # The portal's India checkbox is an exact location, not a country
            # umbrella. Include its Indian city facets as an OR selection.
            labels = page.locator('label[for^="location-"]')
            selected = []
            for label in labels.all():
                if in_india({"location": label.inner_text()}):
                    selected.append(label.get_attribute("for"))
            if not selected:
                raise RuntimeError("MongoDB has no recognized India location facets")
            for ident in selected:
                page.locator('label[for="' + ident + '"]').click()
            text = page.locator("body").inner_text()
            match = re.search(r"Displaying\s*(\d+)\s*positions", text)
            if not match:
                raise RuntimeError("MongoDB filtered result count unavailable")
            total = int(match.group(1))
            ids = set()
            for _ in range((total + 9) // 10):
                urls = page.locator('a[href*="gh_jid="]').evaluate_all("els => els.map(e => e.href)")
                before = len(ids)
                ids.update(parse_qs(urlparse(link).query)["gh_jid"][0] for link in urls)
                if len(ids) >= total:
                    break
                if len(ids) == before:
                    raise RuntimeError("MongoDB pagination did not advance")
                page.locator('svg[aria-label="right arrow"]').click()
                page.wait_for_function("previous => { const el = document.querySelector('a[href*=\"gh_jid=\"]'); return el && el.href !== previous; }", arg=urls[0], timeout=timeout * 1000)
            if len(ids) != total:
                raise RuntimeError("MongoDB filtered result collection was incomplete")
            return ids
        finally:
            browser.close()


def normalize(job, company, location=None):
    description = html.unescape(job.get("content") or "")
    if not all(job.get(key) for key in ("id", "title", "absolute_url")) or not description:
        raise RuntimeError("Selected board job is missing required fields")
    return {"id": str(job["id"]), "title": job["title"], "company": company,
            "department": "Engineering", "location": location or (job.get("location") or {}).get("name", ""),
            "offices": job.get("offices", []), "application_url": job["absolute_url"],
            "posted_date": job.get("first_published"), "updated_date": job.get("updated_at"),
            "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--source", choices=BOARDS, required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("Invalid job limit or timeout")
    board_url = f"https://boards-api.greenhouse.io/v1/boards/{BOARDS[args.source]}/jobs?content=true"
    payload = json.loads(read(board_url, args.timeout))
    if not isinstance(payload.get("jobs"), list):
        raise RuntimeError("Board response is missing jobs")
    jobs = payload["jobs"]
    if args.source == "abnormal_ai":
        categories = abnormal_categories(read(args.url, args.timeout))
        query = parse_qs(urlparse(args.url).query)
        location = query.get("location", ["Hybrid - Bangalore, India"])[0]
        ids = {ident for ident, job in categories.items() if job.get("category") == "Engineering" and job.get("location") == location}
        jobs = [normalize(job, COMPANIES[args.source]) for job in jobs if str(job["id"]) in ids]
        if len(jobs) != len(ids):
            raise RuntimeError("Abnormal category data and board listings disagree; retry later")
    elif args.source == "cloudflare":
        location = parse_qs(urlparse(args.url).query).get("location", ["Bengaluru, India"])[0]
        jobs = [normalize(job, COMPANIES[args.source], location) for job in jobs if cloudflare_matches(job, location)]
    else:
        ids = mongodb_membership(args.url, args.timeout)
        jobs = [normalize(job, COMPANIES[args.source]) for job in jobs if str(job["id"]) in ids]
        if len(jobs) != len(ids):
            raise RuntimeError("MongoDB UI and board listings disagree; retry later")
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    write_snapshot(args.output, jobs, input_url=args.url, source=board_url, filters="Portal Engineering category and India locations", sort="first publication descending; update date fallback")
    print(f"{COMPANIES[args.source]}: wrote {len(jobs)} filtered jobs")


if __name__ == "__main__":
    main()
