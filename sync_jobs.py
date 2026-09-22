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


ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class SourceSpec:
    name: str
    output: Path
    fetch_command: list[str]


def run_command(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def configured_sources() -> list[SourceSpec]:
    load_dotenv(ROOT / ".env")
    google_url = os.getenv("GOOGLE_CAREERS_URL", "").strip()
    sources: list[SourceSpec] = []
    if google_url:
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
        sources.append(SourceSpec("atlassian", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_atlassian_jobs.py"), atlassian_url,
            "--max-jobs", os.getenv("ATLASSIAN_MAX_JOBS", "50"),
            "--timeout", os.getenv("ATLASSIAN_TIMEOUT", "60"),
            "--output", str(output),
        ]))
    apple_url = os.getenv("APPLE_JOBS_URL", "").strip()
    if os.getenv("FETCH_APPLE", "false").lower() == "true" and apple_url:
        output = ROOT / "data" / "apple_jobs.json"
        sources.append(SourceSpec("apple", output, [
            sys.executable, str(ROOT / "career portal scripts" / "fetch_apple_jobs.py"), apple_url,
            "--max-pages", os.getenv("APPLE_MAX_PAGES", "10"),
            "--max-jobs", os.getenv("APPLE_MAX_JOBS", "50"),
            "--timeout", os.getenv("APPLE_TIMEOUT", "30"),
            "--output", str(output),
        ]))
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
        sources.append(SourceSpec("microsoft", output, [
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
        ]))
    return sources


def sync_configured_jobs() -> None:
    configure_logging()
    sources = configured_sources()
    if not sources:
        print("No job source configured. Set GOOGLE_CAREERS_URL, FETCH_AMAZON=true, FETCH_SALESFORCE=true, FETCH_INTUIT=true, FETCH_ATLASSIAN=true, FETCH_APPLE=true, FETCH_META=true, FETCH_UBER=true, or FETCH_MICROSOFT=true in .env.")
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
        raise RuntimeError(f"One or more portal fetches failed after successful imports: {summary}")


if __name__ == "__main__":
    sync_configured_jobs()
