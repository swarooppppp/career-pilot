"""Local process scheduler for periodic OpenAI Batch submission and polling."""

from __future__ import annotations

import logging
import os
import threading

from app.services.openai_batch import poll_openai_batches, submit_pending_batch


logger = logging.getLogger(__name__)


def _positive_minutes(name: str, default: int) -> float:
    value = float(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _submission_enabled() -> bool:
    return os.getenv("OPENAI_BATCH_SUBMISSION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def start_batch_scheduler() -> threading.Event:
    """Start one local scheduler; FastAPI stops it during shutdown."""
    submit_seconds = _positive_minutes("OPENAI_BATCH_SUBMIT_INTERVAL_MINUTES", 60) * 60
    poll_seconds = _positive_minutes("OPENAI_BATCH_POLL_INTERVAL_MINUTES", 5) * 60
    submit_limit = int(os.getenv("OPENAI_BATCH_SUBMIT_LIMIT", "100"))
    if submit_limit < 1:
        raise ValueError("OPENAI_BATCH_SUBMIT_LIMIT must be at least 1")
    submission_enabled = _submission_enabled()
    stop = threading.Event()

    def run() -> None:
        # Submit and poll once on startup, then repeat at the configured intervals.
        next_poll = 0.0
        next_submit = 0.0 if submission_enabled else float("inf")
        elapsed = 0.0
        while not stop.is_set():
            if elapsed >= next_poll:
                try:
                    logger.info("Polling active OpenAI batches")
                    poll_openai_batches()
                except Exception:
                    logger.exception("OpenAI Batch polling failed; will retry on the next interval")
                next_poll = elapsed + poll_seconds
            if submission_enabled and elapsed >= next_submit:
                try:
                    logger.info("Submitting scheduled OpenAI batch (limit=%s)", submit_limit)
                    submit_pending_batch(submit_limit)
                except Exception:
                    logger.exception("OpenAI Batch submission failed; will retry on the next interval")
                next_submit = elapsed + submit_seconds
            wait_for = max(0.1, min(next_poll, next_submit) - elapsed)
            stop.wait(wait_for)
            elapsed += wait_for

    thread = threading.Thread(target=run, name="openai-batch-scheduler", daemon=True)
    thread.start()
    logger.info(
        "OpenAI Batch scheduler started (submission %s; poll every %sm)",
        "enabled" if submission_enabled else "paused", poll_seconds / 60,
    )
    return stop
