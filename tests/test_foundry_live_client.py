import importlib
from types import SimpleNamespace

import pytest


def test_foundry_live_client_module_imports_without_credentials() -> None:
    module = importlib.import_module("src.app.services.foundry_live_client")

    assert hasattr(module, "AzureAiFoundryLiveClient")
    assert hasattr(module, "create_foundry_live_client")


def test_foundry_live_client_exposes_structured_extraction_seam() -> None:
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    client = AzureAiFoundryLiveClient(
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo"
    )

    assert callable(client.complete_structured_extraction)


def test_foundry_live_client_fails_clearly_without_sdk_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    monkeypatch.setattr(
        foundry_live_client,
        "_create_chat_client",
        lambda project_endpoint: (_ for _ in ()).throw(
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
    monkeypatch.setattr(
        foundry_live_client,
        "_create_chat_client",
        lambda project_endpoint: fake_chat_client,
    )

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
    monkeypatch.setattr(
        foundry_live_client,
        "_create_chat_client",
        lambda project_endpoint: FakeChatClient(response=fake_response),
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
    ],
)
def test_foundry_live_client_empty_content_fails_safely(
    monkeypatch: pytest.MonkeyPatch,
    fake_response: object,
) -> None:
    from src.app.services import foundry_live_client
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

    monkeypatch.setattr(
        foundry_live_client,
        "_create_chat_client",
        lambda project_endpoint: FakeChatClient(response=fake_response),
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

    monkeypatch.setattr(
        foundry_live_client,
        "_create_chat_client",
        lambda project_endpoint: FailingChatClient(),
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
        self.response = response
        self.calls: list[dict[str, object]] = []

    def complete(self, messages: list[object], model: str) -> object:
        self.calls.append({"messages": messages, "model": model})
        return self.response


class FailingChatClient:
    def complete(self, messages: list[object], model: str) -> object:
        raise RuntimeError("private sdk marker")
