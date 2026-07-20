import json
from pathlib import Path

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
        "artifactDigest": "unpackaged",
    }


def test_hosted_version_route_fails_closed_when_marker_is_missing(
    monkeypatch,
) -> None:
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "fictional-instance")

    response = client.get("/version")

    assert response.status_code == 503
    assert response.json() == {"detail": "Application artifact marker unavailable."}


def test_hosted_version_route_fails_closed_when_marker_is_malformed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    marker = tmp_path / "application-artifact.json"
    marker.write_text('{"sourceDigest":"not-a-digest"}', encoding="utf-8")
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "fictional-instance")
    monkeypatch.setattr(
        "src.app.services.application_artifact.ARTIFACT_MARKER_PATH",
        marker,
    )

    response = client.get("/version")

    assert response.status_code == 503
    assert response.json() == {"detail": "Application artifact marker unavailable."}


def test_hosted_version_route_returns_valid_packaged_artifact_digest(
    monkeypatch,
    tmp_path: Path,
) -> None:
    digest = "a" * 64
    marker = tmp_path / "application-artifact.json"
    marker.write_text(
        json.dumps({"artifactDigest": digest, "schemaVersion": 1}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "fictional-instance")
    monkeypatch.setattr(
        "src.app.services.application_artifact.ARTIFACT_MARKER_PATH",
        marker,
    )

    response = client.get("/version")

    assert response.status_code == 200
    assert response.json()["artifactDigest"] == digest


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
