"""PostgreSQL persistence for normalized jobs and transactional outbox events."""

from __future__ import annotations

import hashlib
import math
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from dotenv import load_dotenv
from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    delete,
    func,
    Float,
    Index,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    inspect,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.services.posting_dates import publication_date, utc


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DEFAULT_DATABASE_URL = "postgresql+psycopg://career_pilot:career_pilot@localhost:5432/career_pilot"
logger = logging.getLogger(__name__)
metadata = MetaData()
json_column = JSON().with_variant(JSONB, "postgresql")

jobs = Table(
    "jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("source", String(100), nullable=False),
    Column("external_job_id", String(255), nullable=False),
    Column("company_name", String(255), nullable=False),
    Column("job_title", String(500), nullable=False),
    Column("location", String(500)),
    Column("application_url", Text),
    Column("posted_date", DateTime(timezone=True)),
    Column("posted_date_precision", String(12)),
    Column("job_description", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("minimum_years_experience", Float),
    Column("experience_eligible", Boolean, nullable=False),
    Column("filter_reason", Text, nullable=False),
    Column("analysis_status", String(30), nullable=False, default="pending"),
    Column("user_status", String(30), nullable=False, default="new"),
    Column("applied", Boolean, nullable=False, default=False, server_default="false"),
    Column("applied_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
    Column("resume_status", String(30)),
    Column("resume_error", Text),
    Column("resume_filename", Text),
    Column("match_score", Float),
    Column("match_json", json_column),
    Column("analysis_error", Text),
    Column("processed_at", DateTime(timezone=True)),
    Column("resume_generated_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
Index("jobs_source_external_id", jobs.c.source, jobs.c.external_job_id, unique=True)
Index("jobs_dashboard_index", jobs.c.experience_eligible, jobs.c.analysis_status, jobs.c.user_status)

job_tombstones = Table(
    "job_tombstones", metadata,
    Column("source", String(100), primary_key=True),
    Column("external_job_id", String(255), primary_key=True),
    Column("applied", Boolean, nullable=False),
    Column("applied_at", DateTime(timezone=True)),
    Column("deleted_at", DateTime(timezone=True)),
)

job_events = Table(
    "job_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("job_id", String(36), nullable=False),
    Column("event_type", String(100), nullable=False),
    Column("payload", json_column, nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("job_events_pending_index", job_events.c.published_at, job_events.c.created_at)

# PostgreSQL workers use this single locked row to coordinate rate-limit slot
# creation. The actual slot rows make the limit a rolling 60-second window.
gemini_rate_locks = Table(
    "gemini_rate_locks",
    metadata,
    Column("id", String(30), primary_key=True),
)
gemini_request_slots = Table(
    "gemini_request_slots",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
Index("gemini_request_slots_created_index", gemini_request_slots.c.created_at)

analysis_batches = Table(
    "analysis_batches",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("provider_batch_id", String(255), nullable=False, unique=True),
    Column("input_file_id", String(255), nullable=False),
    Column("output_file_id", String(255)),
    Column("status", String(30), nullable=False),
    Column("error", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
analysis_batch_items = Table(
    "analysis_batch_items",
    metadata,
    Column("batch_id", String(36), primary_key=True),
    Column("job_id", String(36), primary_key=True),
    # A job can legitimately be resubmitted in a later batch after a manual
    # retry. The OpenAI custom ID is therefore unique to a submission, not to
    # the job for all time.
    Column("custom_id", String(100), nullable=False),
    Column("content_hash", String(64)),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@lru_cache(maxsize=4)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def _migrate_sqlite_batch_item_custom_ids(engine: Engine) -> None:
    """Remove the obsolete global unique constraint from local SQLite data."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        definition = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'analysis_batch_items'"
        ).scalar_one_or_none()
        if not definition or "UNIQUE (custom_id)" not in definition:
            return
        # SQLite cannot drop a table-level unique constraint in place. Rebuild
        # this small tracking table transactionally and preserve every row.
        connection.exec_driver_sql(
            "CREATE TABLE analysis_batch_items_replacement ("
            "batch_id VARCHAR(36) NOT NULL, "
            "job_id VARCHAR(36) NOT NULL, "
            "custom_id VARCHAR(100) NOT NULL, "
            "PRIMARY KEY (batch_id, job_id))"
        )
        connection.exec_driver_sql(
            "INSERT INTO analysis_batch_items_replacement (batch_id, job_id, custom_id) "
            "SELECT batch_id, job_id, custom_id FROM analysis_batch_items"
        )
        connection.exec_driver_sql("DROP TABLE analysis_batch_items")
        connection.exec_driver_sql("ALTER TABLE analysis_batch_items_replacement RENAME TO analysis_batch_items")
        logger.info("Migrated SQLite batch tracking to submission-scoped custom IDs")


def initialise() -> None:
    engine = _engine(database_url())
    metadata.create_all(engine)
    _migrate_posting_dates(engine)
    _migrate_local_actions(engine)
    _migrate_sqlite_batch_item_custom_ids(engine)
    if "content_hash" not in {c["name"] for c in inspect(engine).get_columns("analysis_batch_items")}:
        with engine.begin() as connection:
            connection.exec_driver_sql("ALTER TABLE analysis_batch_items ADD COLUMN content_hash VARCHAR(64)")


def _migrate_posting_dates(engine: Engine) -> None:
    """Add nullable publication fields to existing SQLite/PostgreSQL databases."""
    existing = {column["name"] for column in inspect(engine).get_columns("jobs")}
    types = {"posted_date": "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE",
             "posted_date_precision": "VARCHAR(12)"}
    for name, sql_type in types.items():
        if name in existing:
            continue
        try:
            with engine.begin() as connection:
                optional = "IF NOT EXISTS " if engine.dialect.name == "postgresql" else ""
                connection.exec_driver_sql(f"ALTER TABLE jobs ADD COLUMN {optional}{name} {sql_type}")
        except OperationalError:
            # Another local process may have completed the same migration.
            if name not in {column["name"] for column in inspect(engine).get_columns("jobs")}:
                raise


def _migrate_local_actions(engine: Engine) -> None:
    existing = {c["name"] for c in inspect(engine).get_columns("jobs")}
    stamp = "DATETIME" if engine.dialect.name == "sqlite" else "TIMESTAMP WITH TIME ZONE"
    fields = {"applied": "BOOLEAN NOT NULL DEFAULT FALSE", "applied_at": stamp,
              "deleted_at": stamp, "resume_status": "VARCHAR(30)", "resume_error": "TEXT", "resume_filename": "TEXT"}
    for name, kind in fields.items():
        if name not in existing:
            with engine.begin() as connection:
                connection.exec_driver_sql(f"ALTER TABLE jobs ADD COLUMN {name} {kind}")
    with engine.begin() as connection:
        connection.execute(update(jobs).where(jobs.c.user_status == "applied", jobs.c.applied.is_(False)).values(applied=True, applied_at=jobs.c.updated_at))


def extract_experience_years(description: str) -> tuple[float | None, float | None]:
    """Return the lowest and highest explicit YOE values found in a JD."""
    # A number normally appears to the left of "years" ("6 years"). Check
    # those forms first, including ranges where the first number is the minimum.
    left_patterns = (
        r"\b(\d+(?:\.\d+)?)\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?\s*(?:years?|yrs?)\b",
        r"\b(\d+(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b",
        r"\b(\d+(?:\.\d+)?)(?:\s+\w+){1,3}\s+(?:years?|yrs?)\b",
    )
    left_values = [
        float(value)
        for pattern in left_patterns
        for value in re.findall(pattern, description, flags=re.IGNORECASE)
    ]
    # Also support reversed wording, e.g. "years of experience: 6".
    right_pattern = (
        r"\b(?:years?|yrs?)(?:\s+(?:of|in|with|relevant|professional|work|industry|"
        r"hands-on|practical|experience)){0,3}\s*[:=-]\s*(\d+(?:\.\d+)?)\b"
    )
    right_values = [float(value) for value in re.findall(right_pattern, description, flags=re.IGNORECASE)]

    values = left_values + right_values
    return (min(values), max(values)) if values else (None, None)


def extract_minimum_years(description: str) -> float | None:
    """Compatibility helper for callers that only need the minimum value."""
    return extract_experience_years(description)[0]


def _google_job_detail_url(external_job_id: str, title: str) -> str:
    """Build Google's public listing URL, rather than its Apply/sign-in URL."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return (
        "https://www.google.com/about/careers/applications/jobs/results/"
        f"{external_job_id}-{slug}"
    )


def normalise_job(raw_job: dict[str, Any], source: str, candidate_years: float) -> dict[str, Any]:
    description = str(
        raw_job.get("jobDescriptionText")
        or raw_job.get("job_description")
        or raw_job.get("description")
        or ""
    ).strip()
    if not description:
        raise ValueError("job has no text description")
    external_id = str(raw_job.get("id") or raw_job.get("job_id") or raw_job.get("jobId") or _hash(description))
    title = str(raw_job.get("title") or raw_job.get("name") or raw_job.get("job_title") or "").strip()
    if not title:
        raise ValueError("job has no title")
    locations = raw_job.get("locations") or raw_job.get("location") or ""
    location = ", ".join(str(item) for item in locations if item) if isinstance(locations, list) else str(locations)
    minimum_years, maximum_years = extract_experience_years(description)
    allowed_maximum = math.ceil(candidate_years)
    experience_eligible = minimum_years is None or minimum_years <= allowed_maximum
    experience_reason = (
        "no explicit experience requirement found"
        if minimum_years is None
        else f"explicit experience range is {minimum_years:g}-{maximum_years:g} years; minimum requirement allowed is {allowed_maximum:g} years"
    )
    title_red_flag = re.search(r"\b(?:manager|staff)\b", title, flags=re.IGNORECASE)
    eligible = experience_eligible and not title_red_flag
    reason = (
        f"title contains excluded seniority word '{title_red_flag.group(0).lower()}'"
        if title_red_flag else experience_reason
    )
    application_url = str(
        raw_job.get("application_url")
        or raw_job.get("publicUrl")
        or raw_job.get("applyUrl")
        or raw_job.get("url")
        or ""
    )
    # Existing Google snapshots stored the URL behind Apply, which sends the
    # user to sign-in. Reconstruct the stable public listing URL on import.
    if (
        source.lower() == "google"
        and "/applications/signin" in application_url
    ):
        application_url = _google_job_detail_url(external_id, title)

    posted_date, precision = publication_date(raw_job, source)
    return {
        "source": source,
        "external_job_id": external_id,
        "company_name": str(raw_job.get("company") or raw_job.get("company_name") or source.title()),
        "job_title": title,
        "location": location,
        "application_url": application_url,
        "posted_date": posted_date,
        "posted_date_precision": precision,
        "job_description": description,
        "content_hash": _hash(description),
        "minimum_years_experience": minimum_years,
        "experience_eligible": eligible,
        "filter_reason": reason,
    }


def import_jobs(raw_jobs: Iterable[dict[str, Any]], source: str, candidate_years: float) -> dict[str, int]:
    initialise()
    logger.info("Importing %s jobs with candidate threshold %.1f years", source, candidate_years)
    counts = {"imported": 0, "updated": 0, "skipped": 0, "ineligible": 0, "imported_eligible": 0}
    with _engine(database_url()).begin() as connection:
        for raw_job in raw_jobs:
            try:
                job = normalise_job(raw_job, source, candidate_years)
            except ValueError:
                counts["skipped"] += 1
                continue
            existing = connection.execute(
                select(
                    jobs.c.id, jobs.c.content_hash, jobs.c.application_url,
                    jobs.c.minimum_years_experience, jobs.c.experience_eligible, jobs.c.filter_reason,
                    jobs.c.posted_date, jobs.c.posted_date_precision,
                ).where(
                    jobs.c.source == job["source"], jobs.c.external_job_id == job["external_job_id"]
                )
            ).mappings().first()
            if not job["experience_eligible"]:
                counts["ineligible"] += 1
                if existing:
                    _remove_jobs(connection, [existing["id"]])
                continue
            tombstone = connection.execute(select(job_tombstones.c.source).where(
                job_tombstones.c.source == job["source"], job_tombstones.c.external_job_id == job["external_job_id"])).first()
            if tombstone:
                counts["skipped"] += 1
                continue
            if existing:
                if job["posted_date"] is None:
                    job["posted_date"] = existing["posted_date"]
                    job["posted_date_precision"] = existing["posted_date_precision"]
                if existing["content_hash"] == job["content_hash"]:
                    # Refresh deterministic eligibility even if the listing's
                    # contents are unchanged. Keep any completed match intact.
                    refresh_values = {
                        "application_url": job["application_url"],
                        "minimum_years_experience": job["minimum_years_experience"],
                        "experience_eligible": job["experience_eligible"],
                        "filter_reason": job["filter_reason"],
                        "posted_date": job["posted_date"],
                        "posted_date_precision": job["posted_date_precision"],
                    }
                    if any((utc(existing[key]) != utc(value) if isinstance(existing[key], datetime) and isinstance(value, datetime)
                            else existing[key] != value) for key, value in refresh_values.items()):
                        connection.execute(
                            update(jobs).where(jobs.c.id == existing["id"]).values(
                                **refresh_values, updated_at=_now()
                            )
                        )
                        counts["updated"] += 1
                    else:
                        counts["skipped"] += 1
                    continue
                connection.execute(
                    update(jobs).where(jobs.c.id == existing["id"]).values(
                        **job,
                        analysis_status="retry_requested",
                        resume_status=None, resume_filename=None, resume_error=None,
                        match_score=None,
                        match_json=None,
                        analysis_error=None,
                        processed_at=None,
                        updated_at=_now(),
                    )
                )
                counts["updated"] += 1
            else:
                connection.execute(
                    insert(jobs).values(
                        id=str(uuid4()),
                        **job,
                        analysis_status="pending",
                        user_status="new",
                        created_at=_now(),
                        updated_at=_now(),
                    )
                )
                counts["imported"] += 1
                counts["imported_eligible"] += int(job["experience_eligible"])
    logger.info("Import finished for %s: %s", source, counts)
    return counts


def _serialize(row: Any, include_description: bool = False) -> dict[str, Any]:
    job = dict(row)
    if job.get("posted_date") is not None:
        job["posted_date"] = utc(job["posted_date"])
    job["match"] = job.pop("match_json", None)
    if not include_description:
        job.pop("job_description", None)
    return job


def list_jobs(include_ineligible: bool = False) -> list[dict[str, Any]]:
    initialise()
    statement = select(jobs).where(jobs.c.user_status != "dismissed", jobs.c.applied.is_(False), jobs.c.deleted_at.is_(None))
    if not include_ineligible:
        statement = statement.where(jobs.c.experience_eligible.is_(True))
    statement = statement.order_by(jobs.c.match_score.desc().nulls_last(), jobs.c.created_at.desc())
    with _engine(database_url()).connect() as connection:
        return [_serialize(row) for row in connection.execute(statement).mappings()]


def existing_external_job_ids(source: str) -> set[str]:
    """Return the portal IDs already imported for one source."""
    initialise()
    statement = select(jobs.c.external_job_id).where(jobs.c.source == source)
    with _engine(database_url()).connect() as connection:
        return {str(row.external_job_id) for row in connection.execute(statement)}


def get_job(job_id: str) -> dict[str, Any] | None:
    initialise()
    with _engine(database_url()).connect() as connection:
        row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
    return _serialize(row, include_description=True) if row else None


def queue_pending_jobs(limit: int, create_outbox_events: bool = True) -> list[str]:
    """Atomically mark work queued and create outbox records in the same transaction."""
    initialise()
    with _engine(database_url()).begin() as connection:
        previously_submitted_job_ids = select(analysis_batch_items.c.job_id)
        candidates = connection.execute(
            select(jobs.c.id)
            .where(
                jobs.c.experience_eligible.is_(True),
                jobs.c.analysis_status.in_(["pending", "retry_requested"]),
                jobs.c.user_status.in_(["new", "saved", "resume_generated"]),
                jobs.c.applied.is_(False), jobs.c.deleted_at.is_(None),
                # Avoid spending again on a source-refresh regression. A
                # retry_requested status is set only by the explicit UI retry.
                (jobs.c.analysis_status == "retry_requested") | ~jobs.c.id.in_(previously_submitted_job_ids),
            )
            .order_by(jobs.c.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).scalars().all()
        for job_id in candidates:
            connection.execute(
                update(jobs).where(jobs.c.id == job_id).values(analysis_status="queued", updated_at=_now())
            )
            if create_outbox_events:
                connection.execute(
                    insert(job_events).values(
                        id=str(uuid4()),
                        job_id=job_id,
                        event_type="job.match_requested",
                        payload={"job_id": job_id},
                        created_at=_now(),
                    )
                )
    queued = list(candidates)
    logger.info("Queued %s eligible jobs (outbox=%s)", len(queued), create_outbox_events)
    return queued


def reserve_pending_jobs_for_batch(limit: int) -> list[dict[str, Any]]:
    """Reserve jobs for an async Batch request so workers cannot claim them."""
    initialise()
    active_batch_job_ids = (
        select(analysis_batch_items.c.job_id)
        .join(analysis_batches, analysis_batches.c.id == analysis_batch_items.c.batch_id)
        .where(analysis_batches.c.status.in_(["validating", "in_progress", "finalizing"]))
    )
    previously_submitted_job_ids = select(analysis_batch_items.c.job_id)
    with _engine(database_url()).begin() as connection:
        rows = connection.execute(
            select(jobs)
            .where(
                jobs.c.experience_eligible.is_(True),
                jobs.c.analysis_status.in_(["pending", "retry_requested"]),
                jobs.c.user_status.in_(["new", "saved", "resume_generated"]),
                jobs.c.applied.is_(False), jobs.c.deleted_at.is_(None),
                ~jobs.c.id.in_(active_batch_job_ids),
                # An existing batch record is a durable cost-control boundary.
                # Only the explicit Retry analysis action may override it.
                (jobs.c.analysis_status == "retry_requested") | ~jobs.c.id.in_(previously_submitted_job_ids),
            )
            .order_by(jobs.c.created_at).limit(limit).with_for_update(skip_locked=True)
        ).mappings().all()
        for row in rows:
            connection.execute(update(jobs).where(jobs.c.id == row["id"]).values(
                analysis_status="batch_submitted", updated_at=_now()))
    return [_serialize(row, include_description=True) for row in rows]


def release_batch_jobs(job_ids: list[str], error: str | None = None) -> None:
    if not job_ids:
        return
    with _engine(database_url()).begin() as connection:
        connection.execute(update(jobs).where(jobs.c.id.in_(job_ids), jobs.c.analysis_status == "batch_submitted").values(
            analysis_status="pending", analysis_error=error, updated_at=_now()))


def batch_item_custom_id(batch_id: str, job_id: str) -> str:
    """Create an OpenAI Batch custom ID unique to this submission."""
    return f"batch-{batch_id}-job-{job_id}"


def record_analysis_batch(
    provider_batch_id: str,
    input_file_id: str,
    job_ids: list[str],
    batch_id: str | None = None,
    custom_ids: dict[str, str] | None = None,
    content_hashes: dict[str, str] | None = None,
) -> str:
    initialise()
    batch_id = batch_id or str(uuid4())
    with _engine(database_url()).begin() as connection:
        connection.execute(insert(analysis_batches).values(id=batch_id, provider_batch_id=provider_batch_id,
            input_file_id=input_file_id, status="validating", created_at=_now(), updated_at=_now()))
        connection.execute(insert(analysis_batch_items), [
            {
                "batch_id": batch_id,
                "job_id": job_id,
                "custom_id": (custom_ids or {}).get(job_id, batch_item_custom_id(batch_id, job_id)),
                "content_hash": (content_hashes or {}).get(job_id),
            }
            for job_id in job_ids
        ])
    return batch_id


def active_analysis_batches() -> list[dict[str, Any]]:
    initialise()
    with _engine(database_url()).connect() as connection:
        return [dict(row) for row in connection.execute(select(analysis_batches).where(
            analysis_batches.c.status.in_(["validating", "in_progress", "finalizing"]))).mappings()]


def batch_job_ids(batch_id: str) -> dict[str, str]:
    initialise()
    with _engine(database_url()).connect() as connection:
        return {row["custom_id"]: row["job_id"] for row in connection.execute(
            select(analysis_batch_items).where(analysis_batch_items.c.batch_id == batch_id)).mappings()}


def update_analysis_batch(batch_id: str, status: str, output_file_id: str | None = None, error: str | None = None) -> None:
    values: dict[str, Any] = {"status": status, "updated_at": _now(), "error": error}
    if output_file_id:
        values["output_file_id"] = output_file_id
    with _engine(database_url()).begin() as connection:
        connection.execute(update(analysis_batches).where(analysis_batches.c.id == batch_id).values(**values))


def pending_outbox_events(limit: int) -> list[dict[str, Any]]:
    initialise()
    with _engine(database_url()).connect() as connection:
        rows = connection.execute(
            select(job_events).where(job_events.c.published_at.is_(None)).order_by(job_events.c.created_at).limit(limit)
        ).mappings()
        return [dict(row) for row in rows]


def mark_event_published(event_id: str) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(update(job_events).where(job_events.c.id == event_id).values(published_at=_now()))


def claim_queued_job(job_id: str) -> dict[str, Any] | None:
    """Claim a Kafka message exactly once at the database boundary."""
    with _engine(database_url()).begin() as connection:
        row = connection.execute(
            update(jobs)
            .where(jobs.c.id == job_id, jobs.c.analysis_status == "queued")
            .values(analysis_status="processing", updated_at=_now())
            .returning(jobs)
        ).mappings().first()
    if row:
        logger.info("Claimed Kafka job %s", job_id)
    return _serialize(row, include_description=True) if row else None


def claim_next_queued_job() -> dict[str, Any] | None:
    """Claim one queued job for the local development worker."""
    with _engine(database_url()).begin() as connection:
        job_id = connection.execute(
            select(jobs.c.id)
            .where(jobs.c.analysis_status == "queued")
            .order_by(jobs.c.updated_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if not job_id:
             return None
        row = connection.execute(
            update(jobs)
            .where(jobs.c.id == job_id, jobs.c.analysis_status == "queued")
            .values(analysis_status="processing", updated_at=_now())
            .returning(jobs)
        ).mappings().first()
    if row:
        logger.info("Claimed local job %s", job_id)
    return _serialize(row, include_description=True) if row else None


def requeue_stale_processing_jobs(max_age_seconds: int | None = None) -> int:
    """Recover jobs left in processing by an interrupted local worker."""
    if max_age_seconds is None:
        max_age_seconds = int(os.getenv("JOB_PROCESSING_LEASE_SECONDS", "600"))
    cutoff = _now() - timedelta(seconds=max_age_seconds)
    with _engine(database_url()).begin() as connection:
        result = connection.execute(
            update(jobs)
            .where(jobs.c.analysis_status == "processing", jobs.c.updated_at < cutoff)
            .values(analysis_status="queued", updated_at=_now())
        )
    if result.rowcount:
        logger.warning("Requeued %s stale processing jobs", result.rowcount)
    return result.rowcount


def save_analysis(job_id: str, analysis: dict[str, Any], expected_hash: str | None = None) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(
            update(jobs).where(jobs.c.id == job_id, jobs.c.content_hash == expected_hash if expected_hash else True).values(
                analysis_status="completed", match_score=analysis["overall_score"], match_json=analysis,
                analysis_error=None, processed_at=_now(), updated_at=_now(),
            )
        )
    logger.info("Saved analysis for job %s (score=%s)", job_id, analysis["overall_score"])


def save_analysis_error(job_id: str, error: Exception) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(
            update(jobs).where(jobs.c.id == job_id).values(
                analysis_status="failed", analysis_error=str(error), updated_at=_now()
            )
        )
    logger.error("Saved analysis failure for job %s: %s", job_id, error)


def update_user_status(job_id: str, status: str) -> bool:
    if status not in {"new", "saved", "applied", "dismissed", "deleted", "resume_generated"}:
        raise ValueError("invalid job action")
    values = {"user_status": status, "updated_at": _now()}
    if status == "applied":
        values.update(applied=True, applied_at=_now())
    if status == "deleted":
        values.update(deleted_at=_now())
    with _engine(database_url()).begin() as connection:
        result = connection.execute(
            update(jobs).where(jobs.c.id == job_id).values(**values)
        )
    return result.rowcount == 1


def mark_resume_generated(job_id: str) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(
            update(jobs).where(jobs.c.id == job_id).values(
                resume_generated_at=_now(), updated_at=_now()
            )
        )


def retry_analysis(job_id: str) -> bool:
    with _engine(database_url()).begin() as connection:
        result = connection.execute(
            update(jobs)
            .where(jobs.c.id == job_id, jobs.c.analysis_status == "failed")
            .values(analysis_status="retry_requested", analysis_error=None, updated_at=_now())
        )
    return result.rowcount == 1


def batch_item_is_current(batch_id: str, job_id: str) -> bool:
    with _engine(database_url()).connect() as connection:
        row = connection.execute(select(analysis_batch_items.c.content_hash, jobs.c.content_hash.label("current_hash"))
            .join(jobs, jobs.c.id == analysis_batch_items.c.job_id)
            .where(analysis_batch_items.c.batch_id == batch_id, jobs.c.id == job_id)).first()
    return bool(row and (row.content_hash is None or row.content_hash == row.current_hash))


def set_resume_state(job_id: str, **values: Any) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(update(jobs).where(jobs.c.id == job_id).values(**values, updated_at=_now()))


def recover_untracked_batch_reservations() -> None:
    """Do not automatically spend again after a crash during provider submission."""
    with _engine(database_url()).begin() as connection:
        tracked = select(analysis_batch_items.c.job_id)
        connection.execute(update(jobs).where(jobs.c.analysis_status == "batch_submitted", ~jobs.c.id.in_(tracked)).values(
            analysis_status="failed", analysis_error="Submission interrupted before tracking was saved. Check provider batches before retrying.", updated_at=_now()))


def delete_jobs(job_ids: list[str]) -> int:
    """Persist tombstones for a selection in one transaction."""
    initialise()
    identifiers = list(dict.fromkeys(job_ids))
    if not identifiers:
        return 0
    now = _now()
    with _engine(database_url()).begin() as connection:
        result = connection.execute(update(jobs).where(jobs.c.id.in_(identifiers), jobs.c.deleted_at.is_(None)).values(
            user_status="deleted", deleted_at=now, updated_at=now))
    return result.rowcount


def eligible_inserts_by_source(started_at: datetime, completed_at: datetime) -> dict[str, int]:
    initialise()
    with _engine(database_url()).connect() as connection:
        rows = connection.execute(select(jobs.c.source, func.count().label("count")).where(
            jobs.c.created_at >= utc(started_at), jobs.c.created_at <= utc(completed_at),
            jobs.c.experience_eligible.is_(True)).group_by(jobs.c.source))
        return {row.source: row.count for row in rows}


def _remove_jobs(connection: Any, identifiers: list[str]) -> int:
    if not identifiers:
        return 0
    rows = connection.execute(select(jobs).where(jobs.c.id.in_(identifiers))).mappings().all()
    for row in rows:
        if row["applied"] or row["deleted_at"] is not None or row["user_status"] == "dismissed":
            key = (job_tombstones.c.source == row["source"]) & (job_tombstones.c.external_job_id == row["external_job_id"])
            values = {"applied": row["applied"], "applied_at": row["applied_at"], "deleted_at": row["deleted_at"] or _now()}
            if connection.execute(select(job_tombstones.c.source).where(key)).first():
                connection.execute(update(job_tombstones).where(key).values(**values))
            else:
                connection.execute(insert(job_tombstones).values(source=row["source"], external_job_id=row["external_job_id"], **values))
    connection.execute(delete(job_events).where(job_events.c.job_id.in_(identifiers)))
    connection.execute(delete(analysis_batch_items).where(analysis_batch_items.c.job_id.in_(identifiers)))
    return connection.execute(delete(jobs).where(jobs.c.id.in_(identifiers))).rowcount


def purge_ineligible_jobs() -> int:
    """Drop rejected JDs while retaining only minimal Applied/deleted markers."""
    initialise()
    with _engine(database_url()).begin() as connection:
        identifiers = connection.execute(select(jobs.c.id).where(jobs.c.experience_eligible.is_(False))).scalars().all()
        return _remove_jobs(connection, list(identifiers))
