from datetime import date, datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from src.app.dependencies import case_repository
from src.app.models.case import (
    CaseDocument,
    CaseHandoffNoteResponse,
    CaseQueueSummary,
    IntakeStatus,
    ReviewStatus,
    Urgency,
)
from src.app.models.review import CaseReviewRequest
from src.app.services.cosmos_case_repository import (
    CaseListNotSupportedError,
    MissingCasePartitionKeyError,
)
from src.app.services.nurse_handoff_note_formatter import NurseHandoffNoteFormatter


router = APIRouter(prefix="/cases", tags=["cases"])
handoff_note_formatter = NurseHandoffNoteFormatter()
HANDOFF_NOTE_OPENAPI_EXAMPLE = {
    "caseId": "demo-case-001",
    "createdDate": "2026-06-30",
    "noteFormat": "plainText",
    "handoffNote": (
        "DEMO ONLY - Not for production clinical use. AI-assisted output "
        "requires nurse review.\n\n"
        "Case metadata\n"
        "- Case ID: demo-case-001\n"
        "- Created date: 2026-06-30\n"
        "- Source/channel: local-demo-ui / text-intake\n"
        "- Intake status: Complete\n"
        "- Review status: PendingReview\n\n"
        "Patient Summary\n"
        "- Patient name: Demo Patient\n"
        "- Callback number: demo-callback-001\n"
        "- Main concern: medication refill\n"
        "- Summary: Demo patient requests medication refill.\n\n"
        "Reported Symptoms\n"
        "- Symptoms: None recorded\n\n"
        "Red Flags\n"
        "- Red flag rationale: None recorded\n\n"
        "Recommended Nurse Review Priority\n"
        "- Urgency level: Routine\n\n"
        "Notification Status\n"
        "- Email status: MockRecorded\n"
        "- SMS status: MockRecorded\n\n"
        "Nurse review\n"
        "- Not yet reviewed"
    ),
}


@router.get("", response_model=list[CaseDocument])
async def list_cases(
    reviewStatus: Annotated[
        ReviewStatus | None,
        Query(description="Filter by nurse review status, such as PendingReview."),
    ] = None,
    urgency: Annotated[
        Urgency | None,
        Query(description="Filter by urgency classification, such as Urgent."),
    ] = None,
    intakeStatus: Annotated[
        IntakeStatus | None,
        Query(description="Filter by intake completion status, such as NeedsFollowUp."),
    ] = None,
    intakeComplete: Annotated[
        bool | None,
        Query(description="Filter by whether all required intake fields are present."),
    ] = None,
    sourceSystem: Annotated[
        str | None,
        Query(
            description=(
                "Filter by source system metadata, for example local or "
                "voicemail-transcript. Blank values are ignored."
            )
        ),
    ] = None,
    caseType: Annotated[
        str | None,
        Query(
            description=(
                "Filter by case type, for example text-intake or phone-intake. "
                "Blank values are ignored."
            )
        ),
    ] = None,
    notificationEmailStatus: Annotated[
        str | None,
        Query(
            description=(
                "Filter by email notification status, such as MockRecorded, "
                "Accepted, Failed, or Suppressed. Blank values are ignored."
            )
        ),
    ] = None,
    notificationSmsStatus: Annotated[
        str | None,
        Query(
            description=(
                "Filter by SMS notification status, such as MockRecorded, "
                "Accepted, Failed, or Suppressed. Blank values are ignored."
            )
        ),
    ] = None,
    notificationSmsDeliveryConfirmed: Annotated[
        bool | None,
        Query(description="Filter by whether SMS delivery has been confirmed."),
    ] = None,
    fromDate: Annotated[
        date | None,
        Query(description="Include cases created on or after this date."),
    ] = None,
    toDate: Annotated[
        date | None,
        Query(description="Include cases created on or before this date."),
    ] = None,
    limit: Annotated[
        int | None,
        Query(
            gt=0,
            le=100,
            description="Maximum number of cases to return after filtering.",
        ),
    ] = None,
    offset: Annotated[
        int,
        Query(
            ge=0,
            description="Number of filtered, sorted cases to skip before returning.",
        ),
    ] = 0,
) -> list[CaseDocument]:
    _validate_date_range(fromDate, toDate)

    try:
        cases = await case_repository.list_cases(
            review_status=reviewStatus,
            urgency=urgency,
            intake_status=intakeStatus,
            intake_complete=intakeComplete,
            source_system=_clean_optional_query_filter(sourceSystem),
            case_type=_clean_optional_query_filter(caseType),
            notification_email_status=_clean_optional_query_filter(
                notificationEmailStatus
            ),
            notification_sms_status=_clean_optional_query_filter(
                notificationSmsStatus
            ),
            notification_sms_delivery_confirmed=notificationSmsDeliveryConfirmed,
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
    sourceSystem: Annotated[
        str | None,
        Query(
            description=(
                "Filter summary counts by source system metadata, for example "
                "local or voicemail-transcript. Blank values are ignored."
            )
        ),
    ] = None,
    caseType: Annotated[
        str | None,
        Query(
            description=(
                "Filter summary counts by case type, for example text-intake or "
                "phone-intake. Blank values are ignored."
            )
        ),
    ] = None,
    notificationEmailStatus: Annotated[
        str | None,
        Query(
            description=(
                "Filter summary counts by email notification status, such as "
                "MockRecorded, Accepted, Failed, or Suppressed."
            )
        ),
    ] = None,
    notificationSmsStatus: Annotated[
        str | None,
        Query(
            description=(
                "Filter summary counts by SMS notification status, such as "
                "MockRecorded, Accepted, Failed, or Suppressed."
            )
        ),
    ] = None,
    notificationSmsDeliveryConfirmed: Annotated[
        bool | None,
        Query(description="Filter summary counts by SMS delivery confirmation."),
    ] = None,
    fromDate: Annotated[
        date | None,
        Query(description="Include cases created on or after this date in counts."),
    ] = None,
    toDate: Annotated[
        date | None,
        Query(description="Include cases created on or before this date in counts."),
    ] = None,
) -> CaseQueueSummary:
    _validate_date_range(fromDate, toDate)

    try:
        cases = await case_repository.list_cases(
            source_system=_clean_optional_query_filter(sourceSystem),
            case_type=_clean_optional_query_filter(caseType),
            notification_email_status=_clean_optional_query_filter(
                notificationEmailStatus
            ),
            notification_sms_status=_clean_optional_query_filter(
                notificationSmsStatus
            ),
            notification_sms_delivery_confirmed=notificationSmsDeliveryConfirmed,
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
        completeIntakes=sum(case.intakeComplete for case in cases),
        needsFollowUpIntakes=sum(not case.intakeComplete for case in cases),
        emailMockRecorded=sum(
            case.notificationEmailStatus == "MockRecorded" for case in cases
        ),
        emailAccepted=sum(case.notificationEmailStatus == "Accepted" for case in cases),
        emailFailed=sum(case.notificationEmailStatus == "Failed" for case in cases),
        emailSuppressed=sum(
            case.notificationEmailStatus == "Suppressed" for case in cases
        ),
        smsMockRecorded=sum(
            case.notificationSmsStatus == "MockRecorded" for case in cases
        ),
        smsAccepted=sum(case.notificationSmsStatus == "Accepted" for case in cases),
        smsFailed=sum(case.notificationSmsStatus == "Failed" for case in cases),
        smsSuppressed=sum(case.notificationSmsStatus == "Suppressed" for case in cases),
        smsDeliveryConfirmed=sum(case.notificationSmsDeliveryConfirmed for case in cases),
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


@router.get(
    "/{case_id}/handoff-note",
    response_model=CaseHandoffNoteResponse,
    summary="Get nurse handoff note",
    description=(
        "Return a deterministic plain-text nurse handoff note for a saved case. "
        "This local demo helper does not call AI, does not call Azure, and does "
        "not send notifications. Cosmos-backed lookups may require the existing "
        "createdDate query parameter."
    ),
    response_description="Copy-friendly nurse handoff note for the saved case.",
    responses={
        200: {
            "description": "Copy-friendly nurse handoff note for the saved case.",
            "content": {
                "application/json": {
                    "example": HANDOFF_NOTE_OPENAPI_EXAMPLE,
                },
            },
        },
    },
)
async def get_case_handoff_note(
    case_id: str,
    createdDate: str | None = None,
) -> CaseHandoffNoteResponse:
    try:
        case = await case_repository.get_by_id(case_id, created_date=createdDate)
    except MissingCasePartitionKeyError as error:
        raise HTTPException(
            status_code=400,
            detail="createdDate is required for Cosmos-backed case lookup.",
        ) from error

    if case is None:
        raise HTTPException(status_code=404, detail="Case not found")

    return CaseHandoffNoteResponse(
        caseId=case.id,
        createdDate=case.createdDate,
        handoffNote=handoff_note_formatter.format(case),
    )


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


def _clean_optional_query_filter(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned_value = value.strip()
    return cleaned_value or None
