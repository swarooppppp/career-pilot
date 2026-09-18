#!/usr/bin/env python3
"""Start the local web app and asynchronous worker with one command."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import uvicorn

from sync_jobs import sync_configured_jobs


ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync-jobs",
        action="store_true",
        help="Fetch and import job sources configured in .env before starting the app",
    )
    args = parser.parse_args()
    if args.sync_jobs:
        sync_configured_jobs()

    worker = subprocess.Popen([sys.executable, str(ROOT / "local_worker.py")], cwd=ROOT)
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
    finally:
        worker.terminate()
        worker.wait(timeout=10)


if __name__ == "__main__":
    main()
