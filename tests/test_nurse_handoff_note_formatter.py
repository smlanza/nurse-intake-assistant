from datetime import datetime, timezone

from src.app.models.ai_outputs import PatientInfo
from src.app.models.case import CaseDocument
from src.app.services.nurse_handoff_note_formatter import (
    SAFETY_HEADER,
    NurseHandoffNoteFormatter,
)


def test_formatter_returns_deterministic_note_with_demo_safety_header() -> None:
    case = _case()
    formatter = NurseHandoffNoteFormatter()

    first_note = formatter.format(case)
    second_note = formatter.format(case)

    assert first_note == second_note
    assert first_note.startswith(SAFETY_HEADER)
    assert "Not for production clinical use" in first_note
    assert "AI-assisted output requires nurse review" in first_note


def test_formatter_includes_expected_handoff_sections() -> None:
    note = NurseHandoffNoteFormatter().format(_case())

    assert "Case metadata" in note
    assert "Case ID: case-123" in note
    assert "Source/channel: voicemail-transcript / text-intake" in note
    assert "Patient Summary" in note
    assert "Patient name: Demo Patient" in note
    assert "Callback number: demo-callback-001" in note
    assert "Main concern: medication refill" in note
    assert "Reported Symptoms" in note
    assert "- Symptoms: fatigue, mild headache" in note
    assert "Duration/onset: Missing" in note
    assert "Red Flags" in note
    assert "Red flag rationale: No urgent symptoms were described." in note
    assert "Recommended Nurse Review Priority" in note
    assert "Urgency level: Routine" in note
    assert "Missing information / follow-up" in note
    assert "Missing required fields: insurance_status" in note
    assert "Intake completion status: NeedsFollowUp" in note
    assert "Notification Status" in note
    assert "Email status: MockRecorded" in note
    assert "SMS delivery confirmed: false" in note
    assert "Nurse review" in note
    assert "Reviewed by: nurse-demo" in note
    assert "Review notes: Called patient back." in note


def test_formatter_handles_missing_optional_fields_without_raising() -> None:
    now = datetime(2026, 6, 30, 15, 0, tzinfo=timezone.utc)
    case = CaseDocument(
        id="case-missing",
        createdDate="2026-06-30",
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
        processingStatus="Completed",
    )

    note = NurseHandoffNoteFormatter().format(case)

    assert "Patient name: Unknown" in note
    assert "Callback number: Missing" in note
    assert "Main concern: Missing" in note
    assert "Symptoms: None recorded" in note
    assert "Red flag rationale: None recorded" in note
    assert "Missing required fields: None recorded" in note
    assert "Not yet reviewed" in note


def _case() -> CaseDocument:
    now = datetime(2026, 6, 30, 15, 30, tzinfo=timezone.utc)
    return CaseDocument(
        id="case-123",
        createdDate="2026-06-30",
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
        sourceSystem="voicemail-transcript",
        patient=PatientInfo(
            name="Demo Patient",
            date_of_birth="1980-04-15",
            callback_number="demo-callback-001",
        ),
        reasonForCalling="medication refill",
        symptoms=["fatigue", "mild headache"],
        summary="Demo patient requests a medication refill.",
        urgency="Routine",
        urgencySource="RulesAndAI",
        urgencyRationale="No urgent symptoms were described.",
        missingFields=["insurance_status"],
        intakeComplete=False,
        intakeStatus="NeedsFollowUp",
        processingStatus="Completed",
        reviewStatus="Reviewed",
        reviewedBy="nurse-demo",
        reviewedAt=now,
        reviewNotes="Called patient back.",
        notificationEmailStatus="MockRecorded",
        notificationSmsStatus="MockRecorded",
        notificationSmsDeliveryConfirmed=False,
    )
