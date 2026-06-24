from fastapi import APIRouter, HTTPException

from src.app.dependencies import case_repository
from src.app.models.case import CaseDocument
from src.app.services.cosmos_case_repository import MissingCasePartitionKeyError


router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("/{case_id}", response_model=CaseDocument)
async def get_case(case_id: str, createdDate: str | None = None) -> CaseDocument:
    try:
        case = await case_repository.get_by_id(case_id, created_date=createdDate)
    except MissingCasePartitionKeyError as error:
        raise HTTPException(
            status_code=400,
            detail="createdDate is required for Cosmos-backed case lookup.",
        ) from error
    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return case
