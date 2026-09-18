#!/usr/bin/env python3
"""Run asynchronous match processing locally without Docker or Kafka."""

from __future__ import annotations

import time

from app.services.job_pipeline import process_job
from app.services.job_store import claim_next_queued_job, requeue_stale_processing_jobs


def main() -> None:
    print("Career Pilot local worker is watching the SQLite job queue.")
    while True:
        requeue_stale_processing_jobs()
        job = claim_next_queued_job()
        if job:
            process_job(job)
            continue
        time.sleep(2)


if __name__ == "__main__":
    main()
