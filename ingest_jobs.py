#!/usr/bin/env python3
"""Normalize a JSON file produced by a job-fetching script into Career Pilot."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app.services.candidate_experience import experience_years_for_import
from app.services.job_store import import_jobs


ROOT = Path(__file__).resolve().parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON output from a portal fetcher")
    parser.add_argument("--source", required=True, help="Source name, e.g. google or microsoft")
    parser.add_argument("--candidate-years", type=float, default=None)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    candidate_years = args.candidate_years
    if candidate_years is None:
        fallback_years = float(os.getenv("CANDIDATE_YEARS_EXPERIENCE", "2"))
        candidate_years = experience_years_for_import(
            (ROOT / "data" / "master_experience.md").read_text(encoding="utf-8"), fallback_years
        )
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    raw_jobs = payload.get("jobs") if isinstance(payload, dict) else payload
    if not isinstance(raw_jobs, list):
        raise ValueError("input JSON must be a list or an object with a 'jobs' list")
    print(json.dumps(import_jobs(raw_jobs, args.source, candidate_years), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
