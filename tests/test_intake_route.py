import pytest
from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


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
