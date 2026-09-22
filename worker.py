#!/usr/bin/env python3
"""Consume queued match requests and run the LangGraph/Gemini workflow."""

from __future__ import annotations

import json
import os
import time

from kafka import KafkaConsumer

from app.logging_utils import configure_logging
from app.services.job_pipeline import process_job
from app.services.job_queue import JOB_MATCH_TOPIC
from app.services.job_store import claim_queued_job, requeue_stale_processing_jobs


def main() -> None:
    configure_logging()
    consumer = KafkaConsumer(
        JOB_MATCH_TOPIC,
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(","),
        group_id="career-pilot-match-workers",
        enable_auto_commit=False,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        auto_offset_reset="earliest",
    )
    print("Career Pilot worker is consuming job-match events.")
    requeue_stale_processing_jobs()
    last_requeue = time.monotonic()
    for message in consumer:
        if time.monotonic() - last_requeue >= 30:
            requeue_stale_processing_jobs()
            last_requeue = time.monotonic()
        job_id = message.value.get("job_id")
        job = claim_queued_job(job_id) if job_id else None
        if job:
            print(f"[kafka-worker] Claimed {job['id']} — {job['company_name']} / {job['job_title']}")
            process_job(job)
        # Commit after the database has a completed/failed terminal state. A
        # duplicate delivery is harmless because claim_queued_job is idempotent.
        consumer.commit()


if __name__ == "__main__":
    main()
