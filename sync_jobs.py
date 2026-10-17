#!/usr/bin/env python3
"""Fetch and import job sources configured in .env."""

from __future__ import annotations

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from app.logging_utils import configure_logging
from app.services.job_store import existing_external_job_ids


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SourceSpec:
    name: str
    output: Path
    fetch_command: list[str]


def run_command(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def add_existing_job_ids(command: list[str], source: str) -> list[str]:
    """Pass imported portal IDs to adapters before they hydrate detail pages."""
    for job_id in sorted(existing_external_job_ids(source)):
        command.extend(["--skip-job-id", job_id])
    return command


def configured_sources() -> list[SourceSpec]:
    load_dotenv(ROOT / ".env")
    google_url = os.getenv("GOOGLE_CAREERS_URL", "").strip()
    sources: list[SourceSpec] = []
    target_url = os.getenv("TARGET_JOBS_URL", "").strip()
    if os.getenv("FETCH_TARGET", "false").lower() == "true" and target_url:
        output = ROOT / "data" / "target_jobs.json"
        command = [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_target_jobs.py"), target_url,
            "--max-jobs", os.getenv("TARGET_MAX_JOBS", "50"),
            "--timeout", os.getenv("TARGET_TIMEOUT", "30"), "--output", str(output),
        ]
        sources.append(SourceSpec("target", output, add_existing_job_ids(command, "target")))
    mastercard_url = os.getenv("MASTERCARD_JOBS_URL", "").strip()
    if os.getenv("FETCH_MASTERCARD", "false").lower() == "true" and mastercard_url:
        output = ROOT / "data" / "mastercard_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_mastercard_jobs.py"), mastercard_url,
                   "--max-jobs", os.getenv("MASTERCARD_MAX_JOBS", "50"),
                   "--timeout", os.getenv("MASTERCARD_TIMEOUT", "30"),
                   "--delay", os.getenv("MASTERCARD_DELAY", "0.5"), "--output", str(output)]
        sources.append(SourceSpec("mastercard", output, add_existing_job_ids(command, "mastercard")))
    american_express_url = os.getenv("AMERICAN_EXPRESS_JOBS_URL", "").strip()
    if os.getenv("FETCH_AMERICAN_EXPRESS", "false").lower() == "true" and american_express_url:
        output = ROOT / "data" / "american_express_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_american_express_jobs.py"), american_express_url,
                   "--max-jobs", os.getenv("AMERICAN_EXPRESS_MAX_JOBS", "50"),
                   "--timeout", os.getenv("AMERICAN_EXPRESS_TIMEOUT", "30"), "--output", str(output)]
        sources.append(SourceSpec("american_express", output, add_existing_job_ids(command, "american_express")))
    palo_alto_url = os.getenv("PALO_ALTO_JOBS_URL", "").strip()
    if os.getenv("FETCH_PALO_ALTO", "false").lower() == "true" and palo_alto_url:
        output = ROOT / "data" / "palo_alto_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_palo_alto_jobs.py"), palo_alto_url,
                   "--max-pages", os.getenv("PALO_ALTO_MAX_PAGES", "10"),
                   "--max-jobs", os.getenv("PALO_ALTO_MAX_JOBS", "50"),
                   "--timeout", os.getenv("PALO_ALTO_TIMEOUT", "30"), "--output", str(output)]
        sources.append(SourceSpec("palo_alto", output, add_existing_job_ids(command, "palo_alto")))
    if os.getenv("FETCH_POSTMAN", "false").lower() == "true":
        output = ROOT / "data" / "postman_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_postman_jobs.py"),
                   "--max-jobs", os.getenv("POSTMAN_MAX_JOBS", "50"),
                   "--timeout", os.getenv("POSTMAN_TIMEOUT", "30"), "--output", str(output)]
        for location in os.getenv("POSTMAN_LOCATIONS", "Bangalore,Hyderabad").split(","):
            command.extend(["--location", location.strip()])
        sources.append(SourceSpec("postman", output, add_existing_job_ids(command, "postman")))
    goldman_url = os.getenv("GOLDMAN_SACHS_JOBS_URL", "").strip()
    if os.getenv("FETCH_GOLDMAN_SACHS", "false").lower() == "true" and goldman_url:
        output = ROOT / "data" / "goldman_sachs_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_goldman_sachs_jobs.py"), goldman_url,
                   "--max-jobs", os.getenv("GOLDMAN_SACHS_MAX_JOBS", "50"),
                   "--timeout", os.getenv("GOLDMAN_SACHS_TIMEOUT", "30"), "--output", str(output)]
        sources.append(SourceSpec("goldman_sachs", output, add_existing_job_ids(command, "goldman_sachs")))
    if os.getenv("FETCH_GOOGLE", "false").lower() == "true" and google_url:
        output = ROOT / "data" / "google_jobs.json"
        sources.append(SourceSpec("google", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_google_jobs.py"), google_url,
            "--max-pages", os.getenv("GOOGLE_MAX_PAGES", "1"), "--output", str(output),
            "--max-jobs", os.getenv("GOOGLE_MAX_JOBS", "50"),
        ]))
    amazon_url = os.getenv("AMAZON_JOBS_URL", "").strip()
    if os.getenv("FETCH_AMAZON", "false").lower() == "true" and amazon_url:
        output = ROOT / "data" / "amazon_jobs.json"
        sources.append(SourceSpec("amazon", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_amazon_jobs.py"), amazon_url,
            "--max-pages", os.getenv("AMAZON_MAX_PAGES", "10"),
            "--result-limit", os.getenv("AMAZON_RESULT_LIMIT", "10"),
            "--max-jobs", os.getenv("AMAZON_MAX_JOBS", "100"),
            "--timeout", os.getenv("AMAZON_TIMEOUT", "30"),
            "--output", str(output),
        ]))
    salesforce_url = os.getenv("SALESFORCE_JOBS_URL", "").strip()
    if os.getenv("FETCH_SALESFORCE", "false").lower() == "true" and salesforce_url:
        output = ROOT / "data" / "salesforce_jobs.json"
        sources.append(SourceSpec("salesforce", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_salesforce_jobs.py"), salesforce_url,
            "--max-pages", os.getenv("SALESFORCE_MAX_PAGES", "10"),
            "--max-jobs", os.getenv("SALESFORCE_MAX_JOBS", "50"),
            "--timeout", os.getenv("SALESFORCE_TIMEOUT", "60"),
            "--output", str(output),
        ]))
    intuit_url = os.getenv("INTUIT_JOBS_URL", "").strip()
    if os.getenv("FETCH_INTUIT", "false").lower() == "true" and intuit_url:
        output = ROOT / "data" / "intuit_jobs.json"
        sources.append(SourceSpec("intuit", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_intuit_jobs.py"), intuit_url,
            "--max-pages", os.getenv("INTUIT_MAX_PAGES", "10"),
            "--max-jobs", os.getenv("INTUIT_MAX_JOBS", "50"),
            "--country", os.getenv("INTUIT_COUNTRY", "India"),
            "--timeout", os.getenv("INTUIT_TIMEOUT", "30"),
            "--output", str(output),
        ]))
    atlassian_url = os.getenv("ATLASSIAN_JOBS_URL", "").strip()
    if os.getenv("FETCH_ATLASSIAN", "false").lower() == "true" and atlassian_url:
        output = ROOT / "data" / "atlassian_jobs.json"
        sources.append(SourceSpec("atlassian", output, add_existing_job_ids([
            sys.executable, str(ROOT / "career portal scripts" / "fetch_atlassian_jobs.py"), atlassian_url,
            "--max-jobs", os.getenv("ATLASSIAN_MAX_JOBS", "50"),
            "--timeout", os.getenv("ATLASSIAN_TIMEOUT", "60"),
            "--delay", os.getenv("ATLASSIAN_DELAY", "0.5"),
            "--output", str(output),
        ], "atlassian")))
    apple_url = os.getenv("APPLE_JOBS_URL", "").strip()
    if os.getenv("FETCH_APPLE", "false").lower() == "true" and apple_url:
        output = ROOT / "data" / "apple_jobs.json"
        sources.append(SourceSpec("apple", output, add_existing_job_ids([
            sys.executable, str(ROOT / "career portal scripts" / "fetch_apple_jobs.py"), apple_url,
            "--max-pages", os.getenv("APPLE_MAX_PAGES", "10"),
            "--max-jobs", os.getenv("APPLE_MAX_JOBS", "50"),
            "--timeout", os.getenv("APPLE_TIMEOUT", "30"),
            "--output", str(output),
        ], "apple")))
    meta_url = os.getenv("META_JOBS_URL", "").strip()
    if os.getenv("FETCH_META", "false").lower() == "true" and meta_url:
        output = ROOT / "data" / "meta_jobs.json"
        sources.append(SourceSpec("meta", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_meta_jobs.py"), meta_url,
            "--max-pages", os.getenv("META_MAX_PAGES", "10"),
            "--max-jobs", os.getenv("META_MAX_JOBS", "50"),
            "--output", str(output),
        ]))
    databricks_url = os.getenv("DATABRICKS_JOBS_URL", "").strip()
    if os.getenv("FETCH_DATABRICKS", "false").lower() == "true" and databricks_url:
        output = ROOT / "data" / "databricks_jobs.json"
        sources.append(SourceSpec("databricks", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_databricks_jobs.py"), databricks_url,
            "--max-jobs", os.getenv("DATABRICKS_MAX_JOBS", "50"),
            "--timeout", os.getenv("DATABRICKS_TIMEOUT", "60"), "--output", str(output),
        ]))
    uber_url = os.getenv("UBER_JOBS_URL", "").strip()
    if os.getenv("FETCH_UBER", "false").lower() == "true" and uber_url:
        output = ROOT / "data" / "uber_jobs.json"
        uber_command = [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_uber_jobs.py"), uber_url,
            "--max-pages", os.getenv("UBER_MAX_PAGES", "10"),
            "--max-jobs", os.getenv("UBER_MAX_JOBS", "50"),
            "--timeout", os.getenv("UBER_TIMEOUT", "30"), "--output", str(output),
        ]
        # Headed Chromium is the pragmatic local default for Uber because its
        # Cloudflare challenge frequently blocks headless automation. Set this
        # false in a display-less cloud worker.
        if os.getenv("UBER_HEADED", "true").lower() == "true":
            uber_command.append("--headed")
        sources.append(SourceSpec("uber", output, uber_command))
    if os.getenv("FETCH_MICROSOFT", "false").lower() == "true":
        output = ROOT / "data" / "microsoft_jobs.json"
        microsoft_command = [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_microsoft_jobs.py"),
            "--query", os.getenv("MICROSOFT_QUERY", "Software Engineer"),
            "--location", os.getenv("MICROSOFT_LOCATION", "India"),
            "--sort-by", os.getenv("MICROSOFT_SORT_BY", "timestamp"),
            "--seniority", os.getenv("MICROSOFT_SENIORITY", "Entry,Senior,Mid-Level"),
            "--role-type", os.getenv("MICROSOFT_ROLE_TYPE", "individual contributor"),
            "--employment-type", os.getenv("MICROSOFT_EMPLOYMENT_TYPE", "full-time"),
            "--max-pages", os.getenv("MICROSOFT_MAX_PAGES", "1"),
            "--max-jobs", os.getenv("MICROSOFT_MAX_JOBS", "50"),
            "--delay", os.getenv("MICROSOFT_DELAY", "1"),
            "--max-retries", os.getenv("MICROSOFT_MAX_RETRIES", "4"),
            "--backoff-seconds", os.getenv("MICROSOFT_BACKOFF_SECONDS", "2"),
            "--output", str(output),
        ]
        for job_id in sorted(existing_external_job_ids("microsoft")):
            microsoft_command.extend(["--skip-job-id", job_id])
        sources.append(SourceSpec("microsoft", output, microsoft_command))
    adobe_url = os.getenv("ADOBE_JOBS_URL", "").strip()
    if os.getenv("FETCH_ADOBE", "false").lower() == "true" and adobe_url:
        output = ROOT / "data" / "adobe_jobs.json"
        sources.append(SourceSpec("adobe", output, add_existing_job_ids([
            sys.executable, str(ROOT / "career portal scripts" / "fetch_adobe_jobs.py"), adobe_url,
            "--max-jobs", os.getenv("ADOBE_MAX_JOBS", "50"), "--timeout", os.getenv("ADOBE_TIMEOUT", "30"),
            "--delay", os.getenv("ADOBE_DELAY", "0.5"), "--output", str(output),
        ], "adobe")))
    rippling_url = os.getenv("RIPPLING_JOBS_URL", "").strip()
    if os.getenv("FETCH_RIPPLING", "false").lower() == "true" and rippling_url:
        output = ROOT / "data" / "rippling_jobs.json"
        sources.append(SourceSpec("rippling", output, add_existing_job_ids([
            sys.executable, str(ROOT / "career portal scripts" / "fetch_rippling_jobs.py"), rippling_url,
            "--max-jobs", os.getenv("RIPPLING_MAX_JOBS", "50"), "--timeout", os.getenv("RIPPLING_TIMEOUT", "30"),
            "--delay", os.getenv("RIPPLING_DELAY", "0.5"), "--output", str(output),
        ], "rippling")))
    capital_one_url = os.getenv("CAPITAL_ONE_JOBS_URL", "").strip()
    if os.getenv("FETCH_CAPITAL_ONE", "false").lower() == "true" and capital_one_url:
        output = ROOT / "data" / "capital_one_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_capital_one_jobs.py"), capital_one_url, "--max-jobs", os.getenv("CAPITAL_ONE_MAX_JOBS", "50"), "--timeout", os.getenv("CAPITAL_ONE_TIMEOUT", "30"), "--delay", os.getenv("CAPITAL_ONE_DELAY", "0.5"), "--output", str(output)]
        if os.getenv("CAPITAL_ONE_BENGALURU", "false").lower() == "true": command.append("--bengaluru")
        sources.append(SourceSpec("capital_one", output, add_existing_job_ids(command, "capital_one")))
    if os.getenv("FETCH_COHESITY", "false").lower() == "true":
        output = ROOT / "data" / "cohesity_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_cohesity_jobs.py"), "--max-jobs", os.getenv("COHESITY_MAX_JOBS", "50"), "--timeout", os.getenv("COHESITY_TIMEOUT", "30"), "--delay", os.getenv("COHESITY_DELAY", "0.5"), "--output", str(output)]
        sources.append(SourceSpec("cohesity", output, add_existing_job_ids(command, "cohesity")))
    if os.getenv("FETCH_ZETA", "false").lower() == "true":
        output = ROOT / "data" / "zeta_jobs.json"
        sources.append(SourceSpec("zeta", output, [sys.executable, str(ROOT / "career portal scripts" / "fetch_zeta_jobs.py"), "--max-jobs", os.getenv("ZETA_MAX_JOBS", "50"), "--timeout", os.getenv("ZETA_TIMEOUT", "30"), "--output", str(output)]))
    if os.getenv("FETCH_EIGHTFOLD", "false").lower() == "true":
        output = ROOT / "data" / "eightfold_jobs.json"
        command=[sys.executable,str(ROOT / "career portal scripts" / "fetch_eightfold_jobs.py"),"--domain",os.getenv("EIGHTFOLD_DOMAIN","volkscience.com"),"--location",os.getenv("EIGHTFOLD_LOCATION","Bengaluru, KA, India"),"--seniority",os.getenv("EIGHTFOLD_SENIORITY","1,2"),"--max-pages",os.getenv("EIGHTFOLD_MAX_PAGES","5"),"--max-jobs",os.getenv("EIGHTFOLD_MAX_JOBS","50"),"--timeout",os.getenv("EIGHTFOLD_TIMEOUT","30"),"--output",str(output)]
        sources.append(SourceSpec("eightfold",output,add_existing_job_ids(command,"eightfold")))
    # Public board APIs shared by several company career sites.  The adapter
    # filters the listing response before considering any record for import.
    for source_name, prefix, board, company, department, location in (
        ("harness", "HARNESS", "harnessinc", "Harness", "Engineering", ""),
        ("glean", "GLEAN", "gleanwork", "Glean", "Engineering", "Bangalore"),
    ):
        if os.getenv(f"FETCH_{prefix}", "false").lower() != "true":
            continue
        output = ROOT / "data" / f"{source_name}_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_greenhouse_jobs.py"),
                   "--board", board, "--company", company, "--department", os.getenv(f"{prefix}_DEPARTMENT", department),
                   "--location", os.getenv(f"{prefix}_LOCATION", location), "--query", os.getenv(f"{prefix}_QUERY", ""),
                   "--max-jobs", os.getenv(f"{prefix}_MAX_JOBS", "50"), "--timeout", os.getenv(f"{prefix}_TIMEOUT", "30"), "--output", str(output)]
        sources.append(SourceSpec(source_name, output, add_existing_job_ids(command, source_name)))
    if os.getenv("FETCH_MEESHO", "false").lower() == "true":
        output = ROOT / "data" / "meesho_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_lever_jobs.py"), "--site", "meesho", "--company", "Meesho",
                   "--team", os.getenv("MEESHO_DEPARTMENT", "Engineering"), "--location", os.getenv("MEESHO_LOCATION", ""),
                   "--query", os.getenv("MEESHO_QUERY", ""), "--max-jobs", os.getenv("MEESHO_MAX_JOBS", "50"),
                   "--timeout", os.getenv("MEESHO_TIMEOUT", "30"), "--output", str(output)]
        sources.append(SourceSpec("meesho", output, add_existing_job_ids(command, "meesho")))
    stripe_url = os.getenv("STRIPE_JOBS_URL", "").strip()
    if os.getenv("FETCH_STRIPE", "false").lower() == "true" and stripe_url:
        output = ROOT / "data" / "stripe_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_stripe_jobs.py"), stripe_url,
                   "--max-jobs", os.getenv("STRIPE_MAX_JOBS", "50"), "--timeout", os.getenv("STRIPE_TIMEOUT", "30"), "--output", str(output)]
        sources.append(SourceSpec("stripe", output, add_existing_job_ids(command, "stripe")))
    for source, prefix, kind, company, default_url, department in (("slice", "SLICE", "kula", "slice", "https://careers.kula.ai/slice?jobs=true", "Technology"), ("airbnb", "AIRBNB", "airbnb", "Airbnb", "https://careers.airbnb.com/positions/?_departments=engineering&_paged=1", "Engineering")):
        if os.getenv(f"FETCH_{prefix}", "false").lower() != "true": continue
        output=ROOT/"data"/f"{source}_jobs.json"
        command=[sys.executable,str(ROOT/"career portal scripts"/"fetch_server_rendered_jobs.py"),os.getenv(f"{prefix}_JOBS_URL",default_url),"--company",company,"--kind",kind,"--department",os.getenv(f"{prefix}_DEPARTMENT",department),"--max-jobs",os.getenv(f"{prefix}_MAX_JOBS","50"),"--timeout",os.getenv(f"{prefix}_TIMEOUT","30"),"--output",str(output)]
        sources.append(SourceSpec(source,output,add_existing_job_ids(command,source)))
    if os.getenv("FETCH_MORGAN_STANLEY", "false").lower() == "true":
        output = ROOT / "data" / "morgan_stanley_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_eightfold_jobs.py"), "--domain", "morganstanley.com",
                   "--query", os.getenv("MORGAN_STANLEY_QUERY", "Software Engineer"), "--location", os.getenv("MORGAN_STANLEY_LOCATION", "Bengaluru, KA, India"),
                   "--max-pages", os.getenv("MORGAN_STANLEY_MAX_PAGES", "5"), "--max-jobs", os.getenv("MORGAN_STANLEY_MAX_JOBS", "50"),
                   "--timeout", os.getenv("MORGAN_STANLEY_TIMEOUT", "30"), "--output", str(output)]
        sources.append(SourceSpec("morgan_stanley", output, add_existing_job_ids(command, "morgan_stanley")))
    for source_name, prefix, domain, company, sort_by, seniority, include_remote, filters in (
        ("qualcomm", "QUALCOMM", "qualcomm.com", "Qualcomm", "timestamp", "Mid-Level,Entry", False, ("filter_job_family=software engineering",)),
        # PayPal's public PCSx API accepts the category and work-location
        # facets but currently returns no results for its browser employment
        # type label. Keep the filters the API can apply rather than dropping
        # all PayPal results.
        ("paypal", "PAYPAL", "paypal.com", "PayPal", "distance", "", True, ("filter_job_category=Software Engineering", "filter_work_location_option=onsite,hybrid,remote_local")),
    ):
        if os.getenv(f"FETCH_{prefix}", "false").lower() != "true":
            continue
        output = ROOT / "data" / f"{source_name}_jobs.json"
        command = [sys.executable, str(ROOT / "career portal scripts" / "fetch_eightfold_jobs.py"), "--domain", domain, "--company", company,
                   "--query", os.getenv(f"{prefix}_QUERY", "Software Engineer"), "--location", os.getenv(f"{prefix}_LOCATION", "India"),
                   "--sort-by", os.getenv(f"{prefix}_SORT_BY", sort_by), "--seniority", os.getenv(f"{prefix}_SENIORITY", seniority), "--max-pages", os.getenv(f"{prefix}_MAX_PAGES", "5"),
                   "--max-jobs", os.getenv(f"{prefix}_MAX_JOBS", "50"), "--timeout", os.getenv(f"{prefix}_TIMEOUT", "30"), "--output", str(output)]
        for filter_value in filters:
            command.extend(["--filter", filter_value])
        if os.getenv(f"{prefix}_INCLUDE_REMOTE", str(include_remote).lower()).lower() == "true": command.append("--include-remote")
        else: command.append("--no-include-remote")
        if os.getenv(f"{prefix}_INCLUDE_RELOCATION", "false").lower() == "true": command.append("--include-relocation")
        else: command.append("--no-include-relocation")
        sources.append(SourceSpec(source_name, output, add_existing_job_ids(command, source_name)))
    if os.getenv("FETCH_NUTANIX", "false").lower() == "true":
        output=ROOT/"data"/"nutanix_jobs.json"; command=[sys.executable,str(ROOT/"career portal scripts"/"fetch_nutanix_jobs.py"),os.getenv("NUTANIX_JOBS_URL",""),"--max-jobs",os.getenv("NUTANIX_MAX_JOBS","50"),"--timeout",os.getenv("NUTANIX_TIMEOUT","30"),"--output",str(output)]
        sources.append(SourceSpec("nutanix",output,add_existing_job_ids(command,"nutanix")))
    for source_name, prefix in (("visa", "VISA"), ("crowdstrike", "CROWDSTRIKE")):
        portal_url = os.getenv(f"{prefix}_JOBS_URL", "").strip()
        if os.getenv(f"FETCH_{prefix}", "false").lower() != "true" or not portal_url:
            continue
        output = ROOT / "data" / f"{source_name}_jobs.json"
        command = [
            sys.executable, str(ROOT / "career portal scripts" / f"fetch_{source_name}_jobs.py"), portal_url,
            "--max-jobs", os.getenv(f"{prefix}_MAX_JOBS", "50"),
            "--page-size", os.getenv(f"{prefix}_PAGE_SIZE", "20"),
            "--timeout", os.getenv(f"{prefix}_TIMEOUT", "30"),
            "--output", str(output),
        ]
        sources.append(SourceSpec(source_name, output, add_existing_job_ids(command, source_name)))
    if os.getenv("FETCH_CORNERSTONE", "false").lower() == "true":
        output=ROOT/"data"/"cornerstone_jobs.json"; command=[sys.executable,str(ROOT/"career portal scripts"/"fetch_cornerstone_jobs.py"),os.getenv("CORNERSTONE_JOBS_URL",""),"--max-jobs",os.getenv("CORNERSTONE_MAX_JOBS","50"),"--timeout",os.getenv("CORNERSTONE_TIMEOUT","45"),"--output",str(output)]
        if os.getenv("CORNERSTONE_HEADED","false").lower()=="true":command.append("--headed")
        sources.append(SourceSpec("cornerstone",output,command))
    flipkart_url = os.getenv("FLIPKART_LINKEDIN_JOBS_URL", "").strip()
    if os.getenv("FETCH_FLIPKART_LINKEDIN", "false").lower() == "true" and flipkart_url:
        output = ROOT / "data" / "flipkart_jobs.json"
        command = [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_linkedin_flipkart_jobs.py"), flipkart_url,
            "--max-jobs", os.getenv("FLIPKART_LINKEDIN_MAX_JOBS", "50"),
            "--timeout", os.getenv("FLIPKART_LINKEDIN_TIMEOUT", "30"),
            "--delay", os.getenv("FLIPKART_LINKEDIN_DELAY", "1"),
            "--output", str(output),
        ]
        sources.append(SourceSpec("flipkart", output, add_existing_job_ids(command, "flipkart")))
    linkedin_url = os.getenv("LINKEDIN_JOBS_URL", "").strip()
    if os.getenv("FETCH_LINKEDIN", "false").lower() == "true" and linkedin_url:
        output = ROOT / "data" / "linkedin_jobs.json"
        command = [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_linkedin_jobs.py"), linkedin_url,
            "--max-pages", os.getenv("LINKEDIN_MAX_PAGES", "20"),
            "--max-jobs", os.getenv("LINKEDIN_MAX_JOBS", "50"),
            "--timeout", os.getenv("LINKEDIN_TIMEOUT", "30"),
            "--min-delay", os.getenv("LINKEDIN_MIN_DELAY", "1"),
            "--max-delay", os.getenv("LINKEDIN_MAX_DELAY", "1"),
            "--429-max-retries", os.getenv("LINKEDIN_429_MAX_RETRIES", "8"),
            "--429-initial-backoff-seconds", os.getenv("LINKEDIN_429_INITIAL_BACKOFF_SECONDS", "60"),
            "--429-max-backoff-seconds", os.getenv("LINKEDIN_429_MAX_BACKOFF_SECONDS", "960"),
            "--output", str(output),
        ]
        sources.append(SourceSpec("linkedin", output, add_existing_job_ids(command, "linkedin")))
    return sources


def sync_configured_jobs(*, strict: bool = True) -> None:
    configure_logging()
    sources = configured_sources()
    if not sources:
        print("No job source configured. Set FETCH_GOOGLE or another FETCH_* flag and its portal URL in .env.")
        return
    concurrency = int(os.getenv("JOB_FETCH_CONCURRENCY", "4"))
    if concurrency < 1:
        raise ValueError("JOB_FETCH_CONCURRENCY must be at least 1")
    failures: dict[str, Exception] = {}
    successful: set[str] = set()
    with ThreadPoolExecutor(max_workers=min(concurrency, len(sources)), thread_name_prefix="portal-fetch") as executor:
        futures = {executor.submit(run_command, source.fetch_command): source for source in sources}
        for future in as_completed(futures):
            source = futures[future]
            try:
                future.result()
                successful.add(source.name)
                print(f"[sync] Fetch succeeded: {source.name}")
            except Exception as error:
                failures[source.name] = error
                print(f"[sync] Fetch failed: {source.name}: {error}")
    # Fetches are I/O-bound and can run concurrently. Imports remain serial to
    # keep SQLite writes, de-duplication, and deterministic filtering safe.
    for source in sources:
        if source.name in successful:
            print(f"[sync] Importing {source.name} snapshot...")
            run_command([sys.executable, str(ROOT / "ingest_jobs.py"), str(source.output), "--source", source.name])
    if failures:
        summary = "; ".join(f"{name}: {error}" for name, error in failures.items())
        if strict:
            raise RuntimeError(f"One or more portal fetches failed after successful imports: {summary}")
        print(f"[sync] Continuing after portal fetch failures: {summary}")


if __name__ == "__main__":
    sync_configured_jobs()
