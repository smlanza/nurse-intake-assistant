from fastapi import APIRouter, HTTPException

from src.app.dependencies import case_repository
from src.app.models.case import CaseDocument


router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/{case_id}", response_model=CaseDocument)
async def get_case(case_id: str, createdDate: str | None = None) -> CaseDocument:
    case = await case_repository.get_by_id(case_id, created_date=createdDate)
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
