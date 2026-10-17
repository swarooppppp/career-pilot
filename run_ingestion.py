#!/usr/bin/env python3
"""Run one configured job ingestion cycle for a scheduler."""

from app.logging_utils import configure_logging
from sync_jobs import sync_configured_jobs


if __name__ == "__main__":
    configure_logging()
    sync_configured_jobs(strict=False)
