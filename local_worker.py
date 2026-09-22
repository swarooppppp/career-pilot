#!/usr/bin/env python3
"""Run asynchronous match processing locally without Docker or Kafka."""

from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import os

from app.services.job_pipeline import process_job
from app.services.job_store import claim_next_queued_job, requeue_stale_processing_jobs
from app.logging_utils import configure_logging


def main() -> None:
    configure_logging()
    concurrency = int(os.getenv("MATCH_WORKER_CONCURRENCY", "4"))
    if concurrency < 1:
        raise ValueError("MATCH_WORKER_CONCURRENCY must be at least 1")
    print(f"Career Pilot local worker is watching the SQLite job queue with {concurrency} slots.")
    active = set()
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="match-worker") as executor:
        while True:
            requeue_stale_processing_jobs()
            while len(active) < concurrency:
                job = claim_next_queued_job()
                if not job:
                    break
                print(f"[worker] Claimed {job['id']} — {job['company_name']} / {job['job_title']}")
                active.add(executor.submit(process_job, job))
            if not active:
                time.sleep(2)
                continue
            completed, active = wait(active, timeout=2, return_when=FIRST_COMPLETED)
            for future in completed:
                try:
                    future.result()
                except Exception as error:
                    # A database/pipeline fault should be visible rather than
                    # silently disappearing when the executor frees its slot.
                    print(f"Local match worker error: {error}")
            active = set(active)


if __name__ == "__main__":
    main()
