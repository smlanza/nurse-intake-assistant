from fastapi.testclient import TestClient

from src.app.dependencies import email_notification_sender, sms_notification_sender
from src.app.main import app


client = TestClient(app)


def create_case(text: str) -> dict:
    response = client.post("/intake/text", json={"text": text})
    assert response.status_code == 200
    return response.json()


def test_get_email_notifications_returns_200_with_list() -> None:
    email_notification_sender.sent_notifications.clear()

    response = client.get("/notifications/email")

    assert response.status_code == 200
    assert response.json() == []


def test_get_email_notifications_returns_recorded_case_notification() -> None:
    email_notification_sender.sent_notifications.clear()
    case = create_case(
        "My name is Jane Doe. DOB: 1980-04-15. "
        "My callback number is +1 (555) 555-0123. I need a medication refill."
    )

    response = client.get("/notifications/email")

    assert response.status_code == 200
    notifications = response.json()
    assert isinstance(notifications, list)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification["recipient"]
    assert notification["subject"]
    assert notification["body"]
    assert notification["case_id"] == case["id"]


def test_get_email_notifications_preserves_send_order() -> None:
    email_notification_sender.sent_notifications.clear()
    first_case = create_case("I need a medication refill.")
    second_case = create_case("I have a cough and fever.")

    response = client.get("/notifications/email")

    assert response.status_code == 200
    notifications = response.json()
    assert len(notifications) == 2
    assert [notification["case_id"] for notification in notifications] == [
        first_case["id"],
        second_case["id"],
    ]


def test_get_sms_notifications_returns_200_with_list() -> None:
    sms_notification_sender.sent_notifications.clear()

    response = client.get("/notifications/sms")

    assert response.status_code == 200
    assert response.json() == []


def test_get_sms_notifications_returns_recorded_case_notification() -> None:
    sms_notification_sender.sent_notifications.clear()
    case = create_case(
        "My name is Jane Doe. DOB: 1980-04-15. "
        "My callback number is +1 (555) 555-0123. I need a medication refill."
    )

    response = client.get("/notifications/sms")

    assert response.status_code == 200
    notifications = response.json()
    assert isinstance(notifications, list)
    assert len(notifications) == 1
    notification = notifications[0]
    assert notification["recipient"]
    assert notification["body"]
    assert notification["case_id"] == case["id"]
    assert case["summary"] in notification["body"]


def test_get_sms_notifications_preserves_send_order() -> None:
    sms_notification_sender.sent_notifications.clear()
    first_case = create_case("I need a medication refill.")
    second_case = create_case("I have a cough and fever.")

    response = client.get("/notifications/sms")

    assert response.status_code == 200
    notifications = response.json()
    assert len(notifications) == 2
    assert [notification["case_id"] for notification in notifications] == [
        first_case["id"],
        second_case["id"],
    ]


def test_get_sms_notifications_does_not_expose_acs_secrets() -> None:
    sms_notification_sender.sent_notifications.clear()
    sms_notification_sender.send_case_notification(
        recipient="+15555550123",
        body="Summary: Patient needs a medication refill.",
        case_id="case-sms-secret-check",
    )

    response = client.get("/notifications/sms")

    assert response.status_code == 200
    response_text = response.text.lower()
    assert "accesskey" not in response_text
    assert "connection_string" not in response_text
    assert "endpoint=https://" not in response_text


def test_get_email_notifications_still_returns_recorded_notifications() -> None:
    email_notification_sender.sent_notifications.clear()
    case = create_case("I need a medication refill.")

    response = client.get("/notifications/email")

    assert response.status_code == 200
    notifications = response.json()
    assert len(notifications) == 1
    assert notifications[0]["case_id"] == case["id"]
