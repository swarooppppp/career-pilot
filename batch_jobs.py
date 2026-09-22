#!/usr/bin/env python3
"""Submit eligible jobs to, or collect results from, the OpenAI Batch API."""

from __future__ import annotations

import argparse

from app.logging_utils import configure_logging
from app.services.openai_batch import poll_openai_batches, submit_pending_batch


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    submit = subcommands.add_parser("submit", help="Submit eligible pending jobs.")
    submit.add_argument("--limit", type=int, required=True)
    subcommands.add_parser("poll", help="Collect completed batch results.")
    args = parser.parse_args()
    if args.command == "submit":
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        print(submit_pending_batch(args.limit))
    else:
        print(poll_openai_batches())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
