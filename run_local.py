#!/usr/bin/env python3
"""Start the local web app and asynchronous worker with one command."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
from pathlib import Path

import uvicorn

from app.logging_utils import configure_logging
from sync_jobs import sync_configured_jobs


ROOT = Path(__file__).resolve().parent


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sync-jobs",
        action="store_true",
        help="Fetch and import job sources configured in .env before starting the app",
    )
    args = parser.parse_args()
    if args.sync_jobs:
        print("[startup] Fetching and importing configured job sources in the background...")
        # A third-party career site can temporarily block one adapter. Import
        # the healthy sources and start the personal app instead of making the
        # whole local workflow unavailable.
        threading.Thread(
            target=sync_configured_jobs,
            kwargs={"strict": False},
            name="portal-sync",
            daemon=True,
        ).start()

    worker = None
    if os.getenv("MATCH_EXECUTION_MODE", "batch").lower() == "worker":
        print("[startup] Starting legacy local worker...")
        worker = subprocess.Popen([sys.executable, str(ROOT / "local_worker.py")], cwd=ROOT)
    else:
        print("[startup] Job matching uses the in-app OpenAI Batch scheduler.")
    try:
        print("[startup] Starting web application at http://127.0.0.1:8000")
        uvicorn.run("app.main:app", host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")), reload=False)
    finally:
        if worker:
            print("[shutdown] Stopping local worker...")
            worker.terminate()
            worker.wait(timeout=10)


if __name__ == "__main__":
    main()
