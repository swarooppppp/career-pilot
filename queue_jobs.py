#!/usr/bin/env python3
"""Queue a bounded batch of eligible jobs for local or Kafka matching workers."""

from __future__ import annotations

import argparse

from app.logging_utils import configure_logging
from app.services.job_queue import publish_outbox_events, queue_backend
from app.services.job_store import queue_pending_jobs


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, required=True, help="Number of eligible pending jobs to queue.")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be at least 1")
    backend = queue_backend()
    queued = queue_pending_jobs(args.limit, create_outbox_events=backend == "kafka")
    published = publish_outbox_events(limit=args.limit) if backend == "kafka" else 0
    print(f"Queued {len(queued)} jobs ({published} Kafka events published; backend={backend}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
