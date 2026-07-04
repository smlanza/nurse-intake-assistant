import json

from fastapi.testclient import TestClient

from src.app.main import app


client = TestClient(app)


def test_version_route_returns_static_demo_metadata() -> None:
    response = client.get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "service": "nurse-intake-assistant",
        "version": "0.1.0",
        "environment": "local",
    }


def test_version_route_does_not_expose_sensitive_or_provider_fields() -> None:
    response = client.get("/version")

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
        "aiProvider",
        "speechProvider",
        "emailProvider",
        "smsProvider",
        "repositoryProvider",
        "azure",
        "resourceGroup",
        "subscription",
        "tenant",
        "notificationTarget",
        "nurseNotification",
    ]:
        assert sensitive_name not in serialized
