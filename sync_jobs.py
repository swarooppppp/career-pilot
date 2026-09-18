#!/usr/bin/env python3
"""Fetch and import job sources configured in .env."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent


def run_command(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def sync_configured_jobs() -> None:
    load_dotenv(ROOT / ".env")
    google_url = os.getenv("GOOGLE_CAREERS_URL", "").strip()
    if google_url:
        output = ROOT / "data" / "google_jobs.json"
        run_command(
            [
                sys.executable,
                str(ROOT / "career portal scripts" / "fetch_google_jobs.py"),
                google_url,
                "--max-pages",
                os.getenv("GOOGLE_MAX_PAGES", "1"),
                "--output",
                str(output),
            ]
        )
        run_command([sys.executable, str(ROOT / "ingest_jobs.py"), str(output), "--source", "google"])

    if os.getenv("FETCH_MICROSOFT", "false").lower() == "true":
        output = ROOT / "data" / "microsoft_jobs.json"
        run_command(
            [
                sys.executable,
                str(ROOT / "career portal scripts" / "fetch_microsoft_jobs.py"),
                "--query",
                os.getenv("MICROSOFT_QUERY", "Software Engineer"),
                "--location",
                os.getenv("MICROSOFT_LOCATION", "India"),
                "--max-pages",
                os.getenv("MICROSOFT_MAX_PAGES", "1"),
                "--delay",
                os.getenv("MICROSOFT_DELAY", "1"),
                "--max-retries",
                os.getenv("MICROSOFT_MAX_RETRIES", "4"),
                "--backoff-seconds",
                os.getenv("MICROSOFT_BACKOFF_SECONDS", "2"),
                "--output",
                str(output),
            ]
        )
        run_command([sys.executable, str(ROOT / "ingest_jobs.py"), str(output), "--source", "microsoft"])

    if not google_url and os.getenv("FETCH_MICROSOFT", "false").lower() != "true":
        print("No job source configured. Set GOOGLE_CAREERS_URL or FETCH_MICROSOFT=true in .env.")


if __name__ == "__main__":
    sync_configured_jobs()
