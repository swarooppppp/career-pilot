"""Persistent job dashboard endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.job_store import (
    get_job,
    delete_jobs,
    list_jobs,
    mark_resume_generated,
    retry_analysis,
    update_user_status,
)
from app.services.openai_batch import poll_openai_batches, submit_pending_batch
from app.services.resume_generation import generate_resume


router = APIRouter()


class JobAction(BaseModel):
    status: str


class ProcessRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class BulkDeleteRequest(BaseModel):
    job_ids: list[str] = Field(min_length=1, max_length=1000)


@router.post("/bulk-delete")
def bulk_delete(request: BulkDeleteRequest) -> dict:
    return {"deleted": delete_jobs(request.job_ids)}


@router.get("")
def dashboard_jobs(include_ineligible: bool = False) -> dict:
    return {"jobs": list_jobs(include_ineligible=include_ineligible)}


@router.post("/process")
def process_jobs(request: ProcessRequest) -> dict:
    try:
        return submit_pending_batch(request.limit)
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/batches/poll")
def poll_batches() -> dict:
    try:
        return poll_openai_batches()
    except (ValueError, RuntimeError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.post("/{job_id}/action")
def take_action(job_id: str, action: JobAction) -> dict[str, str]:
    try:
        updated = update_user_status(job_id, action.status)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not updated:
        raise HTTPException(status_code=404, detail="job not found")
    return {"status": action.status}


@router.post("/{job_id}/retry-analysis")
def retry_job_analysis(job_id: str) -> dict[str, str]:
    if not retry_analysis(job_id):
        raise HTTPException(status_code=404, detail="failed job not found")
    return {"status": "pending"}


@router.post("/{job_id}/generate-resume", status_code=202)
def generate_job_resume(job_id: str) -> dict:
    from app.services.resume_tasks import start_resume
    try:
        return start_resume(job_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/sources/status")
def source_status() -> dict:
    from app.services.portal_scheduler import read_state
    return read_state()


@router.get("/{job_id}")
def job_details(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.delete("/{job_id}")
def delete_job(job_id: str) -> dict:
    if not update_user_status(job_id, "deleted"):
        raise HTTPException(status_code=404, detail="job not found")
    return {"status": "deleted"}
