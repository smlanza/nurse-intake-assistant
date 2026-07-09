import asyncio
import importlib

import pytest

from src.app.config.settings import AppSettings


def test_foundry_agent_client_module_imports_without_credentials() -> None:
    module = importlib.import_module("src.app.services.foundry_agent_client")

    assert hasattr(module, "FoundryAgentClient")
    assert hasattr(module, "FoundryAgentRequest")
    assert hasattr(module, "FoundryAgentResponse")
    assert hasattr(module, "FakeFoundryAgentClient")
    assert hasattr(module, "create_foundry_agent_client")


def test_fake_foundry_agent_client_returns_deterministic_output() -> None:
    from src.app.services.foundry_agent_client import (
        FakeFoundryAgentClient,
        FoundryAgentRequest,
    )

    client = FakeFoundryAgentClient()
    request = FoundryAgentRequest(
        intake_text="Fictional patient requests nurse follow-up for a refill.",
        instructions="Return JSON only.",
        correlation_id="test-correlation",
    )

    response = asyncio.run(client.invoke_agent(request))

    assert response.content == "Fake Foundry Agent response for local nurse review."
    assert response.metadata["provider"] == "foundry-agent"
    assert response.metadata["agentMode"] == "fake"
    assert client.requests == [request]


def test_foundry_agent_request_carries_contract_instructions() -> None:
    from src.app.services.foundry_agent_client import FoundryAgentRequest

    request = FoundryAgentRequest(
        intake_text="Fictional patient requests nurse follow-up for a refill.",
        instructions="Return JSON only.",
    )

    assert request.instructions == "Return JSON only."


def test_foundry_agent_factory_returns_injected_fake_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.foundry_agent_client import (
        FakeFoundryAgentClient,
        create_foundry_agent_client,
    )

    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    fake_client = FakeFoundryAgentClient()

    client = create_foundry_agent_client(AppSettings(), client=fake_client)

    assert client is fake_client


def test_foundry_agent_factory_does_not_create_live_client_for_mock_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client

    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    monkeypatch.setattr(
        foundry_agent_client,
        "foundry_agent_sdk_available",
        lambda: (_ for _ in ()).throw(AssertionError("SDK probe should not run")),
    )

    client = foundry_agent_client.create_foundry_agent_client(AppSettings())

    assert client is None


def test_foundry_agent_factory_does_not_validate_settings_until_live_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.foundry_agent_client import create_foundry_agent_client

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_ID", raising=False)

    client = create_foundry_agent_client(AppSettings())

    assert client is None


def test_foundry_agent_factory_missing_live_settings_fail_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.foundry_agent_client import (
        FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY,
        FoundryAgentClientError,
        create_foundry_agent_client,
    )

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_ID", raising=False)

    with pytest.raises(FoundryAgentClientError) as exc:
        create_foundry_agent_client(AppSettings(), enable_live=True)

    message = str(exc.value)
    assert exc.value.category == FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in message
    assert "project-endpoint-secret" not in message
    assert "agent-id-secret" not in message
    assert "token" not in message.lower()
    assert "credential" not in message.lower()


def test_foundry_agent_factory_can_reuse_foundry_project_endpoint_for_live_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import AzureAiFoundryAgentLiveClient

    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://fictional-foundry.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.delenv("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", raising=False)
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", "fictional-agent-id")
    monkeypatch.setattr(
        foundry_agent_client,
        "foundry_agent_sdk_available",
        lambda: True,
    )

    client = foundry_agent_client.create_foundry_agent_client(
        AppSettings(),
        enable_live=True,
    )

    assert isinstance(client, AzureAiFoundryAgentLiveClient)
    assert (
        client.project_endpoint
        == "https://fictional-foundry.services.ai.azure.com/api/projects/demo"
    )
    assert client.agent_id == "fictional-agent-id"
    assert client._agents_client is None


def test_foundry_agent_factory_missing_sdk_fails_with_safe_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import (
        FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
        FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
        FoundryAgentClientError,
    )

    secret_endpoint = "https://secret-foundry.services.ai.azure.com/api/projects/demo"
    secret_agent_id = "secret-agent-id"
    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT", secret_endpoint)
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", secret_agent_id)
    monkeypatch.setattr(
        foundry_agent_client,
        "foundry_agent_sdk_available",
        lambda: False,
    )

    with pytest.raises(FoundryAgentClientError) as exc:
        foundry_agent_client.create_foundry_agent_client(
            AppSettings(),
            enable_live=True,
        )

    message = str(exc.value)
    assert exc.value.category == FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY
    assert message == FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE
    assert secret_endpoint not in message
    assert secret_agent_id not in message
    assert "secret" not in message
    assert "token" not in message.lower()
    assert "credential" not in message.lower()


def test_foundry_agent_live_client_setup_failure_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import (
        FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE,
        FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
        FoundryAgentClientError,
    )

    class FakeCredential:
        def __init__(self) -> None:
            raise RuntimeError("secret-token raw credential failure")

    monkeypatch.setattr(
        foundry_agent_client,
        "_get_agents_client_class",
        lambda: object,
    )
    monkeypatch.setattr(
        foundry_agent_client,
        "_get_default_credential_class",
        lambda: FakeCredential,
    )

    with pytest.raises(FoundryAgentClientError) as exc:
        foundry_agent_client._create_agents_client(
            "https://secret-foundry.services.ai.azure.com/api/projects/demo"
        )

    message = str(exc.value)
    assert exc.value.category == FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY
    assert message == FOUNDRY_AGENT_CLIENT_UNAVAILABLE_MESSAGE
    assert "secret-foundry" not in message
    assert "secret-token" not in message
    assert "raw credential" not in message


def test_foundry_agent_live_client_request_failure_preserves_safe_cause() -> None:
    from src.app.services.foundry_agent_client import (
        FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE,
        FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
        AzureAiFoundryAgentLiveClient,
        FoundryAgentClientError,
        FoundryAgentRequest,
    )

    class FakeHttpResponseError(Exception):
        status_code = 404

    class FailingLiveClient(AzureAiFoundryAgentLiveClient):
        def _get_agents_client(self):
            return object()

        async def _invoke_with_client(self, agents_client, request):
            raise FakeHttpResponseError("raw endpoint and agent secret")

    client = FailingLiveClient(
        project_endpoint="https://secret-foundry.services.ai.azure.com/api/projects/demo",
        agent_id="secret-agent-id",
    )
    request = FoundryAgentRequest(
        intake_text="Fictional patient requests a refill.",
        instructions="Return JSON only.",
    )

    with pytest.raises(FoundryAgentClientError) as exc:
        asyncio.run(client.invoke_agent(request))

    assert exc.value.category == FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY
    assert str(exc.value) == FOUNDRY_AGENT_CLIENT_REQUEST_FAILED_MESSAGE
    assert isinstance(exc.value.__cause__, FakeHttpResponseError)
    assert getattr(exc.value.__cause__, "status_code") == 404
    assert "secret" not in str(exc.value)
