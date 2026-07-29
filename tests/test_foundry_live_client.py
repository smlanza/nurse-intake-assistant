import asyncio
import importlib
import inspect
import json
from types import SimpleNamespace

import pytest


def test_foundry_live_client_module_imports_without_credentials() -> None:
    module = importlib.import_module("src.app.services.foundry_live_client")

    assert hasattr(module, "AzureAiFoundryLiveClient")
    assert hasattr(module, "create_foundry_live_client")
    assert hasattr(module, "AzureOpenAiEndpointLiveClient")
    assert hasattr(module, "create_azure_openai_live_client")


def test_foundry_live_client_exposes_structured_extraction_seam() -> None:
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    client = AzureAiFoundryLiveClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo"
    )

    assert callable(client.complete_structured_extraction)


def test_foundry_live_client_declares_endpoint_contract() -> None:
    from src.app.services import foundry_live_client

    assert foundry_live_client.FOUNDRY_LIVE_CLIENT_MODE == "foundry-project-endpoint"
    assert (
        foundry_live_client.FOUNDRY_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE
        == "services.ai.azure.com"
    )
    assert (
        foundry_live_client.AZURE_OPENAI_LIVE_CLIENT_MODE
        == "azure-openai-endpoint"
    )
    assert (
        foundry_live_client.AZURE_OPENAI_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE
        == "openai.azure.com"
    )


def test_foundry_project_endpoint_uses_one_lazy_project_openai_client_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    project_endpoint = (
        "https://example.services.ai.azure.com/api/projects/fictional-project"
    )
    events: list[object] = []

    class FakeCredential:
        def __init__(self) -> None:
            events.append("credential_created")

        def close(self) -> None:
            events.append("credential_closed")

    class FakeCompletions:
        def create(self, *, messages: list[object], model: str) -> object:
            events.append(("model_request", messages, model))
            return {
                "choices": [
                    {"message": {"content": '{"summary": "project client ok"}'}}
                ]
            }

    class FakeOpenAIClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=FakeCompletions())

        def close(self) -> None:
            events.append("openai_client_closed")

    openai_client = FakeOpenAIClient()

    class FakeAIProjectClient:
        def __init__(self, *, endpoint: str, credential: object) -> None:
            events.append(("project_client_created", endpoint, credential))

        def get_openai_client(self) -> object:
            events.append("get_openai_client")
            return openai_client

        def close(self) -> None:
            events.append("project_client_closed")

    monkeypatch.setattr(
        foundry_live_client,
        "_get_default_credential_class",
        lambda: FakeCredential,
    )
    monkeypatch.setattr(
        foundry_live_client,
        "_get_ai_project_client_class",
        lambda: FakeAIProjectClient,
        raising=False,
    )
    client = AzureAiFoundryLiveClient(project_endpoint=project_endpoint)

    assert events == []

    result = client.complete_structured_extraction(
        prompt="Return JSON only.",
        model_deployment_name="configured-deployment",
    )
    client.close()

    assert result == '{"summary": "project client ok"}'
    assert "ChatCompletionsClient" not in inspect.getsource(foundry_live_client)
    assert events[0] == "credential_created"
    assert events[1][0:2] == ("project_client_created", project_endpoint)
    assert isinstance(events[1][2], FakeCredential)
    assert events.count("get_openai_client") == 1
    model_requests = [
        event
        for event in events
        if isinstance(event, tuple) and event[0] == "model_request"
    ]
    assert len(model_requests) == 1
    assert model_requests[0][2] == "configured-deployment"
    assert model_requests[0][1][1]["content"] == "Return JSON only."
    assert events[-3:] == [
        "openai_client_closed",
        "project_client_closed",
        "credential_closed",
    ]


def test_azure_openai_live_client_exposes_structured_extraction_seam() -> None:
    from src.app.services.foundry_live_client import AzureOpenAiEndpointLiveClient

    client = AzureOpenAiEndpointLiveClient(
        azure_openai_endpoint="https://example-openai-resource.openai.azure.com/"
    )

    assert callable(client.complete_structured_extraction)


def test_foundry_live_client_fails_clearly_without_sdk_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    monkeypatch.setattr(
        foundry_live_client,
        "_get_ai_project_client_class",
        lambda: (_ for _ in ()).throw(
            RuntimeError(
                "Azure AI Foundry live client is not configured or SDK support "
                "is not available."
            )
        ),
    )

    client = AzureAiFoundryLiveClient(
        project_endpoint="https://secret-endpoint.example.invalid/api/projects/demo"
    )

    with pytest.raises(RuntimeError) as exc:
        client.complete_structured_extraction(
            prompt="Return JSON only.",
            model_deployment_name="secret-deployment",
        )

    message = str(exc.value)
    assert (
        message
        == "Azure AI Foundry live client is not configured or SDK support is not available."
    )
    assert "secret-endpoint" not in message
    assert "secret-deployment" not in message


def test_azure_openai_live_client_fails_clearly_without_sdk_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureOpenAiEndpointLiveClient

    monkeypatch.setattr(
        foundry_live_client,
        "_create_azure_openai_chat_client",
        lambda azure_openai_endpoint: (_ for _ in ()).throw(
            RuntimeError(
                "Azure OpenAI endpoint live client is not configured or SDK "
                "support is not available."
            )
        ),
    )

    client = AzureOpenAiEndpointLiveClient(
        azure_openai_endpoint="https://secret-openai-resource.openai.azure.com/"
    )

    with pytest.raises(RuntimeError) as exc:
        client.complete_structured_extraction(
            prompt="Return JSON only.",
            model_deployment_name="secret-deployment",
        )

    message = str(exc.value)
    assert (
        message
        == "Azure OpenAI endpoint live client is not configured or SDK support is not available."
    )
    assert "secret-openai-resource" not in message
    assert "secret-deployment" not in message


def test_foundry_live_client_returns_content_from_fake_chat_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    fake_chat_client = FakeChatClient(
        response={
            "choices": [
                {
                    "message": {
                        "content": '{"summary": "ok"}',
                    }
                }
            ]
        }
    )
    _install_foundry_project_fakes(monkeypatch, foundry_live_client, fake_chat_client)

    client = AzureAiFoundryLiveClient(
        project_endpoint="https://secret-endpoint.example.invalid/api/projects/demo"
    )

    result = client.complete_structured_extraction(
        prompt="secret prompt marker",
        model_deployment_name="secret-deployment",
    )

    assert result == '{"summary": "ok"}'
    assert fake_chat_client.calls == [
        {
            "messages": [
                {
                    "role": "system",
                    "content": foundry_live_client.FOUNDRY_SYSTEM_MESSAGE,
                },
                {
                    "role": "user",
                    "content": "secret prompt marker",
                },
            ],
            "model": "secret-deployment",
        }
    ]


def test_foundry_project_response_reaches_existing_service_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_ai_service import FoundryAiService
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    response_text = json.dumps(
        {
            "patient": {
                "name": "Fictional Patient",
                "date_of_birth": "2000-01-01",
                "callback_number": None,
            },
            "reason_for_calling": "medication question",
            "symptoms": ["fatigue"],
            "summary": "Fictional patient reports fatigue.",
            "urgency": "Routine",
            "urgency_rationale": "No urgent symptoms were described.",
            "advisory_disclaimer": (
                "Advisory urgency only; nurse review and clinical judgment "
                "are required."
            ),
            "missing_fields": ["patient.callback_number"],
            "uncertain_fields": [],
        }
    )
    openai_client = FakeChatClient(
        response={"choices": [{"message": {"content": response_text}}]}
    )
    _install_foundry_project_fakes(
        monkeypatch,
        foundry_live_client,
        openai_client,
    )
    live_client = AzureAiFoundryLiveClient(
        project_endpoint=(
            "https://example.services.ai.azure.com/api/projects/fictional-project"
        )
    )
    service = FoundryAiService(
        project_endpoint=live_client.project_endpoint,
        model_deployment_name="configured-deployment",
        client=live_client,
    )

    extraction = asyncio.run(service.extract_and_summarize("Fictional intake."))
    live_client.close()

    assert extraction.summary == "Fictional patient reports fatigue."
    assert len(openai_client.calls) == 1
    assert openai_client.calls[0]["model"] == "configured-deployment"


def test_azure_openai_live_client_returns_content_from_fake_chat_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureOpenAiEndpointLiveClient

    fake_chat_client = FakeAzureOpenAiClient(
        response={
            "choices": [
                {
                    "message": {
                        "content": '{"summary": "azure ok"}',
                    }
                }
            ]
        }
    )
    monkeypatch.setattr(
        foundry_live_client,
        "_create_azure_openai_chat_client",
        lambda azure_openai_endpoint: fake_chat_client,
    )

    client = AzureOpenAiEndpointLiveClient(
        azure_openai_endpoint="https://secret-openai-resource.openai.azure.com/"
    )

    result = client.complete_structured_extraction(
        prompt="secret prompt marker",
        model_deployment_name="secret-deployment",
    )

    assert result == '{"summary": "azure ok"}'
    assert fake_chat_client.chat.completions.calls[0]["model"] == "secret-deployment"
    assert (
        fake_chat_client.chat.completions.calls[0]["messages"][1]["content"]
        == "secret prompt marker"
    )


def test_azure_openai_chat_client_uses_bearer_token_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client

    constructed_clients: list[dict[str, object]] = []
    token_provider = object()

    class FakeOpenAI:
        def __init__(self, **kwargs: object) -> None:
            constructed_clients.append(kwargs)

    class FakeCredential:
        pass

    def fake_get_bearer_token_provider(credential: object, scope: str) -> object:
        assert isinstance(credential, FakeCredential)
        assert scope == "https://cognitiveservices.azure.com/.default"
        return token_provider

    monkeypatch.setattr(
        foundry_live_client,
        "_get_openai_client_class",
        lambda: FakeOpenAI,
    )
    monkeypatch.setattr(
        foundry_live_client,
        "_get_default_credential_class",
        lambda: FakeCredential,
    )
    monkeypatch.setattr(
        foundry_live_client,
        "_get_bearer_token_provider_factory",
        lambda: fake_get_bearer_token_provider,
    )

    foundry_live_client._create_azure_openai_chat_client(
        "https://secret-openai-resource.openai.azure.com/"
    )

    assert constructed_clients == [
        {
            "base_url": "https://secret-openai-resource.openai.azure.com/openai/v1/",
            "api_key": token_provider,
        }
    ]
    assert "azure_endpoint" not in constructed_clients[0]
    assert "azure_ad_token_provider" not in constructed_clients[0]
    assert "api_version" not in constructed_clients[0]
    assert "credential" not in constructed_clients[0]


@pytest.mark.parametrize(
    "endpoint,expected_base_url",
    [
        (
            "https://example-openai-resource.openai.azure.com",
            "https://example-openai-resource.openai.azure.com/openai/v1/",
        ),
        (
            "https://example-openai-resource.openai.azure.com/",
            "https://example-openai-resource.openai.azure.com/openai/v1/",
        ),
        (
            "https://example-openai-resource.openai.azure.com/openai/v1",
            "https://example-openai-resource.openai.azure.com/openai/v1/",
        ),
        (
            "https://example-openai-resource.openai.azure.com/openai/v1/",
            "https://example-openai-resource.openai.azure.com/openai/v1/",
        ),
    ],
)
def test_azure_openai_v1_base_url_normalization(
    endpoint: str,
    expected_base_url: str,
) -> None:
    from src.app.services import foundry_live_client

    assert (
        foundry_live_client.normalize_azure_openai_v1_base_url(endpoint)
        == expected_base_url
    )


def test_azure_openai_v1_base_url_rejects_unknown_path_safely() -> None:
    from src.app.services import foundry_live_client

    with pytest.raises(ValueError) as exc:
        foundry_live_client.normalize_azure_openai_v1_base_url(
            "https://secret-openai-resource.openai.azure.com/private/path"
        )

    message = str(exc.value)
    assert message == "Unsupported Azure OpenAI endpoint path shape."
    assert "secret-openai-resource" not in message


def test_azure_openai_token_provider_setup_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client

    class FakeCredential:
        pass

    def failing_get_bearer_token_provider(credential: object, scope: str) -> object:
        raise RuntimeError("raw token provider secret-token")

    monkeypatch.setattr(
        foundry_live_client,
        "_get_default_credential_class",
        lambda: FakeCredential,
    )
    monkeypatch.setattr(
        foundry_live_client,
        "_get_bearer_token_provider_factory",
        lambda: failing_get_bearer_token_provider,
    )

    with pytest.raises(RuntimeError) as exc:
        foundry_live_client._create_azure_openai_bearer_token_provider()

    message = str(exc.value)
    assert message == "Azure OpenAI endpoint token provider setup failed."
    assert "secret-token" not in message


def test_foundry_live_client_supports_object_chat_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    fake_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content='{"summary": "object ok"}')
            )
        ]
    )
    _install_foundry_project_fakes(
        monkeypatch,
        foundry_live_client,
        FakeChatClient(response=fake_response),
    )

    client = AzureAiFoundryLiveClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo"
    )

    result = client.complete_structured_extraction(
        prompt="Return JSON only.",
        model_deployment_name="intake-extraction",
    )

    assert result == '{"summary": "object ok"}'


@pytest.mark.parametrize(
    "fake_response",
    [
        {"choices": []},
        {"choices": [{"message": {"content": ""}}]},
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": 7}}]},
        {"unsupported": "response shape"},
    ],
)
def test_foundry_live_client_empty_content_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    fake_response: object,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    _install_foundry_project_fakes(
        monkeypatch,
        foundry_live_client,
        FakeChatClient(response=fake_response),
    )

    client = AzureAiFoundryLiveClient(
        project_endpoint="https://secret-endpoint.example.invalid/api/projects/demo"
    )

    with pytest.raises(RuntimeError) as exc:
        client.complete_structured_extraction(
            prompt="secret prompt marker",
            model_deployment_name="secret-deployment",
        )

    message = str(exc.value)
    assert message == "Azure AI Foundry live client returned no response content."
    assert "secret-endpoint" not in message
    assert "secret-deployment" not in message
    assert "secret prompt marker" not in message


def test_foundry_live_client_sdk_exception_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    _install_foundry_project_fakes(
        monkeypatch,
        foundry_live_client,
        FailingChatClient(),
    )

    client = AzureAiFoundryLiveClient(
        project_endpoint="https://secret-endpoint.example.invalid/api/projects/demo"
    )

    with pytest.raises(RuntimeError) as exc:
        client.complete_structured_extraction(
            prompt="secret prompt marker",
            model_deployment_name="secret-deployment",
        )

    message = str(exc.value)
    assert message == "Azure AI Foundry live client request failed."
    assert "secret-endpoint" not in message
    assert "secret-deployment" not in message
    assert "secret prompt marker" not in message
    assert "private sdk marker" not in message


def test_foundry_live_client_factory_does_not_construct_sdk_client() -> None:
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient
    from src.app.services.foundry_live_client import create_foundry_live_client

    client = create_foundry_live_client(
        "https://example.services.ai.azure.com/api/projects/demo"
    )

    assert isinstance(client, AzureAiFoundryLiveClient)


class FakeChatClient:
    def __init__(self, response: object) -> None:
        completions = FakeAzureOpenAiCompletions(response=response)
        self.chat = SimpleNamespace(completions=completions)
        self.calls = completions.calls


class FakeAzureOpenAiClient:
    def __init__(self, response: object) -> None:
        self.chat = SimpleNamespace(
            completions=FakeAzureOpenAiCompletions(response=response)
        )


class FakeAzureOpenAiCompletions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, messages: list[object], model: str) -> object:
        self.calls.append({"messages": messages, "model": model})
        return self.response


class FailingChatClient:
    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)

    def create(self, messages: list[object], model: str) -> object:
        raise RuntimeError("private sdk marker")


def _install_foundry_project_fakes(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    openai_client: object,
) -> None:
    class FakeCredential:
        pass

    class FakeAIProjectClient:
        def __init__(self, *, endpoint: str, credential: object) -> None:
            self.endpoint = endpoint
            self.credential = credential

        def get_openai_client(self) -> object:
            return openai_client

    monkeypatch.setattr(
        module,
        "_get_default_credential_class",
        lambda: FakeCredential,
    )
    monkeypatch.setattr(
        module,
        "_get_ai_project_client_class",
        lambda: FakeAIProjectClient,
    )
