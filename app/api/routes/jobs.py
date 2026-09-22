"""Persistent job dashboard endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.job_store import (
    get_job,
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


@router.post("/{job_id}/generate-resume")
def generate_job_resume(job_id: str) -> dict[str, str]:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["analysis_status"] != "completed" or not job.get("match"):
        raise HTTPException(status_code=422, detail="complete job matching before generating a tailored resume")
    try:
        from app.api.routes.resume import TEMP_ROOT

        output_dir = TEMP_ROOT / job_id
        pdf_path = generate_resume(
            job["job_description"], output_dir,
            match_analysis=job["match"], job_title=job["job_title"],
        )
        mark_resume_generated(job_id)
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"resume generation failed: {error}") from error
    return {
        "filename": pdf_path.name,
        "download_url": f"/api/resume/download/{job_id}/{pdf_path.name}",
    }
