"""Kafka producer for durable job-match requests."""

from __future__ import annotations

import json
import os
from typing import Any

from app.services.job_store import mark_event_published, pending_outbox_events

try:
    from kafka import KafkaProducer
except ImportError:
    KafkaProducer = None


JOB_MATCH_TOPIC = "career-pilot.job-match-requested"


def queue_backend() -> str:
    backend = os.getenv("QUEUE_BACKEND", "local").lower()
    if backend not in {"local", "kafka"}:
        raise ValueError("QUEUE_BACKEND must be 'local' or 'kafka'")
    return backend


def _producer() -> Any:
    if KafkaProducer is None:
        raise RuntimeError("install kafka-python-ng before publishing job-match events")
    return KafkaProducer(
        bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(","),
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
        acks="all",
        retries=3,
    )


def publish_outbox_events(limit: int = 100) -> int:
    """Publish stored events, marking each one after Kafka acknowledges it."""
    producer = _producer()
    published = 0
    try:
        for event in pending_outbox_events(limit):
            producer.send(JOB_MATCH_TOPIC, event["payload"], key=event["job_id"].encode("utf-8")).get(timeout=10)
            mark_event_published(event["id"])
            published += 1
    finally:
        producer.flush()
        producer.close()
    return published
