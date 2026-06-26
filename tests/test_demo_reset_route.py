from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def create_case() -> dict:
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
    return response.json()


def reset_demo_state() -> dict:
    response = client.post("/demo/reset")
    assert response.status_code == 200
    return response.json()


def test_demo_reset_returns_success_in_mock_mode() -> None:
    response = client.post("/demo/reset")

    assert response.status_code == 200
    assert response.json() == {
        "reset": True,
        "cleared": {
            "cases": True,
            "emailNotifications": True,
            "smsNotifications": True,
        },
    }


def test_demo_reset_clears_in_memory_cases() -> None:
    reset_demo_state()
    create_case()
    create_case()

    assert len(client.get("/cases").json()) == 2

    reset_demo_state()

    response = client.get("/cases")
    assert response.status_code == 200
    assert response.json() == []


def test_demo_reset_clears_mock_email_and_sms_notifications() -> None:
    reset_demo_state()
    create_case()

    assert client.get("/notifications/email").json()
    assert client.get("/notifications/sms").json()

    reset_demo_state()

    assert client.get("/notifications/email").json() == []
    assert client.get("/notifications/sms").json() == []


def test_demo_reset_does_not_break_subsequent_intake_creation() -> None:
    reset_demo_state()

    case = create_case()

    assert case["id"]
    assert client.get("/cases").json()[0]["id"] == case["id"]
    assert client.get("/notifications/email").json()[0]["case_id"] == case["id"]
    assert client.get("/notifications/sms").json()[0]["case_id"] == case["id"]


def test_demo_reset_is_unavailable_outside_mock_mode(
    monkeypatch,
) -> None:
    import src.app.routes.demo as demo_route

    class NonMockSettings:
        app_mode = "cosmos"

    class ResetShouldNotBeCalled:
        def clear(self) -> None:
            raise AssertionError("reset should not clear non-mock state")

    monkeypatch.setattr(demo_route, "settings", NonMockSettings())
    monkeypatch.setattr(demo_route, "case_repository", ResetShouldNotBeCalled())
    monkeypatch.setattr(
        demo_route,
        "email_notification_sender",
        ResetShouldNotBeCalled(),
    )
    monkeypatch.setattr(
        demo_route,
        "sms_notification_sender",
        ResetShouldNotBeCalled(),
    )
    test_app = FastAPI()
    test_app.include_router(demo_route.router)
    local_client = TestClient(test_app)

    response = local_client.post("/demo/reset")

    assert response.status_code == 400
    assert "only available in mock mode" in response.json()["detail"]
