"""Master-experience editor endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.job_matching import MASTER_EXPERIENCE, candidate_profile


router = APIRouter()


class MasterExperienceUpdate(BaseModel):
    content: str = Field(..., min_length=100, max_length=200_000)


@router.get("/master-experience")
def get_master_experience() -> dict[str, str]:
    return {"content": MASTER_EXPERIENCE.read_text(encoding="utf-8")}


@router.put("/master-experience")
def update_master_experience(update: MasterExperienceUpdate) -> dict[str, str]:
    try:
        MASTER_EXPERIENCE.write_text(update.content.strip() + "\n", encoding="utf-8")
        candidate_profile.cache_clear()
    except OSError as error:
        raise HTTPException(status_code=500, detail=f"could not update master experience: {error}") from error
    return {"status": "saved"}
