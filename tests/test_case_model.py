from datetime import datetime, timezone

from src.app.models.case import CaseDocument


def test_case_document_defaults_to_pending_review() -> None:
    now = datetime.now(timezone.utc)

    case = CaseDocument(
        createdDate=now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
    )

    assert case.reviewStatus == "PendingReview"
    assert case.reviewedBy is None
    assert case.reviewNotes is None
    assert case.reviewedAt is None


def test_case_document_defaults_to_unattempted_notification_statuses() -> None:
    now = datetime.now(timezone.utc)

    case = CaseDocument(
        createdDate=now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
    )

    assert case.notificationEmailSent is False
    assert case.notificationEmailStatus == "NotAttempted"
    assert case.notificationSmsSent is False
    assert case.notificationSmsStatus == "NotAttempted"
    assert case.notificationSmsDeliveryConfirmed is False
