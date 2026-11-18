#!/usr/bin/env python3
"""Browser-only career portals: headless first, one headed fallback."""
import argparse
import html
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlencode, urlsplit

from common import newest_first, plain_text, write_snapshot
from filters import engineering_title, in_india
from fetch_filtered_board_jobs import normalize as greenhouse_normalize
from fetch_ashby_jobs import normalize as ashby_normalize
from fetch_smartrecruiters_jobs import description_html
import fetch_workday_india_jobs as workday
import fetch_oracle_india_jobs as oracle
from fetch_eightfold_company_jobs import normalize as eightfold_normalize, iso

SOURCES = {
    "fortinet": ("Fortinet", "oracle", "https://edel.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_2001"),
    "arctic_wolf": ("Arctic Wolf", "workday", "https://arcticwolf.wd1.myworkdayjobs.com/External"),
    "rapid7": ("Rapid7", "rapid7", "https://careers.rapid7.com/jobs/search"),
    "sophos": ("Sophos", "ashby", "sophos"),
    "tenable": ("Tenable", "greenhouse", "tenableinc"),
    "qualys": ("Qualys", "workday", "https://qualys.wd5.myworkdayjobs.com/Careers"),
    "suse": ("SUSE", "workday", "https://suse.wd3.myworkdayjobs.com/Jobsatsuse"),
    "mirantis": ("Mirantis", "smartrecruiters", "Mirantis"),
    "canonical": ("Canonical", "greenhouse", "canonical"),
    "zapier": ("Zapier", "ashby", "zapier"),
    "agoda": ("Agoda", "greenhouse", "agoda"),
    "twilio": ("Twilio", "twilio", "https://jobs.twilio.com"),
    "grab": ("Grab", "smartrecruiters", "Grab"),
    "roku": ("Roku", "rapid7", "https://www.weareroku.com/jobs/search"),
    "wisdom_ai": ("WisdomAI", "ashby", "Wisdom-AI"),
    "arcana": ("Arcana Analytics", "greenhouse", "arcanaanalytics"),
    "spotnana": ("Spotnana", "gem", "spotnana"),
    "coupang": ("Coupang", "greenhouse_selective", "coupang"),
    "wayfair": ("Wayfair", "wayfair", "https://www.wayfair.com/careers/jobs"),
    "zepto": ("Zepto", "darwinbox", "https://zepto.darwinbox.in/ms/candidatev2/main/careers/allJobs"),
    "inmobi": ("InMobi", "greenhouse", "inmobi"),
    "deel": ("Deel", "enterprise_deel", "https://www.deel.com/careers/"),
    "expedia_group": ("Expedia Group", "workday", "https://expedia.wd108.myworkdayjobs.com/search"),
    "jpmorgan_chase": ("JPMorgan Chase", "enterprise_oracle", "https://jpmc.fa.oraclecloud.com|CX_1001"),
    "goldman_sachs": ("Goldman Sachs", "enterprise_goldman", "https://higher.gs.com/results"),
    "morgan_stanley": ("Morgan Stanley", "enterprise_pcsx", "https://morganstanley.eightfold.ai|morganstanley.com"),
    "american_express": ("American Express", "enterprise_oracle", "https://egug.fa.us2.oraclecloud.com|CX_1"),
    "navi": ("Navi", "enterprise_turbohire", "https://navi.turbohire.co/dashboardv2?orgId=3e818601-0baa-429c-b6f8-4b21903ae0e6&type=0"),
    "gojek": ("Gojek", "enterprise_lever", "GoToGroup"),
    "freshworks": ("Freshworks", "smartrecruiters", "Freshworks"),
    "amd": ("AMD", "enterprise_icims", "https://careers.amd.com/jobs?country=India&categories=Engineering"),
    "arm": ("Arm", "enterprise_talentbrew", "https://careers.arm.com/search-jobs"),
    "clari": ("Clari", "enterprise_clari", "salesloft"),
    "toast": ("Toast", "rapid7", "https://careers.toasttab.com/jobs/search?country_codes%5B%5D=IN"),
    "stockx": ("StockX", "greenhouse", "stockx"),
    "opendoor": ("Opendoor", "enterprise_cards", "https://www.opendoor.com/careers/open-positions"),
    "netapp": ("NetApp", "enterprise_talentbrew", "https://careers.netapp.com/search-jobs"),
    "forward_networks": ("Forward Networks", "greenhouse", "forwardnetworks"),
    "autodesk": ("Autodesk", "enterprise_pcsx", "https://jobs.autodesk.com|autodesk.com"),
    "dream11": ("Dream11", "enterprise_lever", "dreamsports"),
    "sharechat": ("ShareChat", "enterprise_sharechat", "https://sharechat.com/careers"),
    "exaforce": ("Exaforce", "enterprise_cards", "https://www.exaforce.com/careers"),
}


class Browser:
    def __init__(self, playwright, headed, timeout):
        self.browser = playwright.chromium.launch(channel="chrome", headless=not headed)
        self.page = self.browser.new_page()
        self.timeout = timeout
        self.page.set_default_timeout(timeout * 1000)

    def close(self):
        self.browser.close()

    def goto(self, url):
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout * 1000)
        if response is None or not response.ok:
            status = response.status if response else "unknown"
            retry = response.headers.get("retry-after", "unspecified") if response else "unspecified"
            raise RuntimeError(f"HTTP {status} at {url}; Retry-After={retry}")
        return response

    def json(self, url):
        return self.goto(url).json()


def department_excluded(names):
    return any(re.search(r"\b(?:sales|support|customer success|professional services|consulting)\b", name, re.I) for name in names)


def greenhouse_jobs(browser, company, board):
    data = browser.json(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true")
    if not isinstance(data.get("jobs"), list):
        raise RuntimeError("Greenhouse listing shape changed")
    jobs = []
    for item in data["jobs"]:
        departments = [d.get("name", "") for d in item.get("departments", [])]
        if not engineering_title(item) or department_excluded(departments):
            continue
        explicit = in_india(item)
        location = (item.get("location") or {}).get("name", "")
        worldwide = company == "Canonical" and bool(re.search(r"\bHome based\s*-\s*Worldwide\b", location, re.I))
        if not explicit and not worldwide:
            continue
        job = greenhouse_normalize(item, company)
        job["department"] = " | ".join(departments)
        job["source_departments"] = departments
        if worldwide and not explicit:
            job.update(country="India", source_location=location,
                       location_scope="Worldwide home-based hiring location includes India; not India-specific",
                       location_evidence=location)
        jobs.append(job)
    return jobs, {"global_results": len(data["jobs"]), "complete": True}


def greenhouse_selective_jobs(browser, company, board):
    base = f"https://boards-api.greenhouse.io/v1/boards/{board}"
    data = browser.json(base + "/jobs?content=false")
    if not isinstance(data.get("jobs"), list):
        raise RuntimeError("Greenhouse listing shape changed")
    jobs = []
    seen = set()
    for item in data["jobs"]:
        if item.get("id") in seen or not item.get("id"):
            raise RuntimeError("Greenhouse repeated/missing job ID")
        seen.add(item["id"])
        location = (item.get("location") or {}).get("name", "")
        ambiguous = not location or bool(re.search(r"multiple|various|several", location, re.I))
        if not engineering_title(item) or not (in_india(item) or ambiguous):
            continue
        detail = browser.json(base + f"/jobs/{item['id']}?questions=false")
        if detail.get("id") != item["id"]:
            raise RuntimeError("Greenhouse detail identity mismatch")
        departments = [d.get("name", "") for d in detail.get("departments", [])]
        if not in_india(detail) or department_excluded(departments):
            continue
        job = greenhouse_normalize(detail, company)
        job["department"] = " | ".join(departments)
        job["source_departments"] = departments
        jobs.append(job)
        time.sleep(0.3)
    return jobs, {"global_results": len(data["jobs"]), "complete": True,
                  "selection": "Complete lightweight listing scan; India or ambiguous-location technical candidates hydrated and rechecked"}


def ashby_jobs(browser, company, board):
    data = browser.json("https://api.ashbyhq.com/posting-api/job-board/" + board)
    if not isinstance(data.get("jobs"), list):
        raise RuntimeError("Ashby listing shape changed")
    selected = [j for j in data["jobs"] if not department_excluded([j.get("department") or "", j.get("team") or ""])]
    return ashby_normalize(selected, company), {"global_results": len(data["jobs"]), "complete": True}


def gem_jobs(browser, company, board):
    data = browser.json(f"https://api.gem.com/job_board/v0/{board}/job_posts/")
    if not isinstance(data, list):
        raise RuntimeError("Gem job-board response shape changed")
    jobs, seen = [], set()
    for item in data:
        if not item.get("id") or item["id"] in seen:
            raise RuntimeError("Gem repeated/missing job ID")
        seen.add(item["id"])
        departments = [d.get("name", "") for d in item.get("departments", [])]
        if not in_india(item) or not engineering_title(item) or department_excluded(departments):
            continue
        job = greenhouse_normalize({**item, "first_published": item.get("first_published_at")}, company)
        job["department"] = " | ".join(departments)
        job["source_departments"] = departments
        jobs.append(job)
    return jobs, {"global_results": len(data), "complete": True}


def unwrap_eightfold(payload):
    if payload.get("status") != 200 or not isinstance(payload.get("data"), dict):
        raise RuntimeError("Eightfold PCSx response shape changed")
    return payload["data"]


def twilio_jobs(browser, company, origin, domain="twilio.com"):
    jobs, seen, offset, total = [], set(), 0, 0
    for _ in range(100):
        data = unwrap_eightfold(browser.json(origin + "/api/pcsx/search?" + urlencode({
            "domain": domain, "query": "", "location": "India", "start": offset, "sort_by": "timestamp"})))
        if not isinstance(data.get("positions"), list) or "count" not in data:
            raise RuntimeError("Twilio listing response shape changed")
        total = int(data["count"])
        for item in data["positions"]:
            if not item.get("id") or item["id"] in seen:
                raise RuntimeError("Twilio repeated/missing job ID")
            seen.add(item["id"])
            if not in_india(item) or not engineering_title({"title": item.get("name")}) or department_excluded([item.get("department") or ""]):
                continue
            detail = unwrap_eightfold(browser.json(origin + "/api/pcsx/position_details?" + urlencode({
                "domain": domain, "position_id": item["id"], "hl": "en"})))
            if detail.get("id") != item["id"]:
                raise RuntimeError("Twilio detail identity mismatch")
            job = eightfold_normalize(item, detail, origin, company, "pcsx")
            if not in_india(job) or not engineering_title(job) or department_excluded([job.get("department") or ""]):
                continue
            dates = detail.get("efcustomTextPostDate") or []
            if isinstance(dates, str):
                dates = [dates]
            job["posted_date"] = next((v for v in dates if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)), job["posted_date"])
            job["source_created_timestamp"] = detail.get("creationTs")
            jobs.append(job)
            time.sleep(0.3)
        offset += len(data["positions"])
        if offset >= total:
            return jobs, {"total_india_search_results": total, "complete": True,
                          "publication_basis": "Explicit efcustomTextPostDate; postedTs when supplied; creationTs kept separate"}
        if not data["positions"]:
            raise RuntimeError("Twilio pagination ended before reported count")
    raise RuntimeError("Twilio page limit reached")


def wayfair_jobs(browser, company, url):
    endpoint = "https://www.wayfair.com/a/careers/careers/job_search_data"
    with browser.page.expect_response(lambda r: r.url == endpoint, timeout=browser.timeout * 1000) as pending:
        browser.goto(url)
    response = pending.value
    if not response.ok:
        raise RuntimeError(f"Wayfair native job data HTTP {response.status}")
    data = response.json()
    if not isinstance(data.get("jobListData"), list):
        raise RuntimeError("Wayfair native job data shape changed")
    engineering_ids = {v["teamId"] for v in data.get("validTeams", {}).get("filters", [])
                       if v.get("team") == "Engineering & Technology"}
    if not engineering_ids:
        raise RuntimeError("Wayfair Engineering & Technology mapping missing")
    jobs, seen = [], set()
    for item in data["jobListData"]:
        if not item.get("id") or item["id"] in seen:
            raise RuntimeError("Wayfair repeated/missing job ID")
        seen.add(item["id"])
        if item.get("isActive") is not True or item.get("isHidden") or item.get("isReferralOnly"):
            continue
        location = item.get("location") or {}
        if item.get("teamId") not in engineering_ids or not in_india({"location": location}) or not engineering_title(item):
            continue
        description = item.get("description") or ""
        if not plain_text(description) or not item.get("applyLink"):
            raise RuntimeError("Wayfair full description/application URL missing")
        jobs.append({"id": str(item["id"]), "title": item["title"], "company": company,
                     "department": (item.get("category") or {}).get("name"),
                     "location": location.get("name"), "country": location.get("country"),
                     "application_url": item["applyLink"], "posted_date": None,
                     "source_created_date": item.get("createdDate"), "updated_date": item.get("lastUpdatedDate"),
                     "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
    return jobs, {"global_results": len(data["jobListData"]), "complete": True,
                  "date_limitation": "Native feed supplies createdDate and lastUpdatedDate, not an explicit publication date"}


def darwinbox_jobs(browser, company, url):
    page = browser.page
    def matches(response):
        return "/ms/candidateapi/job/alljobs" in response.url
    with page.expect_response(matches, timeout=browser.timeout * 1000) as pending:
        browser.goto(url)
    jobs, seen, total = [], set(), 0
    for _ in range(100):
        response = pending.value
        if not response.ok:
            raise RuntimeError(f"Darwinbox native list HTTP {response.status}")
        data = response.json()
        if data.get("status") != "success" or not isinstance(data.get("data"), list) or "job_counts" not in data:
            raise RuntimeError("Darwinbox native list shape changed")
        total = max(total, int(data["job_counts"]))
        for item in data["data"]:
            if not item.get("id") or item["id"] in seen:
                raise RuntimeError("Darwinbox repeated/missing job ID")
            seen.add(item["id"])
            locations = item.get("officelocations_area") or item.get("tool_tip_locations") or []
            title = item.get("title") or item.get("designation_name")
            if not in_india({"country": item.get("country"), "locations": locations}) or not engineering_title({"title": title}):
                continue
            if department_excluded([item.get("department_name_only") or ""]):
                continue
            description = html.unescape(item.get("jd") or "")
            if not plain_text(description):
                raise RuntimeError("Darwinbox selected job lacks its full description")
            jobs.append({"id": item["id"], "title": title, "company": company,
                         "department": item.get("department_name_only"), "locations": locations,
                         "location": " | ".join(locations), "country": item.get("country"),
                         "application_url": url.rsplit('/', 1)[0] + f"/jobDetails/{item['id']}?from=all",
                         "posted_date": iso(item.get("posted_on")), "source_created_date": item.get("created_on"),
                         "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
        if len(seen) >= total:
            return jobs, {"global_results": total, "complete": True}
        if not data["data"]:
            raise RuntimeError("Darwinbox pagination ended before reported count")
        with page.expect_response(matches, timeout=browser.timeout * 1000) as pending:
            page.get_by_role("button", name=re.compile(r"^next(?: page)?$", re.I)).click()
    raise RuntimeError("Darwinbox page limit reached")


def smartrecruiters_jobs(browser, company, tenant):
    base = f"https://api.smartrecruiters.com/v1/companies/{tenant}/postings"
    summaries, seen, offset = [], set(), 0
    for _ in range(100):
        data = browser.json(base + "?" + urlencode({"country": "in", "limit": 100, "offset": offset}))
        if not isinstance(data.get("content"), list) or "totalFound" not in data:
            raise RuntimeError("SmartRecruiters listing shape changed")
        for item in data["content"]:
            if item["id"] in seen:
                raise RuntimeError("SmartRecruiters repeated a listing")
            seen.add(item["id"])
            if engineering_title({"title": item.get("name")}) and not department_excluded([(item.get("department") or {}).get("label", "")]):
                summaries.append(item)
        offset += len(data["content"])
        if offset >= data["totalFound"]:
            break
        if not data["content"]:
            raise RuntimeError("SmartRecruiters pagination incomplete")
    else:
        raise RuntimeError("SmartRecruiters page limit reached")
    jobs = []
    for item in summaries:
        detail = browser.json(base + "/" + item["id"])
        if (detail.get("company") or {}).get("identifier", "").casefold() != tenant.casefold():
            raise RuntimeError("SmartRecruiters employer mismatch")
        location = detail.get("location") or {}
        if location.get("country", "").lower() != "in":
            continue
        description = description_html(detail)
        jobs.append({"id": str(item["id"]), "title": detail["name"], "company": company,
                     "department": (detail.get("department") or {}).get("label"),
                     "country": "India", "location": location.get("fullLocation") or f"{location.get('city', '')}, India",
                     "posted_date": detail.get("releasedDate"), "application_url": detail.get("postingUrl") or item.get("ref"),
                     "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
        time.sleep(0.3)
    return jobs, {"total_india_results": offset, "complete": True}


def workday_jobs(browser, company, url):
    host, tenant, site, _ = workday.transport.site_config(url)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    landing = f"https://{host}/en-US/{site}"
    page = browser.page

    def listing(target, expected, next_page=False):
        print(f"{company}: waiting for native listing offset {expected['offset']}", flush=True)
        def matches(response):
            if response.url != base + "/jobs" or response.request.method != "POST":
                return False
            payload = response.request.post_data_json
            return payload.get("offset", 0) == expected["offset"] and payload.get("appliedFacets", {}) == expected["appliedFacets"]
        with page.expect_response(matches, timeout=browser.timeout * 1000) as pending:
            if next_page:
                page.get_by_role("button", name=re.compile(r"^next", re.I)).click()
            else:
                browser.goto(target)
        response = pending.value
        if not response.ok:
            raise RuntimeError(f"Workday native listing HTTP {response.status}; Retry-After={response.headers.get('retry-after', 'unspecified')}")
        return response.json()

    initial = listing(landing, {"offset": 0, "appliedFacets": {}})
    if not isinstance(initial.get("jobPostings"), list) or not isinstance(initial.get("facets"), list):
        raise RuntimeError("Workday discovery shape changed")
    facets = workday.native_facets(initial["facets"])
    if not facets:
        return [], {"global_results": initial["total"], "complete": True, "discovered_applied_facets": None}
    target = landing + "?" + urlencode(facets, doseq=True)
    summaries, seen = [], set()
    offset, total = 0, 0
    for number in range(100):
        data = listing(target, {"offset": offset, "appliedFacets": facets}, next_page=number > 0)
        if not isinstance(data.get("jobPostings"), list) or "total" not in data:
            raise RuntimeError("Workday listing shape changed")
        total = max(total, int(data["total"]))
        for item in data["jobPostings"]:
            if not item.get("externalPath") or item["externalPath"] in seen:
                raise RuntimeError("Workday repeated/missing job path")
            seen.add(item["externalPath"])
            if engineering_title(item):
                summaries.append(item)
        offset += len(data["jobPostings"])
        if offset >= total:
            break
        if not data["jobPostings"]:
            raise RuntimeError("Workday pagination incomplete")
    else:
        raise RuntimeError("Workday page limit reached")
    jobs = []
    for index, item in enumerate(summaries):
        if index % 10 == 0:
            print(f"{company}: full details {index}/{len(summaries)}", flush=True)
        endpoint = base + item["externalPath"]
        with page.expect_response(lambda r: r.url == endpoint and r.request.method == "GET", timeout=browser.timeout * 1000) as pending:
            browser.goto(landing + item["externalPath"])
        response = pending.value
        if not response.ok:
            raise RuntimeError(f"Workday detail HTTP {response.status}")
        detail = response.json().get("jobPostingInfo")
        if not detail:
            raise RuntimeError("Workday full detail missing")
        job = workday.normalize(item, detail, host, site, company)
        if job and engineering_title(job):
            jobs.append(job)
        time.sleep(0.3)
    return jobs, {"global_results": initial["total"], "total_filtered_results": total,
                  "discovered_applied_facets": facets, "complete": True}


def json_ld_jobs(page):
    results = []
    for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
        try:
            stack = [json.loads(raw)]
        except ValueError:
            continue
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                kind = value.get("@type")
                if kind == "JobPosting" or isinstance(kind, list) and "JobPosting" in kind:
                    results.append(value)
                else:
                    stack.extend(value.values())
            elif isinstance(value, list):
                stack.extend(value)
    return results


def rapid7_jobs(browser, company, url):
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    summaries, seen, visited = [], set(), set()
    page_fingerprints, scanned = set(), 0
    total = None
    while url:
        if url in visited:
            raise RuntimeError("Rapid7 pagination repeated")
        visited.add(url)
        browser.goto(url)
        if company == 'Toast':
            country = browser.page.locator('input[name="country_codes[]"][value="IN"]')
            if not country.count() or not country.is_checked():
                raise RuntimeError('Toast did not apply the native India country filter')
        rows = browser.page.locator('tr[data-job-url], article.job-search-results-card-col').evaluate_all('''els => els.map(e=>({
            url:e.dataset.jobUrl || e.querySelector('.job-search-results-card-title a').href,
            title:e.querySelector('.job-search-results-title, .job-search-results-card-title').innerText.trim(),
            location:e.querySelector('.job-search-results-location, .job-component-list-location').innerText.trim(),
            department:e.querySelector('.job-search-results-department, [class*="job-search-results-string_field"], .job-component-list-department')?.innerText.trim() || ''}))''')
        count_text = browser.page.locator('.table-counts').first.inner_text()
        count = (re.search(r"of\s+(\d+)\s+in total", count_text)
                 or re.search(r"Displaying\s+all\s+(\d+)\s+(?:entries|jobs)", count_text, re.I))
        if not count:
            raise RuntimeError("Rapid7 listing count unavailable")
        total = int(count.group(1))
        fingerprint = tuple(row['url'] for row in rows)
        if fingerprint in page_fingerprints:
            raise RuntimeError(f"{company} returned a repeated listing page")
        page_fingerprints.add(fingerprint)
        scanned += len(rows)
        for row in rows:
            if row["url"] in seen:
                continue
            seen.add(row["url"])
            if in_india(row) and engineering_title(row) and not department_excluded([row["department"]]):
                summaries.append(row)
        next_link = browser.page.locator('li.next:not(.disabled) a[rel="next"]').first
        url = next_link.get_attribute('href') if next_link.count() else None
        if url and url.startswith('/'):
            url = origin + url
        if len(visited) > 100:
            raise RuntimeError("Rapid7 page limit reached")
    if scanned != total:
        raise RuntimeError(f"{company} listing count mismatch: {scanned} rows, {len(seen)} unique jobs, {total} advertised, {len(visited)} pages")
    jobs = []
    for row in summaries:
        browser.goto(row["url"])
        details = json_ld_jobs(browser.page)
        if len(details) != 1:
            raise RuntimeError("Rapid7 JobPosting schema missing or ambiguous")
        detail = details[0]
        description = detail.get("description") or ""
        if not plain_text(description):
            raise RuntimeError("Rapid7 full description missing")
        locations = detail.get("jobLocation") or []
        if not isinstance(locations, list):
            locations = [locations]
        if not in_india({"jobLocation": locations}):
            continue
        identifier = detail.get("identifier") or row["url"].rsplit('/', 1)[-1]
        if isinstance(identifier, dict):
            identifier = identifier.get("value")
        jobs.append({"id": str(identifier), "title": detail.get("title") or row["title"],
                     "company": company, "department": row["department"], "location": row["location"],
                     "country": "India", "application_url": row["url"], "posted_date": detail.get("datePosted"),
                     "jobDescriptionHtml": description, "jobDescriptionText": plain_text(description)})
    return jobs, {"global_results": total, "duplicate_listings_removed": scanned-len(seen), "complete": True}


def collect(browser, slug):
    company, kind, source = SOURCES[slug]
    if kind.startswith("enterprise_"):
        from fetch_enterprise_portals import collect_enterprise
        return collect_enterprise(browser, company, kind, source)
    if kind == "oracle":
        jobs, total = oracle.collect(source, company, site="CX_2001", timeout=browser.timeout,
                                     title_facet="RD", reader=lambda url, timeout: browser.goto(url).text())
        return jobs, {"global_rd_results": total, "complete": True, "native_function": "Research/Development (RD)"}
    return {"workday": workday_jobs, "greenhouse": greenhouse_jobs,
            "greenhouse_selective": greenhouse_selective_jobs,
            "gem": gem_jobs, "twilio": twilio_jobs, "wayfair": wayfair_jobs,
            "darwinbox": darwinbox_jobs,
            "ashby": ashby_jobs, "smartrecruiters": smartrecruiters_jobs,
            "rapid7": rapid7_jobs}[kind](browser, company, source)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Official source URL recorded in the snapshot")
    parser.add_argument("--source", choices=SOURCES, required=True)
    parser.add_argument("--max-jobs", type=int, default=50)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--headed", action="store_true", help="Skip headless and run the visible browser")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.max_jobs < 0 or args.timeout < 1:
        parser.error("Invalid limits")
    from playwright.sync_api import sync_playwright
    errors = []
    with sync_playwright() as playwright:
        for headed in ([True] if args.headed else [False, True]):
            browser = None
            try:
                print(f"{args.source}: starting {'headed' if headed else 'headless'} Playwright", flush=True)
                browser = Browser(playwright, headed, args.timeout)
                browser.max_jobs = args.max_jobs
                jobs, metadata = collect(browser, args.source)
                jobs = newest_first(jobs)
                if args.max_jobs:
                    jobs = jobs[:args.max_jobs]
                write_snapshot(args.output, jobs, **metadata, input_url=args.url,
                    source=SOURCES[args.source][2], browser_mode="headed" if headed else "headless",
                    previous_attempt_errors=errors, filters="Engineering roles eligible in India; sales/support excluded; conservative title guard",
                    ordering="Available publication dates descending before cap; unknown dates preserved")
                print(f"{args.source}: saved {len(jobs)} jobs", flush=True)
                return 0
            except Exception as error:
                errors.append({"mode": "headed" if headed else "headless", "error": f"{type(error).__name__}: {error}"})
                print(f"{args.source}: {errors[-1]['error']}", file=sys.stderr, flush=True)
                # A server-specified cooldown is never shortened for a fallback.
                if re.search(r"Retry-After=(?!unspecified)[^\s;]+", str(error)):
                    break
            finally:
                if browser:
                    browser.close()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
