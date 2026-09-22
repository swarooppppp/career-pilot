"""Quota coordination for Gemini calls made by local and cloud workers."""

from __future__ import annotations

import os
import logging
import threading
import time
from collections import deque
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.services.job_store import (
    _engine,
    _now,
    database_url,
    gemini_rate_locks,
    gemini_request_slots,
    initialise,
)


WINDOW_SECONDS = 60.0
logger = logging.getLogger(__name__)
_local_lock = threading.Lock()
_local_slots: deque[float] = deque()


def requests_per_minute() -> int:
    value = int(os.getenv("GEMINI_REQUESTS_PER_MINUTE", "20"))
    if value < 1:
        raise ValueError("GEMINI_REQUESTS_PER_MINUTE must be at least 1")
    return value


def _acquire_local(limit: int) -> None:
    """Coordinate all threads in the local worker process with a rolling window."""
    while True:
        with _local_lock:
            now = time.monotonic()
            while _local_slots and _local_slots[0] <= now - WINDOW_SECONDS:
                _local_slots.popleft()
            if len(_local_slots) < limit:
                _local_slots.append(now)
                logger.info("Gemini quota slot granted locally (%s/%s in last minute)", len(_local_slots), limit)
                return
            wait_seconds = max(0.01, _local_slots[0] + WINDOW_SECONDS - now)
        logger.info("Gemini local quota full; waiting %.2fs", wait_seconds)
        time.sleep(wait_seconds)


def _ensure_cloud_lock(connection: object) -> None:
    try:
        with connection.begin_nested():
            connection.execute(insert(gemini_rate_locks).values(id="global"))
    except IntegrityError:
        # Another worker created the singleton row first.
        pass


def _cloud_wait_seconds(limit: int) -> float:
    """Create one PostgreSQL-backed rate slot, or return time until capacity."""
    initialise()
    with _engine(database_url()).begin() as connection:
        _ensure_cloud_lock(connection)
        connection.execute(select(gemini_rate_locks.c.id).where(gemini_rate_locks.c.id == "global").with_for_update())
        cutoff = _now() - timedelta(seconds=WINDOW_SECONDS)
        connection.execute(delete(gemini_request_slots).where(gemini_request_slots.c.created_at <= cutoff))
        used = connection.execute(select(func.count()).select_from(gemini_request_slots)).scalar_one()
        if used < limit:
            connection.execute(insert(gemini_request_slots).values(id=str(uuid4()), created_at=_now()))
            logger.info("Gemini quota slot granted in PostgreSQL (%s/%s in last minute)", used + 1, limit)
            return 0.0
        oldest = connection.execute(select(func.min(gemini_request_slots.c.created_at))).scalar_one()
        return max(0.01, (oldest + timedelta(seconds=WINDOW_SECONDS) - _now()).total_seconds())


def acquire_gemini_slot() -> None:
    """Block until this process has permission to make one Gemini request."""
    limit = requests_per_minute()
    if database_url().startswith("sqlite"):
        _acquire_local(limit)
        return
    while True:
        wait_seconds = _cloud_wait_seconds(limit)
        if not wait_seconds:
            return
        logger.info("Gemini shared quota full; waiting %.2fs", wait_seconds)
        time.sleep(wait_seconds)
