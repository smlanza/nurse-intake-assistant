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


def seed_demo_state() -> dict:
    response = client.post("/demo/seed")
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


def test_demo_seed_returns_success_and_deterministic_case_ids() -> None:
    reset_demo_state()

    response = client.post("/demo/seed")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "seededCaseCount": 4,
        "caseIds": [
            "demo-seed-urgent-text",
            "demo-seed-routine-voicemail",
            "demo-seed-reviewed-text",
            "demo-seed-follow-up-voicemail",
        ],
    }


def test_demo_seeded_cases_appear_in_cases_and_summary() -> None:
    reset_demo_state()
    seed_response = seed_demo_state()

    cases_response = client.get("/cases")
    assert cases_response.status_code == 200
    cases = cases_response.json()
    case_ids = {case["id"] for case in cases}
    assert case_ids == set(seed_response["caseIds"])

    assert any(
        case["id"] == "demo-seed-urgent-text"
        and case["urgency"] == "Urgent"
        and case["reviewStatus"] == "PendingReview"
        and case["caseType"] == "text-intake"
        and case["sourceSystem"] == "demo-seed"
        for case in cases
    )
    assert any(
        case["id"] == "demo-seed-routine-voicemail"
        and case["urgency"] == "Routine"
        and case["reviewStatus"] == "PendingReview"
        and case["caseType"] == "phone-intake"
        and case["sourceSystem"] == "voicemail-transcript"
        for case in cases
    )
    assert any(
        case["id"] == "demo-seed-reviewed-text"
        and case["reviewStatus"] == "Reviewed"
        for case in cases
    )
    assert any(
        case["id"] == "demo-seed-follow-up-voicemail"
        and case["intakeComplete"] is False
        and case["intakeStatus"] == "NeedsFollowUp"
        for case in cases
    )
    assert any(
        case["notificationEmailStatus"] == "MockRecorded"
        and case["notificationSmsStatus"] == "MockRecorded"
        for case in cases
    )

    summary_response = client.get("/cases/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total"] == 4
    assert summary["urgent"] == 2
    assert summary["routine"] == 2
    assert summary["pendingReview"] == 3
    assert summary["reviewed"] == 1
    assert summary["pendingUrgent"] == 2
    assert summary["completeIntakes"] == 3
    assert summary["needsFollowUpIntakes"] == 1
    assert summary["emailMockRecorded"] == 1
    assert summary["smsMockRecorded"] == 1


def test_demo_seed_is_idempotent_for_repeated_demo_runs() -> None:
    reset_demo_state()

    first_seed = seed_demo_state()
    second_seed = seed_demo_state()

    assert second_seed == first_seed
    cases = client.get("/cases").json()
    assert len(cases) == first_seed["seededCaseCount"]
    assert sorted(case["id"] for case in cases) == sorted(first_seed["caseIds"])


def test_demo_reset_clears_seeded_cases() -> None:
    reset_demo_state()
    seed_demo_state()
    assert client.get("/cases").json()

    reset_demo_state()

    assert client.get("/cases").json() == []
    assert client.get("/cases/summary").json()["total"] == 0


def test_demo_seed_is_unavailable_outside_mock_mode(
    monkeypatch,
) -> None:
    import src.app.routes.demo as demo_route

    class NonMockSettings:
        app_mode = "cosmos"

    class SeedShouldNotBeCalled:
        async def save(self, case: object) -> object:
            raise AssertionError("seed should not write non-mock state")

    monkeypatch.setattr(demo_route, "settings", NonMockSettings())
    monkeypatch.setattr(demo_route, "case_repository", SeedShouldNotBeCalled())
    test_app = FastAPI()
    test_app.include_router(demo_route.router)
    local_client = TestClient(test_app)

    response = local_client.post("/demo/seed")

    assert response.status_code == 400
    assert "only available in mock mode" in response.json()["detail"]


def test_demo_seed_response_does_not_expose_secrets() -> None:
    reset_demo_state()

    response = client.post("/demo/seed")

    assert response.status_code == 200
    serialized_response = response.text.lower()
    for sensitive_term in [
        "connection",
        "key",
        "secret",
        "token",
        "password",
        "endpoint",
    ]:
        assert sensitive_term not in serialized_response


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
