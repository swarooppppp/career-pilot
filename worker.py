#!/usr/bin/env python3
"""Consume queued match requests and run the LangGraph/Gemini workflow."""

from __future__ import annotations

import json
import os

from kafka import KafkaConsumer

from app.services.job_pipeline import process_job
from app.services.job_queue import JOB_MATCH_TOPIC
from app.services.job_store import claim_queued_job


def main() -> None:
    consumer = KafkaConsumer(
        JOB_MATCH_TOPIC,
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(","),
        group_id="career-pilot-match-workers",
        enable_auto_commit=False,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        auto_offset_reset="earliest",
    )
    print("Career Pilot worker is consuming job-match events.")
    for message in consumer:
        job_id = message.value.get("job_id")
        job = claim_queued_job(job_id) if job_id else None
        if job:
            process_job(job)
        # Commit after the database has a completed/failed terminal state. A
        # duplicate delivery is harmless because claim_queued_job is idempotent.
        consumer.commit()


if __name__ == "__main__":
    main()
