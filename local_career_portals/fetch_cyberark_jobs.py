#!/usr/bin/env python3
"""CyberArk/Idira-scoped roles on the successor's official career portal."""
import argparse
import importlib.util
from pathlib import Path
import re
import time
from urllib.parse import unquote, urljoin, urlsplit

from common import newest_first, plain_text, write_snapshot
from filters import engineering_title, in_india

SPEC = importlib.util.spec_from_file_location("palo_brand_transport", Path(__file__).resolve().parents[1] / "career portal scripts/fetch_palo_alto_jobs.py")
portal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(portal)
DEFAULT_URL = "https://jobs.paloaltonetworks.com/en/search-jobs/CyberArk/47263/1"
BRAND = re.compile(r"\b(?:cyberark|idira)\b", re.I)


def brand_evidence(posting):
    text = plain_text(posting.get("description") or "")
    match = BRAND.search(text)
    return text[max(0, match.start() - 100):match.end() + 160] if match else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.max_pages < 1 or args.timeout < 1 or args.delay < 0:
        parser.error("Invalid limits")
    jobs, seen, total_pages = [], set(), None
    for number in range(1, args.max_pages + 1):
        document = portal.read(portal.page_url(args.url, number), args.timeout)
        match = re.search(r'data-total-pages=["\'](\d+)', document)
        if total_pages is None:
            if not match:
                raise RuntimeError("Successor portal result count unavailable; refusing a false empty result")
            total_pages = int(match.group(1))
        links = re.findall(r'href=["\']([^"\']*/en/job/[^"\']+/\d+/\d+)["\']', document, re.I)
        for link in dict.fromkeys(links):
            url = urljoin(portal.BASE, link)
            parts = urlsplit(url).path.strip("/").split("/")
            ident = parts[-1]
            if ident in seen:
                continue
            seen.add(ident)
            city = unquote(parts[2]).replace("-", " ")
            title_hint = unquote(parts[3]).replace("-", " ")
            if not engineering_title({"title": title_hint}):
                continue
            # Inspect unknown/remote locations as well, rather than guessing
            # eligibility from them. Final country comes from JobPosting.
            if not in_india({"location": city}) and city.casefold() not in {"remote", "multiple locations", "india"}:
                continue
            time.sleep(args.delay)
            posting = portal.job_posting(portal.read(url, args.timeout), url)
            evidence = brand_evidence(posting)
            if not portal.is_india(posting) or not engineering_title(posting) or not evidence:
                continue
            places = posting.get("jobLocation") or []
            if isinstance(places, dict):
                places = [places]
            locations = [", ".join(str(value) for value in [(p.get("address") or {}).get("addressLocality"), (p.get("address") or {}).get("addressRegion")] if value) for p in places]
            description = posting.get("description") or ""
            jobs.append({"id": ident, "title": posting["title"], "company": (posting.get("hiringOrganization") or {}).get("name") or "Palo Alto Networks",
                         "requested_brand": "CyberArk / Idira", "brand_evidence": evidence, "country": "India", "location": " | ".join(locations),
                         "application_url": url, "posted_date": posting.get("datePosted"),
                         "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
        if number >= total_pages:
            break
        time.sleep(args.delay)
    jobs = newest_first(jobs)
    if args.max_jobs:
        jobs = jobs[:args.max_jobs]
    complete = (total_pages or 0) <= args.max_pages
    write_snapshot(args.output, jobs, input_url=args.url, official_original_careers_url="https://www.cyberark.com/careers/",
                   employer_transition="Original careers page routes to Palo Alto Networks / Idira",
                   scope="Successor portal CyberArk keyword search, explicit CyberArk/Idira mention, India, engineering titles; actual hiring employer retained",
                   complete=complete, stopped_reason=None if complete else "listing_page_limit",
                   sort="JobPosting datePosted descending before limit")
    print(f"CyberArk/Idira scope: wrote {len(jobs)} India engineering roles")


if __name__ == "__main__":
    main()
