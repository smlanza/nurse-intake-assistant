import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.models.case import CaseDocument
from src.app.services.case_processing_service import CaseProcessingService


client = TestClient(app)


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
    assert case["reviewStatus"] == "New"
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
    assert len(email_notification_sender.sent_notifications) == 1
    assert email_notification_sender.sent_notifications[0].case_id == case["id"]


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


@pytest.mark.parametrize("text", ["", "   "])
def test_text_intake_rejects_empty_text(text: str) -> None:
    response = client.post("/intake/text", json={"text": text})

    assert response.status_code == 422


def test_health_endpoint_still_works() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
