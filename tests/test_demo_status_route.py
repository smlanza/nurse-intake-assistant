import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def _demo_status_endpoint():
    return next(
        child_route.endpoint
        for route in app.routes
        for child_route in getattr(getattr(route, "original_router", None), "routes", [])
        if getattr(child_route, "path", None) == "/demo/status"
    )


def _set_demo_status_settings(monkeypatch, **overrides) -> None:
    values = {
        "app_mode": "mock",
        "ai_provider": "mock",
        "speech_provider": "mock",
        "email_provider": "mock",
        "sms_provider": "mock",
        "demo_suppress_notifications": False,
    }
    values.update(overrides)
    monkeypatch.setitem(
        _demo_status_endpoint().__globals__,
        "settings",
        SimpleNamespace(**values),
    )


def test_demo_status_reports_default_mock_configuration(monkeypatch) -> None:
    _set_demo_status_settings(monkeypatch)

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["demoModeReady"] is True
    assert body["appMode"] == "mock"
    assert body["aiProvider"] == "mock"
    assert body["speechProvider"] == "mock"
    assert body["emailProvider"] == "mock"
    assert body["smsProvider"] == "mock"
    assert body["safeForLocalDemo"] is True
    assert body["warnings"] == []
    safety_boundary = body["safetyBoundary"].lower()
    assert "not for production clinical use" in safety_boundary
    assert "human nurse review" in safety_boundary


def test_demo_status_warns_when_ai_provider_is_not_mock(monkeypatch) -> None:
    _set_demo_status_settings(monkeypatch, ai_provider="foundry")

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["demoModeReady"] is False
    assert body["aiProvider"] == "foundry"
    assert (
        "AI_PROVIDER is not mock; live AI integration should not be claimed "
        "unless manually verified."
    ) in body["warnings"]


def test_demo_status_reflects_suppressed_notifications(monkeypatch) -> None:
    _set_demo_status_settings(monkeypatch, demo_suppress_notifications=True)

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["notificationsSuppressed"] is True
    assert body["demoModeReady"] is True
    assert body["emailProvider"] == "mock"
    assert body["smsProvider"] == "mock"


def test_demo_status_does_not_expose_secret_like_fields(monkeypatch) -> None:
    _set_demo_status_settings(monkeypatch)

    response = client.get("/demo/status")

    assert response.status_code == 200
    serialized = json.dumps(response.json())
    for secret_like_name in [
        "connectionString",
        "key",
        "token",
        "secret",
        "password",
        "phoneNumber",
        "emailAddress",
        "endpoint",
    ]:
        assert secret_like_name not in serialized
