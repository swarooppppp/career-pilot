"""Resume generation and download endpoints."""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.services.email_delivery import send_resume_email
from app.services.resume_generation import generate_resume


TEMP_ROOT = Path(tempfile.gettempdir()) / "career-pilot-resumes"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)

router = APIRouter()


class ResumeRequest(BaseModel):
    job_description: str = Field(..., min_length=20, max_length=50_000)


@router.post("/generate")
def generate_resume_endpoint(request: ResumeRequest) -> dict[str, str]:
    job_directory = TEMP_ROOT / uuid4().hex
    try:
        pdf_path = generate_resume(request.job_description, job_directory)
        emailed = send_resume_email(pdf_path)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error

    return {
        "status": "completed",
        "filename": pdf_path.name,
        "download_url": f"/api/resume/download/{job_directory.name}/{pdf_path.name}",
        "email_status": "sent" if emailed else "not_configured",
    }


@router.get("/download/{job_id}/{filename}")
def download_resume(job_id: str, filename: str) -> FileResponse:
    if Path(filename).name != filename or not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="invalid PDF filename")
    pdf_path = TEMP_ROOT / job_id / filename
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="resume not found")
    return FileResponse(pdf_path, media_type="application/pdf", filename=filename)
