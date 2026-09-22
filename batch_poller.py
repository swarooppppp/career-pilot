#!/usr/bin/env python3
"""Periodically collect completed OpenAI job-match batches."""

from __future__ import annotations

import logging
import os
import time

from dotenv import load_dotenv

from app.logging_utils import configure_logging
from app.services.openai_batch import poll_openai_batches


def poll_interval_seconds() -> int:
    value = int(os.getenv("OPENAI_BATCH_POLL_INTERVAL_MINUTES", "5")) * 60
    if value < 60:
        raise ValueError("OPENAI_BATCH_POLL_INTERVAL_MINUTES must be at least 1")
    return value


def main() -> int:
    load_dotenv()
    configure_logging()
    logger = logging.getLogger(__name__)
    interval = poll_interval_seconds()
    logger.info("OpenAI Batch poller started; checking every %s seconds", interval)
    while True:
        try:
            logger.info("Polling active OpenAI batches")
            logger.info("OpenAI batch poll result: %s", poll_openai_batches())
        except Exception:
            logger.exception("OpenAI Batch polling failed; will retry on the next interval")
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
