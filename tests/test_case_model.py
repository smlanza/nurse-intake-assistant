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
    assert case.intakeComplete is True


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


def test_case_document_defaults_to_unknown_processing_trace() -> None:
    now = datetime.now(timezone.utc)

    case = CaseDocument(
        createdDate=now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
    )

    assert case.processing_trace.ai_provider is None
    assert case.processing_trace.agent_provider is None
    assert case.processing_trace.agent_used is False
    assert case.processing_trace.agent_attempted is False
    assert case.processing_trace.agent_mode is None
    assert case.processing_trace.agent_output_valid is None
    assert case.processing_trace.agent_fallback_used is False
    assert case.processing_trace.agent_fallback_reason is None
    assert case.processing_trace.steps == []
    assert case.processing_trace.rules_urgency_override is False
    assert case.processing_trace.final_urgency_source == "unknown"
    assert case.processing_trace.warnings == []
