from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from src.app.dependencies import case_repository
from src.app.models.case import CaseDocument, ReviewStatus, Urgency
from src.app.models.review import CaseReviewRequest
from src.app.services.cosmos_case_repository import (
    CaseListNotSupportedError,
    MissingCasePartitionKeyError,
)


router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseDocument])
async def list_cases(
    reviewStatus: ReviewStatus | None = None,
    urgency: Urgency | None = None,
) -> list[CaseDocument]:
    try:
        return await case_repository.list_cases(
            review_status=reviewStatus,
            urgency=urgency,
        )
    except (CaseListNotSupportedError, NotImplementedError) as error:
        raise HTTPException(
            status_code=501,
            detail="Case list queries are not implemented for this repository.",
        ) from error


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


@router.post("/{case_id}/review", response_model=CaseDocument)
async def review_case(
    case_id: str,
    request: CaseReviewRequest,
    createdDate: str | None = None,
) -> CaseDocument:
    try:
        case = await case_repository.get_by_id(case_id, created_date=createdDate)
    except MissingCasePartitionKeyError as error:
        raise HTTPException(
            status_code=400,
            detail="createdDate is required for Cosmos-backed case lookup.",
        ) from error

    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    now = datetime.now(timezone.utc)
    case.reviewStatus = "Reviewed"
    case.reviewedBy = request.reviewedBy
    case.reviewNotes = request.reviewNotes
    case.reviewedAt = now
    case.lastStatusUpdatedUtc = now

    return await case_repository.save(case)
