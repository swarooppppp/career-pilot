"""Kafka producer for durable job-match requests."""

from __future__ import annotations

import json
import os
import logging
from typing import Any

from app.services.job_store import mark_event_published, pending_outbox_events

try:
    from kafka import KafkaProducer
    from kafka.admin import KafkaAdminClient, NewPartitions, NewTopic
except ImportError:
    KafkaProducer = None
    KafkaAdminClient = None


JOB_MATCH_TOPIC = "career-pilot.job-match-requested"
logger = logging.getLogger(__name__)


def topic_partitions() -> int:
    value = int(os.getenv("KAFKA_TOPIC_PARTITIONS", "8"))
    if value < 1:
        raise ValueError("KAFKA_TOPIC_PARTITIONS must be at least 1")
    return value


def ensure_job_match_topic() -> None:
    """Create or expand the topic before producers can auto-create one partition."""
    if KafkaAdminClient is None:
        raise RuntimeError("install kafka-python-ng before provisioning Kafka topics")
    admin = KafkaAdminClient(bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092").split(","))
    try:
        if JOB_MATCH_TOPIC not in admin.list_topics():
            admin.create_topics([NewTopic(JOB_MATCH_TOPIC, num_partitions=topic_partitions(), replication_factor=1)])
            logger.info("Created Kafka topic %s with %s partitions", JOB_MATCH_TOPIC, topic_partitions())
            return
        topics = admin.describe_topics([JOB_MATCH_TOPIC])
        current = len(topics[0].get("partitions", []))
        if current < topic_partitions():
            admin.create_partitions({JOB_MATCH_TOPIC: NewPartitions(topic_partitions())})
            logger.info("Expanded Kafka topic %s from %s to %s partitions", JOB_MATCH_TOPIC, current, topic_partitions())
    finally:
        admin.close()


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
    ensure_job_match_topic()
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
    logger.info("Published %s Kafka job events", published)
    return published
