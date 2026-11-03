#!/usr/bin/env python3
"""Fill missing DB publication dates from existing snapshots, without importing jobs."""
import argparse
import json
from pathlib import Path

from sqlalchemy import select, update

from app.services import job_store
from app.services.posting_dates import publication_date

ROOT = Path(__file__).resolve().parent


def snapshot_dates(roots):
    files = sorted({p for root in roots for p in root.rglob("*_jobs.json")}, key=lambda p: p.stat().st_mtime, reverse=True)
    candidates = {}
    for path in files:
        source = path.name[:-len("_jobs.json")]
        try:
            payload = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        rows = payload.get("jobs") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            ident = raw.get("id") or raw.get("job_id") or raw.get("jobId")
            date, precision = publication_date(raw, source)
            if ident is not None and date is not None:
                candidates.setdefault((source, str(ident)), (date, precision))
    return candidates


def backfill(candidates):
    job_store.initialise()
    changed = 0
    with job_store._engine(job_store.database_url()).begin() as connection:
        rows = connection.execute(select(job_store.jobs.c.id, job_store.jobs.c.source, job_store.jobs.c.external_job_id)
                                  .where(job_store.jobs.c.posted_date.is_(None))).mappings()
        for row in rows:
            value = candidates.get((row["source"], row["external_job_id"]))
            if value is None:
                continue
            result = connection.execute(update(job_store.jobs).where(job_store.jobs.c.id == row["id"], job_store.jobs.c.posted_date.is_(None))
                                        .values(posted_date=value[0], posted_date_precision=value[1]))
            changed += result.rowcount
    return changed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    candidates = snapshot_dates([ROOT / "data", ROOT / "local_career_portals" / "data"])
    if args.dry_run:
        print(json.dumps({"snapshot_jobs_with_publication_dates": len(candidates), "database_modified": False}))
    else:
        print(json.dumps({"snapshot_jobs_with_publication_dates": len(candidates), "existing_jobs_backfilled": backfill(candidates)}))


if __name__ == "__main__":
    main()
