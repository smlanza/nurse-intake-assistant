import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.models.case import CaseDocument
from src.app.services.case_processing_service import CaseProcessingService


client = TestClient(app)


def reset_demo_state() -> None:
    response = client.post("/demo/reset")
    assert response.status_code == 200


class SnapshotCaseRepository:
    def __init__(self) -> None:
        self.saved_cases: list[dict] = []

    async def save(self, case: CaseDocument) -> CaseDocument:
        self.saved_cases.append(case.model_dump(mode="json"))
        return case

    async def get_by_id(
        self,
        case_id: str,
        created_date: str | None = None,
    ) -> CaseDocument | None:
        return None


def test_text_intake_returns_completed_routine_case() -> None:
    response = client.post(
        "/intake/text",
        json={
            "text": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            ),
            "sourceSystem": "local-test",
            "sourceCallId": "test-call-123",
        },
    )

    assert response.status_code == 200
    case = response.json()
    assert case["caseType"] == "text-intake"
    assert case["processingStatus"] == "Completed"
    assert case["reviewStatus"] == "PendingReview"
    assert case["intakeComplete"] is True
    assert case["missingFields"] == []
    assert case["urgency"] == "Routine"
    assert case["sourceSystem"] == "local-test"
    assert case["sourceCallId"] == "test-call-123"
    assert case["id"]
    assert case["summary"] == "Patient is calling about medication refill."


def test_text_intake_records_notification_through_shared_sender() -> None:
    from src.app.dependencies import email_notification_sender

    email_notification_sender.sent_notifications.clear()

    response = client.post(
        "/intake/text",
        json={
            "text": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            )
        },
    )

    assert response.status_code == 200
    case = response.json()
    assert case["id"]
    assert case["processingStatus"] == "Completed"
    assert case["summary"] == "Patient is calling about medication refill."
    assert len(email_notification_sender.sent_notifications) == 1
    notification = email_notification_sender.sent_notifications[0]
    assert notification.case_id == case["id"]
    assert case["urgency"] in notification.subject
    assert case["summary"] in notification.body


def test_text_intake_default_mock_mode_returns_successful_sms_notification() -> None:
    from src.app.dependencies import email_notification_sender

    email_notification_sender.sent_notifications.clear()

    response = client.post(
        "/intake/text",
        json={
            "text": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            )
        },
    )

    assert response.status_code == 200
    case = response.json()
    assert case["id"]
    assert case["notificationSmsSent"] is True
    assert case["notificationEmailSent"] is True
    assert case["notificationEmailStatus"] == "MockRecorded"
    assert case["notificationSmsStatus"] == "MockRecorded"
    assert case["notificationSmsDeliveryConfirmed"] is False
    assert len(email_notification_sender.sent_notifications) == 1
    assert email_notification_sender.sent_notifications[0].case_id == case["id"]


def test_text_intake_with_missing_required_fields_returns_incomplete_case() -> None:
    response = client.post(
        "/intake/text",
        json={"text": "I have a cough and fever."},
    )

    assert response.status_code == 200
    case = response.json()
    assert case["intakeComplete"] is False
    assert case["intakeStatus"] == "NeedsFollowUp"
    assert case["reviewStatus"] == "PendingReview"
    assert case["missingFields"] == [
        "patient.name",
        "patient.date_of_birth",
        "patient.callback_number",
    ]
    assert case["notificationEmailSent"] is True
    assert case["notificationSmsSent"] is True


def test_text_intake_persists_request_source_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.routes.intake as intake_route

    repository = SnapshotCaseRepository()
    monkeypatch.setattr(
        intake_route,
        "case_processing_service",
        CaseProcessingService(
            case_repository=repository,
            suppress_notifications=True,
        ),
    )
    monkeypatch.setattr(intake_route, "case_repository", repository)
    test_app = FastAPI()
    test_app.include_router(intake_route.router)
    local_client = TestClient(test_app)

    response = local_client.post(
        "/intake/text",
        json={
            "text": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            ),
            "sourceSystem": "manual-cosmos-smoke-test",
            "sourceCallId": "manual-smoke-001",
        },
    )

    assert response.status_code == 200
    saved_case = repository.saved_cases[-1]
    assert saved_case["sourceSystem"] == "manual-cosmos-smoke-test"
    assert saved_case["sourceCallId"] == "manual-smoke-001"


@pytest.mark.parametrize("text", ["I have chest pain.", "I have shortness of breath."])
def test_text_intake_returns_urgent_for_red_flag(text: str) -> None:
    response = client.post("/intake/text", json={"text": text})

    assert response.status_code == 200
    case = response.json()
    assert case["caseType"] == "text-intake"
    assert case["processingStatus"] == "Completed"
    assert case["urgency"] == "Urgent"
    assert case["sourceSystem"] == "local"


@pytest.mark.parametrize("text", ["", "   ", "hi"])
def test_text_intake_rejects_unusable_text_without_side_effects(text: str) -> None:
    reset_demo_state()

    response = client.post("/intake/text", json={"text": text})

    assert response.status_code == 422
    response_text = response.text
    assert "text" in response_text
    assert client.get("/cases").json() == []
    assert client.get("/notifications/email").json() == []
    assert client.get("/notifications/sms").json() == []


def test_valid_text_intake_still_creates_case_after_validation() -> None:
    reset_demo_state()

    response = client.post(
        "/intake/text",
        json={"text": "I need a medication refill for tomorrow."},
    )

    assert response.status_code == 200
    case = response.json()
    assert case["id"]
    assert client.get("/cases").json()[0]["id"] == case["id"]
    assert client.get("/notifications/email").json()[0]["case_id"] == case["id"]
    assert client.get("/notifications/sms").json()[0]["case_id"] == case["id"]


def test_voicemail_transcript_intake_returns_completed_routine_case() -> None:
    reset_demo_state()

    response = client.post(
        "/intake/voicemail-transcript",
        json={
            "transcript": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            )
        },
    )

    assert response.status_code == 200
    case = response.json()
    assert case["id"]
    assert case["caseType"] == "phone-intake"
    assert case["processingStatus"] == "Completed"
    assert case["urgency"] == "Routine"
    assert case["intakeComplete"] is True
    assert case["reviewStatus"] == "PendingReview"
    assert case["notificationEmailStatus"] == "MockRecorded"
    assert case["notificationSmsStatus"] == "MockRecorded"
    assert case["notificationSmsDeliveryConfirmed"] is False
    assert case["sourceSystem"] == "voicemail-transcript"
    assert case["summary"] == "Patient is calling about medication refill."


def test_voicemail_transcript_persists_supplied_source_metadata() -> None:
    reset_demo_state()

    response = client.post(
        "/intake/voicemail-transcript",
        json={
            "transcript": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            ),
            "sourceSystem": "manual-voicemail-smoke-test",
            "sourceCallId": "voicemail-call-001",
        },
    )

    assert response.status_code == 200
    case = response.json()
    assert case["sourceSystem"] == "manual-voicemail-smoke-test"
    assert case["sourceCallId"] == "voicemail-call-001"
    assert client.get("/cases").json()[0]["sourceCallId"] == "voicemail-call-001"


def test_voicemail_transcript_accepts_caller_phone_number_as_request_metadata() -> None:
    reset_demo_state()

    response = client.post(
        "/intake/voicemail-transcript",
        json={
            "transcript": "I have a cough and fever.",
            "callerPhoneNumber": "+1 555 555 9999",
        },
    )

    assert response.status_code == 200
    case = response.json()
    assert case["id"]
    assert case["patient"]["callback_number"] is None
    assert "callerPhoneNumber" not in case


@pytest.mark.parametrize("transcript", ["", "   ", "hi"])
def test_voicemail_transcript_rejects_unusable_transcript_without_side_effects(
    transcript: str,
) -> None:
    reset_demo_state()

    response = client.post(
        "/intake/voicemail-transcript",
        json={"transcript": transcript},
    )

    assert response.status_code == 422
    response_text = response.text
    assert "transcript" in response_text
    assert client.get("/cases").json() == []
    assert client.get("/notifications/email").json() == []
    assert client.get("/notifications/sms").json() == []


def test_text_intake_behavior_remains_unchanged_after_voicemail_endpoint() -> None:
    reset_demo_state()

    response = client.post(
        "/intake/text",
        json={"text": "I need a medication refill for tomorrow."},
    )

    assert response.status_code == 200
    case = response.json()
    assert case["caseType"] == "text-intake"
    assert case["sourceSystem"] == "local"
    assert case["reviewStatus"] == "PendingReview"


def test_health_endpoint_still_works() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
