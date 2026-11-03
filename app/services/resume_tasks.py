"""Background resume generation with durable UI status and local artifacts."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

from app.services.job_store import get_job, set_resume_state, mark_resume_generated
from app.services.resume_generation import generate_resume

ROOT = Path(__file__).resolve().parents[2]
RESUME_ROOT = ROOT / "generated" / "resumes"
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="resume")
_lock = threading.Lock()
_active: set[str] = set()


def start_resume(job_id: str) -> dict:
    with _lock:
        if job_id in _active:
            return {"status": "generating"}
        job = get_job(job_id)
        if not job:
            raise LookupError("job not found")
        if job["analysis_status"] != "completed" or not job.get("match"):
            raise ValueError("complete job matching before generating a tailored resume")
        _active.add(job_id)
        set_resume_state(job_id, resume_status="generating", resume_error=None)

    def run():
        try:
            path = generate_resume(job["job_description"], RESUME_ROOT / job_id,
                                   match_analysis=job["match"], job_title=job["job_title"])
            current = get_job(job_id)
            if current and current["content_hash"] == job["content_hash"]:
                set_resume_state(job_id, resume_status="completed", resume_filename=path.relative_to(RESUME_ROOT / job_id).as_posix())
                mark_resume_generated(job_id)
        except Exception as error:
            current = get_job(job_id)
            if current and current["content_hash"] == job["content_hash"]:
                set_resume_state(job_id, resume_status="failed", resume_error=str(error))
        finally:
            with _lock:
                _active.discard(job_id)

    _pool.submit(run)
    return {"status": "generating"}


def recover_resume_tasks():
    from app.services.job_store import _engine, database_url, jobs
    from sqlalchemy import update
    with _engine(database_url()).begin() as connection:
        connection.execute(update(jobs).where(jobs.c.resume_status == "generating").values(
            resume_status="failed", resume_error="Generation interrupted; click Generate resume to retry."))
