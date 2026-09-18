#!/usr/bin/env python3
"""Reliably publish PostgreSQL outbox events to Kafka."""

from __future__ import annotations

import time

from app.services.job_queue import publish_outbox_events


def main() -> None:
    print("Career Pilot outbox relay is publishing pending Kafka events.")
    while True:
        try:
            publish_outbox_events()
        except Exception as error:
            # The event remains in PostgreSQL and will be retried on the next poll.
            print(f"Outbox publish retry: {error}")
        time.sleep(5)


if __name__ == "__main__":
    main()
