"""Local process scheduler for periodic OpenAI Batch submission and polling."""

from __future__ import annotations

import logging
import os
import threading
import time

from app.services.openai_batch import poll_openai_batches, submit_pending_batch


logger = logging.getLogger(__name__)


def _positive_minutes(name: str, default: int) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _submission_enabled() -> bool:
    return os.getenv("OPENAI_BATCH_SUBMISSION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def submit_waiting_batches(limit: int, stop: threading.Event) -> dict[str, int]:
    """Drain eligible pending work in chunks; empty queues make no API call."""
    totals = {"batches": 0, "jobs": 0}
    while not stop.is_set():
        result = submit_pending_batch(limit)
        submitted = result["submitted"]
        if submitted:
            totals["batches"] += 1
            totals["jobs"] += submitted
        if submitted < limit:
            break
    return totals


_work_available = threading.Event()


def notify_matching_work() -> None:
    """Wake the submitter after committed collection results or explicit retries."""
    _work_available.set()


class SchedulerStop(threading.Event):
    def set(self) -> None:
        super().set()
        _work_available.set()


def start_batch_scheduler() -> threading.Event:
    """Submit on new work; reconcile queues and poll results hourly."""
    submit_seconds = _positive_minutes("OPENAI_BATCH_SUBMIT_INTERVAL_MINUTES", 60) * 60
    poll_seconds = _positive_minutes("OPENAI_BATCH_POLL_INTERVAL_MINUTES", 60) * 60
    submit_limit = int(os.getenv("OPENAI_BATCH_SUBMIT_LIMIT", "100"))
    if submit_limit < 1:
        raise ValueError("OPENAI_BATCH_SUBMIT_LIMIT must be at least 1")
    submission_enabled = _submission_enabled()
    stop = SchedulerStop()

    def run() -> None:
        next_poll = 0.0
        next_submit = 0.0 if submission_enabled else float("inf")
        while not stop.is_set():
            notified = _work_available.is_set()
            if notified:
                _work_available.clear()
            now = time.monotonic()
            if now >= next_poll:
                try:
                    poll_openai_batches()
                except Exception:
                    logger.exception("OpenAI Batch polling failed; will retry on the next interval")
                next_poll = time.monotonic() + poll_seconds
            if submission_enabled and (notified or now >= next_submit):
                try:
                    submit_waiting_batches(submit_limit, stop)
                except Exception:
                    logger.exception("OpenAI Batch submission failed; pending jobs retained for retry")
                next_submit = time.monotonic() + submit_seconds
            wait_for = max(0.1, min(next_poll, next_submit) - time.monotonic())
            _work_available.wait(wait_for)

    stop.thread = threading.Thread(target=run, name="openai-batch-scheduler", daemon=True)
    stop.thread.start()
    logger.info(
        "OpenAI Batch scheduler started (submission %s; new-work notifications; queue check every %sm; results check every %sm; batch size %s)",
        "enabled" if submission_enabled else "paused", submit_seconds / 60, poll_seconds / 60, submit_limit,
    )
    return stop
