import json

from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def test_health_route_returns_liveness_status() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "nurse-intake-assistant",
    }


def test_health_route_does_not_expose_sensitive_or_provider_fields() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    serialized = json.dumps(response.json())
    for sensitive_name in [
        "connectionString",
        "connection_string",
        "key",
        "token",
        "secret",
        "password",
        "endpoint",
        "phoneNumber",
        "phone_number",
        "emailAddress",
        "email_address",
        "credential",
        "provider",
    ]:
        assert sensitive_name not in serialized
