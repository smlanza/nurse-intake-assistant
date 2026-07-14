from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.app.main import app
from src.app.services.nurse_intake_agent_preflight import (
    FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND,
)


client = TestClient(app)


def _set_ops_settings(monkeypatch, **overrides) -> None:
    import src.app.routes.ops as ops_route

    values = {
        "agent_provider": "mock",
        "agent_provider_normalized": "mock",
        "azure_ai_foundry_agent_project_endpoint": None,
        "azure_ai_foundry_agent_endpoint": None,
        "azure_ai_foundry_agent_use_project_endpoint_compatibility": False,
        "azure_ai_foundry_project_endpoint": None,
        "azure_ai_foundry_agent_id": None,
        "azure_ai_foundry_agent_name": None,
        "azure_ai_foundry_agent_version": None,
        "azure_ai_foundry_model_deployment_name": None,
        "acs_email_connection_string": None,
    }
    values.update(overrides)
    if (
        "azure_ai_foundry_agent_endpoint" not in overrides
        and values["azure_ai_foundry_agent_project_endpoint"]
        and values["azure_ai_foundry_agent_name"]
    ):
        values["azure_ai_foundry_agent_endpoint"] = (
            f"{str(values['azure_ai_foundry_agent_project_endpoint']).rstrip('/')}"
            f"/agents/{values['azure_ai_foundry_agent_name']}"
            "/endpoint/protocols/openai"
        )
    if "agent_provider_normalized" not in overrides:
        values["agent_provider_normalized"] = (
            values["agent_provider"].strip().lower() or "mock"
        )
    monkeypatch.setattr(ops_route, "settings", SimpleNamespace(**values), raising=False)


def test_ops_page_returns_html() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_ops_page_lists_safe_routes_and_purposes() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "Nurse Intake Assistant Operations" in html
    assert "/health" in html
    assert "liveness check" in html
    assert "/version" in html
    assert "safe service metadata" in html
    assert "/demo" in html
    assert "local mock demo UI" in html
    assert "/demo/status" in html
    assert "local demo readiness status" in html
    assert "/: redirects to /demo" in html


def test_ops_page_does_not_show_foundry_agent_manual_command_in_mock_mode(
    monkeypatch,
) -> None:
    _set_ops_settings(monkeypatch)

    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "Nurse Intake Assistant Operations" in html
    assert "Safe Routes" in html
    assert FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND not in html
    assert "Foundry Agent Manual Validation" not in html


def test_ops_page_shows_foundry_agent_manual_command_when_configured(
    monkeypatch,
) -> None:
    _set_ops_settings(
        monkeypatch,
        agent_provider="foundry-agent",
        azure_ai_foundry_agent_project_endpoint=(
            "https://actual-endpoint.services.ai.azure.com/api/projects/demo"
        ),
        azure_ai_foundry_agent_id="actual-agent-id",
        azure_ai_foundry_agent_name="actual-agent-name",
        azure_ai_foundry_agent_version="actual-agent-version",
        azure_ai_foundry_model_deployment_name="actual-deployment",
        acs_email_connection_string="Endpoint=https://actual-secret/;AccessKey=secret",
    )

    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "Foundry Agent Manual Validation" in html
    assert FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND in html
    assert "Run this command manually from a configured developer shell" in html
    assert "This page only shows the command; it does not call Azure" in html
    for unsafe_text in [
        "https://actual-endpoint.services.ai.azure.com",
        "actual-agent-id",
        "actual-agent-name",
        "actual-agent-version",
        "actual-deployment",
        "actual-secret",
        "AccessKey",
        "bearer",
        "token",
    ]:
        assert unsafe_text not in html


def test_ops_page_shows_foundry_agent_manual_command_when_settings_missing(
    monkeypatch,
) -> None:
    _set_ops_settings(
        monkeypatch,
        agent_provider="foundry-agent",
        azure_ai_foundry_agent_project_endpoint=None,
        azure_ai_foundry_agent_id=None,
        azure_ai_foundry_agent_name=None,
        azure_ai_foundry_agent_version=None,
    )

    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "Foundry Agent Manual Validation" in html
    assert FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND in html
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in html
    assert "AZURE_AI_FOUNDRY_AGENT_ENDPOINT" in html
    assert "AZURE_AI_FOUNDRY_AGENT_NAME" in html
    assert "AZURE_AI_FOUNDRY_AGENT_VERSION" in html
    assert "None" not in html


def test_ops_page_does_not_show_manual_command_for_unsupported_agent_provider(
    monkeypatch,
) -> None:
    _set_ops_settings(monkeypatch, agent_provider="unsupported-value")

    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "Unsupported AGENT_PROVIDER" in html
    assert FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND not in html
    assert "Foundry Agent Manual Validation" not in html


def test_ops_page_includes_safety_wording() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    assert "informational only" in html
    assert "does not validate live Azure readiness" in html
    assert (
        "must not expose secrets, provider credentials, connection strings, "
        "phone numbers, email addresses, or patient data"
    ) in html


def test_ops_page_does_not_include_sensitive_examples() -> None:
    response = client.get("/ops")

    assert response.status_code == 200
    html = response.text
    for sensitive_term in [
        "connectionString",
        "key=",
        "token=",
        "password",
        "endpoint=",
        "000-000-0000",
        "555",
        "example.com",
        "nurse@",
        "providerCredential",
    ]:
        assert sensitive_term not in html
