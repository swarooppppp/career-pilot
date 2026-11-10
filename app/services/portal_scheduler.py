"""Durable local calendar scheduling and isolated parallel portal imports."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from local_career_portals.runtime_support import FileLock
import json
import logging
import os
from pathlib import Path
import sys
import threading
from zoneinfo import ZoneInfo

from app.services.candidate_experience import experience_years_for_import
from app.services.job_store import import_jobs, initialise

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "data" / "portal_schedule.json"
ZONE = ZoneInfo("Asia/Kolkata")
HOURS = (7, 10, 13, 16, 19, 22)
logger = logging.getLogger(__name__)


def latest_slot(now: datetime) -> datetime:
    local = now.astimezone(ZONE)
    slots = [local.replace(hour=h, minute=0, second=0, microsecond=0) for h in HOURS]
    return max([s for s in slots if s <= local] or [slots[-1] - timedelta(days=1)])


def read_state() -> dict:
    try:
        return collection_statistics(json.loads(STATE.read_text()))
    except FileNotFoundError:
        return {"sources": {}}


def collection_statistics(state: dict) -> dict:
    """Count committed inserts only; updates and repeats are not new jobs."""
    sources = state.get("sources", {})
    total = 0
    eligible_total = 0
    legacy_counts = {}
    if state.get("started_at") and any("new_eligible_jobs" not in source and "imported_eligible" not in source.get("import", {}) for source in sources.values()):
        from app.services.job_store import eligible_inserts_by_source
        legacy_counts = eligible_inserts_by_source(datetime.fromisoformat(state["started_at"]), datetime.fromisoformat(state["completed_at"]) if state.get("completed_at") else datetime.now(ZONE))
    for slug, source in sources.items():
        source["new_jobs"] = source.get("new_jobs", source.get("import", {}).get("imported", 0))
        total += source["new_jobs"]
        source["new_eligible_jobs"] = source.get("new_eligible_jobs", source.get("import", {}).get("imported_eligible", legacy_counts.get(slug, 0)))
        eligible_total += source["new_eligible_jobs"]
    state["statistics"] = {
        "new_jobs_total": total,
        "new_eligible_jobs_total": eligible_total,
        "companies_completed": sum(source.get("status") != "queued" for source in sources.values()),
        "companies_total": len(sources),
    }
    return state


def write_state(state: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(STATE)


_stop_event = threading.Event()


def _acquire_collection_lock():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(STATE.with_suffix(".lock"))
    return lock if lock.acquire() else None


def collection_is_running() -> bool:
    lock = _acquire_collection_lock()
    if lock is None:
        return True
    lock.close()
    return False


def collect(slot: datetime, stop: threading.Event) -> bool:
    lock = _acquire_collection_lock()
    if lock is None:
        return False
    with lock:
        return _collect_locked(slot, stop)


def trigger_manual_collection() -> bool:
    """Reserve the shared OS lock before accepting a background collection."""
    lock = _acquire_collection_lock()
    if lock is None:
        return False

    def run():
        with lock:
            try:
                _collect_locked(latest_slot(datetime.now(ZONE)), _stop_event, manual=True)
            except Exception as error:
                logger.exception("Manual portal collection failed")
                state = read_state()
                state.update(status="failed", trigger="manual", error=str(error), completed_at=datetime.now(ZONE).isoformat())
                write_state(state)

    try:
        threading.Thread(target=run, name="manual-portal-collection", daemon=True).start()
    except Exception:
        lock.close()
        raise
    return True


def _collect_locked(slot: datetime, stop: threading.Event, manual: bool = False) -> bool:
    state = read_state()
    if not manual and state.get("last_slot", "") >= slot.isoformat() and state.get("status") != "running":
        return False
    # Keep committed counts when recovering an interrupted run in the same slot.
    recovering = not manual and state.get("trigger") != "manual" and state.get("status") == "running" and state.get("last_slot") == slot.isoformat()
    previous_sources = state.get("sources", {})
    started = datetime.now(ZONE).isoformat()
    state.update(status="running", started_at=started, trigger="manual" if manual else "scheduled", run_at=started if manual else slot.isoformat())
    state.pop("error", None)
    if not manual:
        state["last_slot"] = slot.isoformat()
    write_state(state)
    initialise()
    portal_path = str(ROOT / "local_career_portals")
    if portal_path not in sys.path:
        sys.path.insert(0, portal_path)
    from sample_all import fetch
    inventory = json.loads((Path(portal_path) / "companies.json").read_text())
    companies = [c for c in inventory["companies"] if c["status"] in {"reuse", "implemented"}]
    if not recovering:
        state["sources"] = {c["slug"]: {"company": c.get("company", c["slug"]), "status": "queued", "new_jobs": 0, "new_eligible_jobs": 0,
            "last_success_at": previous_sources.get(c["slug"], {}).get("last_success_at")} for c in companies}
        state.pop("completed_at", None)
    write_state(state)
    directory = ROOT / "local_career_portals" / "data" / "scheduled" / datetime.now(ZONE).strftime("%Y%m%d_%H%M%S_%f")
    directory.mkdir(parents=True)
    profile = ROOT / "data" / "master_experience.md"
    years = experience_years_for_import(profile.read_text() if profile.exists() else "", float(os.getenv("CANDIDATE_YEARS_EXPERIENCE", "0")))
    workers = max(1, int(os.getenv("PORTAL_WORKERS", "3")))
    timeout = max(1, int(os.getenv("PORTAL_SOURCE_TIMEOUT", "600")))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, c, directory, 50, timeout): c for c in companies}
        for future in as_completed(futures):
            company = futures[future]
            previous = state["sources"].get(company["slug"], {})
            try:
                result = future.result()
                if result["status"] in {"ok", "empty", "partial"}:
                    result["import"] = import_jobs(result["jobs"], company["slug"], years)
                result["new_jobs"] = previous.get("new_jobs", 0) + result.get("import", {}).get("imported", 0)
                result["new_eligible_jobs"] = previous.get("new_eligible_jobs", 0) + result.get("import", {}).get("imported_eligible", 0)
                if result["status"] in {"ok", "empty"}:
                    result["last_success_at"] = datetime.now(ZONE).isoformat()
                else:
                    result["last_success_at"] = previous.get("last_success_at")
                result.pop("jobs", None)
                state["sources"][company["slug"]] = result
            except Exception as error:
                logger.exception("Source import failed: %s", company["slug"])
                state["sources"][company["slug"]] = {"status": "failed", "error": str(error), "new_jobs": previous.get("new_jobs", 0), "new_eligible_jobs": previous.get("new_eligible_jobs", 0), "last_success_at": previous.get("last_success_at")}
            write_state(state)
            if stop.is_set():
                for pending in futures:
                    pending.cancel()
    state.update(status="complete", completed_at=datetime.now(ZONE).isoformat())
    write_state(state)
    if any(source.get("import", {}).get("imported_eligible", 0) or source.get("import", {}).get("updated", 0) for source in state["sources"].values()):
        from app.services.batch_scheduler import notify_matching_work
        notify_matching_work()
    return True


def start_portal_scheduler() -> threading.Event:
    global _stop_event
    stop = _stop_event = threading.Event()
    if os.getenv("PORTAL_SCHEDULER_ENABLED", "false").lower() not in {"true", "1", "yes"}:
        return stop

    def run():
        while not stop.is_set():
            try:
                collect(latest_slot(datetime.now(ZONE)), stop)
            except Exception:
                logger.exception("Portal scheduling failed; retrying in one minute")
            stop.wait(60)

    threading.Thread(target=run, name="portal-scheduler", daemon=True).start()
    return stop
