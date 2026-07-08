import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.app.main import app
from src.app.services.nurse_intake_agent_preflight import (
    FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND,
)


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
        "agent_provider": "mock",
        "agent_provider_normalized": "mock",
        "azure_ai_foundry_agent_project_endpoint": None,
        "azure_ai_foundry_project_endpoint": None,
        "azure_ai_foundry_agent_id": None,
        "demo_suppress_notifications": False,
    }
    values.update(overrides)
    if "agent_provider_normalized" not in overrides:
        values["agent_provider_normalized"] = (
            values["agent_provider"].strip().lower() or "mock"
        )
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
    assert body["agentProvider"] == "mock"
    assert body["agentStatus"] == {
        "provider": "mock",
        "ready": True,
        "mode": "mock",
        "missingSettings": [],
    }
    assert body["agentProviderStatus"] == {
        "provider": "mock",
        "configured": True,
        "liveValidation": "not_attempted",
        "manualValidationAvailable": False,
        "manualValidationCommand": None,
        "missingSettings": [],
        "warnings": [],
    }
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


def test_demo_status_warns_when_foundry_agent_provider_is_configured(
    monkeypatch,
) -> None:
    _set_demo_status_settings(monkeypatch, agent_provider="foundry-agent")

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["demoModeReady"] is False
    assert body["agentProvider"] == "foundry-agent"
    assert body["agentStatus"] == {
        "provider": "foundry-agent",
        "ready": False,
        "mode": "configuration-only",
        "missingSettings": [
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
            "AZURE_AI_FOUNDRY_AGENT_ID",
        ],
    }
    assert body["agentProviderStatus"] == {
        "provider": "foundry-agent",
        "configured": False,
        "liveValidation": "not_attempted",
        "manualValidationAvailable": True,
        "manualValidationCommand": FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND,
        "missingSettings": [
            (
                "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT or "
                "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"
            ),
            "AZURE_AI_FOUNDRY_AGENT_ID",
        ],
        "warnings": [
            "Foundry Agent readiness is configuration-only; live Azure validation was not attempted."
        ],
    }
    assert any(
        "AGENT_PROVIDER is foundry-agent" in warning
        for warning in body["warnings"]
    )
    assert any("manual" in warning.lower() for warning in body["warnings"])
    assert all("not wired yet" not in warning for warning in body["warnings"])


def test_demo_status_reports_foundry_agent_ready_when_configuration_is_present(
    monkeypatch,
) -> None:
    _set_demo_status_settings(
        monkeypatch,
        agent_provider="foundry-agent",
        agent_provider_normalized="foundry-agent",
        azure_ai_foundry_agent_project_endpoint=(
            "https://fictional-foundry.services.ai.azure.com/api/projects/demo"
        ),
        azure_ai_foundry_agent_id="fictional-agent-id",
    )

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["agentStatus"] == {
        "provider": "foundry-agent",
        "ready": True,
        "mode": "configuration-only",
        "missingSettings": [],
    }
    assert body["agentProviderStatus"] == {
        "provider": "foundry-agent",
        "configured": True,
        "liveValidation": "not_attempted",
        "manualValidationAvailable": True,
        "manualValidationCommand": FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND,
        "missingSettings": [],
        "warnings": [
            "Foundry Agent readiness is configuration-only; live Azure validation was not attempted."
        ],
    }
    serialized = json.dumps(body)
    assert "fictional-foundry" not in serialized
    assert "fictional-agent-id" not in serialized


def test_demo_status_foundry_agent_manual_validation_command_is_static_and_safe(
    monkeypatch,
) -> None:
    _set_demo_status_settings(
        monkeypatch,
        agent_provider="foundry-agent",
        azure_ai_foundry_agent_project_endpoint=(
            "https://actual-endpoint.services.ai.azure.com/api/projects/demo"
        ),
        azure_ai_foundry_agent_id="actual-agent-id",
        azure_ai_foundry_model_deployment_name="actual-deployment",
        acs_email_connection_string="Endpoint=https://actual-secret/;AccessKey=secret",
    )

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    agent_status = body["agentProviderStatus"]
    assert agent_status["provider"] == "foundry-agent"
    assert agent_status["manualValidationAvailable"] is True
    assert agent_status["manualValidationCommand"] == (
        "python scripts/smoke_foundry_agent.py "
        "--env-file .env.foundry-agent.local --live --json"
    )
    serialized = json.dumps(body)
    for unsafe_text in [
        "https://actual-endpoint.services.ai.azure.com",
        "actual-agent-id",
        "actual-deployment",
        "actual-secret",
        "AccessKey",
        "secret",
        "bearer",
        "token",
    ]:
        assert unsafe_text not in serialized


def test_demo_status_foundry_agent_missing_settings_still_advertises_command(
    monkeypatch,
) -> None:
    _set_demo_status_settings(
        monkeypatch,
        agent_provider="foundry-agent",
        azure_ai_foundry_agent_project_endpoint=None,
        azure_ai_foundry_agent_id=None,
    )

    response = client.get("/demo/status")

    assert response.status_code == 200
    agent_status = response.json()["agentProviderStatus"]
    assert agent_status["manualValidationAvailable"] is True
    assert "--live --json" in agent_status["manualValidationCommand"]
    assert agent_status["missingSettings"] == [
        (
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT or "
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"
        ),
        "AZURE_AI_FOUNDRY_AGENT_ID",
    ]


def test_demo_status_treats_foundry_agent_smoke_alias_as_foundry_agent(
    monkeypatch,
) -> None:
    _set_demo_status_settings(monkeypatch, agent_provider="foundry")

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["demoModeReady"] is False
    assert body["agentProvider"] == "foundry"
    assert body["agentStatus"]["provider"] == "foundry"
    assert body["agentStatus"]["mode"] == "configuration-only"
    assert any(
        "AGENT_PROVIDER is foundry" in warning
        for warning in body["warnings"]
    )
    assert all("unsupported" not in warning for warning in body["warnings"])


def test_demo_status_does_not_create_foundry_agent_client(monkeypatch) -> None:
    import src.app.services.foundry_agent_client as foundry_agent_client

    _set_demo_status_settings(
        monkeypatch,
        agent_provider="foundry",
        agent_provider_normalized="foundry",
        azure_ai_foundry_agent_project_endpoint=(
            "https://fictional-foundry.services.ai.azure.com/api/projects/demo"
        ),
        azure_ai_foundry_agent_id="fictional-agent-id",
    )
    monkeypatch.setattr(
        foundry_agent_client,
        "create_foundry_agent_client",
        lambda *args, **kwargs: pytest.fail("Foundry client should not be created"),
    )

    response = client.get("/demo/status")

    assert response.status_code == 200
    assert response.json()["agentStatus"]["ready"] is True


def test_demo_status_does_not_construct_live_foundry_agent_client_on_app_import(
    monkeypatch,
) -> None:
    import importlib
    import sys
    from types import ModuleType

    import src.app.services.foundry_agent_client as foundry_agent_client

    module_names = (
        "src.app.main",
        "src.app.routes.intake",
        "src.app.routes.demo",
        "src.app.dependencies",
    )
    original_modules: dict[str, ModuleType | None] = {
        module_name: sys.modules.get(module_name)
        for module_name in module_names
    }

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "https://fictional-foundry.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", "fictional-agent-id")
    monkeypatch.setattr(
        foundry_agent_client,
        "AzureAiFoundryAgentLiveClient",
        lambda *args, **kwargs: pytest.fail(
            "Live Foundry Agent client should not be constructed for /demo/status"
        ),
    )

    try:
        for module_name in module_names:
            sys.modules.pop(module_name, None)

        imported_main = importlib.import_module("src.app.main")
        local_client = TestClient(imported_main.app)

        response = local_client.get("/demo/status")

        assert response.status_code == 200
        assert response.json()["agentStatus"]["mode"] == "configuration-only"
    finally:
        for module_name in reversed(module_names):
            original_module = original_modules[module_name]
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def test_demo_status_warns_when_agent_provider_is_unsupported(monkeypatch) -> None:
    _set_demo_status_settings(monkeypatch, agent_provider="future-agent")

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["demoModeReady"] is False
    assert body["agentProvider"] == "future-agent"
    assert (
        "AGENT_PROVIDER is not mock; unsupported agent providers must not be "
        "claimed for local demo readiness."
    ) in body["warnings"]
    assert body["agentProviderStatus"] == {
        "provider": "unsupported",
        "configured": False,
        "liveValidation": "not_attempted",
        "manualValidationAvailable": False,
        "manualValidationCommand": None,
        "missingSettings": [],
        "warnings": [
            "Unsupported AGENT_PROVIDER; restore AGENT_PROVIDER=mock for local demo readiness."
        ],
    }


def test_demo_status_sanitizes_secret_like_unsupported_agent_provider(
    monkeypatch,
) -> None:
    unsafe_provider = "https://example.invalid/?token=secret-agent-id"
    _set_demo_status_settings(monkeypatch, agent_provider=unsafe_provider)

    response = client.get("/demo/status")

    assert response.status_code == 200
    body = response.json()
    assert body["demoModeReady"] is False
    assert body["agentProvider"] == "unsupported"
    assert body["agentStatus"]["provider"] == "unsupported"
    assert body["agentProviderStatus"]["provider"] == "unsupported"
    serialized = json.dumps(body)
    assert "example.invalid" not in serialized
    assert "secret-agent-id" not in serialized
    assert "token=" not in serialized


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
