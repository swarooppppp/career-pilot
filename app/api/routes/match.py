"""Candidate-to-job match analysis endpoint."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.job_matching import analyse_job


router = APIRouter()


class MatchRequest(BaseModel):
    job_description: str = Field(..., min_length=20, max_length=50_000)


@router.post("/analyze")
def analyse_match(request: MatchRequest) -> dict:
    try:
        return analyse_job(request.job_description)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"match analysis failed: {error}") from error
