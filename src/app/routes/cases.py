from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from src.app.dependencies import case_repository
from src.app.models.case import CaseDocument, CaseQueueSummary, ReviewStatus, Urgency
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
    fromDate: date | None = None,
    toDate: date | None = None,
    limit: Annotated[int | None, Query(gt=0, le=100)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CaseDocument]:
    _validate_date_range(fromDate, toDate)

    try:
        cases = await case_repository.list_cases(
            review_status=reviewStatus,
            urgency=urgency,
            from_date=fromDate,
            to_date=toDate,
        )
    except (CaseListNotSupportedError, NotImplementedError) as error:
        raise HTTPException(
            status_code=501,
            detail="Case list queries are not implemented for this repository.",
        ) from error

    cases = cases[offset:]
    if limit is not None:
        cases = cases[:limit]
    return cases


@router.get("/summary", response_model=CaseQueueSummary)
async def get_case_summary(
    fromDate: date | None = None,
    toDate: date | None = None,
) -> CaseQueueSummary:
    _validate_date_range(fromDate, toDate)

    try:
        cases = await case_repository.list_cases(
            from_date=fromDate,
            to_date=toDate,
        )
    except (CaseListNotSupportedError, NotImplementedError) as error:
        raise HTTPException(
            status_code=501,
            detail="Case summary queries are not implemented for this repository.",
        ) from error

    return CaseQueueSummary(
        total=len(cases),
        pendingReview=sum(case.reviewStatus == "PendingReview" for case in cases),
        reviewed=sum(case.reviewStatus == "Reviewed" for case in cases),
        urgent=sum(case.urgency == "Urgent" for case in cases),
        routine=sum(case.urgency == "Routine" for case in cases),
        pendingUrgent=sum(
            case.reviewStatus == "PendingReview" and case.urgency == "Urgent"
            for case in cases
        ),
    )


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


def _validate_date_range(
    from_date: date | None,
    to_date: date | None,
) -> None:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=400,
            detail="fromDate must be on or before toDate.",
        )
