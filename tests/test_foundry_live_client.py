import importlib

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


def test_foundry_live_client_fails_clearly_without_sdk_support() -> None:
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient

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


def test_foundry_live_client_factory_does_not_construct_sdk_client() -> None:
    from src.app.services.foundry_live_client import AzureAiFoundryLiveClient
    from src.app.services.foundry_live_client import create_foundry_live_client

    client = create_foundry_live_client(
        "https://example.services.ai.azure.com/api/projects/demo"
    )

    assert isinstance(client, AzureAiFoundryLiveClient)
