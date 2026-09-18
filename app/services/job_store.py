"""PostgreSQL persistence for normalized jobs and transactional outbox events."""

from __future__ import annotations

import hashlib
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
    Float,
    Index,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine


ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

DEFAULT_DATABASE_URL = "postgresql+psycopg://career_pilot:career_pilot@localhost:5432/career_pilot"
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
    Column("job_description", Text, nullable=False),
    Column("content_hash", String(64), nullable=False),
    Column("minimum_years_experience", Float),
    Column("experience_eligible", Boolean, nullable=False),
    Column("filter_reason", Text, nullable=False),
    Column("analysis_status", String(30), nullable=False, default="pending"),
    Column("user_status", String(30), nullable=False, default="new"),
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@lru_cache(maxsize=4)
def _engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def initialise() -> None:
    metadata.create_all(_engine(database_url()))


def extract_minimum_years(description: str) -> float | None:
    """Extract the conservative pre-Gemini YOE threshold from explicit JD wording."""
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

    # This gate runs before the LLM. Reject only when every explicit experience
    # requirement exceeds the candidate threshold, which is equivalent to using
    # the lowest requirement found. A higher skill-specific requirement may need
    # semantic interpretation, so it must not alone exclude a job at this stage.
    values = left_values + right_values
    return min(values) if values else None


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
    minimum_years = extract_minimum_years(description)
    eligible = minimum_years is None or minimum_years <= candidate_years + 1
    reason = (
        "no explicit experience requirement found"
        if minimum_years is None
        else f"requires {minimum_years:g}+ years; candidate threshold is {candidate_years + 1:g} years"
    )
    return {
        "source": source,
        "external_job_id": external_id,
        "company_name": str(raw_job.get("company") or raw_job.get("company_name") or source.title()),
        "job_title": title,
        "location": location,
        "application_url": str(raw_job.get("applyUrl") or raw_job.get("application_url") or raw_job.get("url") or ""),
        "job_description": description,
        "content_hash": _hash(description),
        "minimum_years_experience": minimum_years,
        "experience_eligible": eligible,
        "filter_reason": reason,
    }


def import_jobs(raw_jobs: Iterable[dict[str, Any]], source: str, candidate_years: float) -> dict[str, int]:
    initialise()
    counts = {"imported": 0, "updated": 0, "skipped": 0, "ineligible": 0}
    with _engine(database_url()).begin() as connection:
        for raw_job in raw_jobs:
            try:
                job = normalise_job(raw_job, source, candidate_years)
            except ValueError:
                counts["skipped"] += 1
                continue
            existing = connection.execute(
                select(jobs.c.id, jobs.c.content_hash).where(
                    jobs.c.source == job["source"], jobs.c.external_job_id == job["external_job_id"]
                )
            ).mappings().first()
            if existing and existing["content_hash"] == job["content_hash"]:
                counts["skipped"] += 1
                continue
            if not job["experience_eligible"]:
                counts["ineligible"] += 1
            if existing:
                connection.execute(
                    update(jobs).where(jobs.c.id == existing["id"]).values(
                        **job,
                        analysis_status="pending",
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
    return counts


def _serialize(row: Any, include_description: bool = False) -> dict[str, Any]:
    job = dict(row)
    job["match"] = job.pop("match_json", None)
    if not include_description:
        job.pop("job_description", None)
    return job


def list_jobs(include_ineligible: bool = False) -> list[dict[str, Any]]:
    initialise()
    statement = select(jobs).where(jobs.c.user_status != "dismissed")
    if not include_ineligible:
        statement = statement.where(jobs.c.experience_eligible.is_(True))
    statement = statement.order_by(jobs.c.match_score.desc().nulls_last(), jobs.c.created_at.desc())
    with _engine(database_url()).connect() as connection:
        return [_serialize(row) for row in connection.execute(statement).mappings()]


def get_job(job_id: str) -> dict[str, Any] | None:
    initialise()
    with _engine(database_url()).connect() as connection:
        row = connection.execute(select(jobs).where(jobs.c.id == job_id)).mappings().first()
    return _serialize(row, include_description=True) if row else None


def queue_pending_jobs(limit: int, create_outbox_events: bool = True) -> list[str]:
    """Atomically mark work queued and create outbox records in the same transaction."""
    initialise()
    with _engine(database_url()).begin() as connection:
        candidates = connection.execute(
            select(jobs.c.id)
            .where(
                jobs.c.experience_eligible.is_(True),
                jobs.c.analysis_status == "pending",
                jobs.c.user_status == "new",
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
    return list(candidates)


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
    return _serialize(row, include_description=True) if row else None


def requeue_stale_processing_jobs(max_age_seconds: int = 180) -> int:
    """Recover jobs left in processing by an interrupted local worker."""
    cutoff = _now() - timedelta(seconds=max_age_seconds)
    with _engine(database_url()).begin() as connection:
        result = connection.execute(
            update(jobs)
            .where(jobs.c.analysis_status == "processing", jobs.c.updated_at < cutoff)
            .values(analysis_status="queued", updated_at=_now())
        )
    return result.rowcount


def save_analysis(job_id: str, analysis: dict[str, Any]) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(
            update(jobs).where(jobs.c.id == job_id).values(
                analysis_status="completed", match_score=analysis["overall_score"], match_json=analysis,
                analysis_error=None, processed_at=_now(), updated_at=_now(),
            )
        )


def save_analysis_error(job_id: str, error: Exception) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(
            update(jobs).where(jobs.c.id == job_id).values(
                analysis_status="failed", analysis_error=str(error), updated_at=_now()
            )
        )


def update_user_status(job_id: str, status: str) -> bool:
    if status not in {"new", "saved", "applied", "dismissed", "resume_generated"}:
        raise ValueError("invalid job action")
    with _engine(database_url()).begin() as connection:
        result = connection.execute(
            update(jobs).where(jobs.c.id == job_id).values(user_status=status, updated_at=_now())
        )
    return result.rowcount == 1


def mark_resume_generated(job_id: str) -> None:
    with _engine(database_url()).begin() as connection:
        connection.execute(
            update(jobs).where(jobs.c.id == job_id).values(
                user_status="resume_generated", resume_generated_at=_now(), updated_at=_now()
            )
        )


def retry_analysis(job_id: str) -> bool:
    with _engine(database_url()).begin() as connection:
        result = connection.execute(
            update(jobs)
            .where(jobs.c.id == job_id, jobs.c.analysis_status == "failed")
            .values(analysis_status="pending", analysis_error=None, updated_at=_now())
        )
    return result.rowcount == 1
