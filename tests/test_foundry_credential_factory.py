import builtins
import importlib
import json
import sys
from types import SimpleNamespace

import pytest


def test_factory_module_import_does_not_import_azure_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "azure.identity":
            raise AssertionError("module import must not import azure.identity")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    module = importlib.import_module(
        "src.app.services.foundry_credential_factory"
    )

    assert hasattr(module, "FoundryCredentialFactory")


def test_default_configuration_constructs_credential_without_identity_override() -> None:
    from src.app.services.foundry_credential_factory import (
        FoundryCredentialConfiguration,
        FoundryCredentialFactory,
    )

    calls: list[dict[str, object]] = []

    class FakeCredential:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

        def get_token(self, *scopes: str) -> None:
            pytest.fail("credential factory must not request a token")

    credential = FoundryCredentialFactory(
        credential_constructor=FakeCredential
    ).create(FoundryCredentialConfiguration())

    assert isinstance(credential, FakeCredential)
    assert calls == [{}]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_blank_client_id_normalizes_to_none(value: str | None) -> None:
    from src.app.services.foundry_credential_factory import (
        FoundryCredentialConfiguration,
    )

    configuration = FoundryCredentialConfiguration(
        managed_identity_client_id=value
    )

    assert configuration.managed_identity_client_id is None


def test_user_assigned_client_id_is_trimmed_and_uses_installed_keyword() -> None:
    from src.app.services.foundry_credential_factory import (
        FoundryCredentialConfiguration,
        FoundryCredentialFactory,
    )

    calls: list[dict[str, object]] = []

    def constructor(**kwargs: object) -> object:
        calls.append(kwargs)
        return object()

    FoundryCredentialFactory(credential_constructor=constructor).create(
        FoundryCredentialConfiguration(
            managed_identity_client_id="  managed-identity-client-id  "
        )
    )

    assert calls == [
        {"managed_identity_client_id": "managed-identity-client-id"}
    ]


def test_constructor_exception_is_sanitized() -> None:
    from src.app.services.foundry_credential_factory import (
        FOUNDRY_CREDENTIAL_UNAVAILABLE_MESSAGE,
        FoundryCredentialConfiguration,
        FoundryCredentialFactory,
        FoundryCredentialFactoryError,
    )

    def explode(**kwargs: object) -> object:
        raise RuntimeError(
            "Bearer credential-secret managed-identity-client-id Traceback"
        )

    with pytest.raises(FoundryCredentialFactoryError) as exc_info:
        FoundryCredentialFactory(credential_constructor=explode).create(
            FoundryCredentialConfiguration(
                managed_identity_client_id="managed-identity-client-id"
            )
        )

    assert str(exc_info.value) == FOUNDRY_CREDENTIAL_UNAVAILABLE_MESSAGE
    assert exc_info.value.category == "credential_creation_failed"
    assert "managed-identity-client-id" not in str(exc_info.value)
    assert "Bearer" not in str(exc_info.value)
    assert "Traceback" not in str(exc_info.value)


def test_sdk_absence_fails_only_when_create_is_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.foundry_credential_factory import (
        FoundryCredentialConfiguration,
        FoundryCredentialFactory,
        FoundryCredentialFactoryError,
    )

    real_import = builtins.__import__

    def unavailable_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "azure.identity":
            raise ModuleNotFoundError("raw SDK import detail")
        return real_import(name, *args, **kwargs)

    factory = FoundryCredentialFactory()
    monkeypatch.setattr(builtins, "__import__", unavailable_import)

    with pytest.raises(FoundryCredentialFactoryError) as exc_info:
        factory.create(FoundryCredentialConfiguration())

    assert exc_info.value.category == "sdk_unavailable"
    assert "raw SDK import detail" not in str(exc_info.value)


def test_mock_application_import_is_safe_when_azure_identity_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.main as application_module

    real_import = builtins.__import__

    def unavailable_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "azure.identity":
            raise ModuleNotFoundError("azure identity unavailable")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable_import)
    monkeypatch.setitem(sys.modules, "src.app.main", application_module)

    reloaded = importlib.reload(application_module)

    assert reloaded.app is not None


def test_agent_responses_client_uses_factory_once_when_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_client
    from src.app.services.foundry_agent_client import (
        AzureAiFoundryAgentLiveClient,
    )

    configurations: list[object] = []

    class RecordingFactory:
        def create(self, configuration: object) -> object:
            configurations.append(configuration)
            return object()

    class FakeProjectClient:
        def __init__(self, **kwargs: object) -> None:
            pass

        def get_openai_client(self, **kwargs: object) -> object:
            return SimpleNamespace(responses=object())

    monkeypatch.setattr(
        foundry_agent_client,
        "_get_ai_project_client_class",
        lambda: FakeProjectClient,
    )
    client = AzureAiFoundryAgentLiveClient(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="secret-agent",
        agent_version="7",
        managed_identity_client_id="managed-identity-client-id",
        credential_factory=RecordingFactory(),
    )

    responses_clients = [client._get_responses_client() for _ in range(3)]

    assert responses_clients[0] is responses_clients[1] is responses_clients[2]
    assert len(configurations) == 1
    assert configurations[0].managed_identity_client_id == (
        "managed-identity-client-id"
    )


def test_verification_default_client_path_uses_shared_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_verification as verification
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerification,
        FoundryAgentVerificationRequest,
    )
    from src.app.services.nurse_intake_agent_instructions import (
        build_nurse_intake_agent_instructions,
    )

    configurations: list[object] = []

    class RecordingFactory:
        def create(self, configuration: object) -> object:
            configurations.append(configuration)
            return object()

    class FakeAgents:
        def get_version(self, agent_name: str, agent_version: str) -> object:
            return SimpleNamespace(
                name=agent_name,
                version=agent_version,
                definition=SimpleNamespace(
                    model="model",
                    instructions=build_nurse_intake_agent_instructions(),
                ),
            )

    class FakeProjectClient:
        def __init__(self, **kwargs: object) -> None:
            self.agents = FakeAgents()

    monkeypatch.setattr(
        verification,
        "FoundryCredentialFactory",
        RecordingFactory,
    )
    monkeypatch.setattr(
        verification,
        "_get_ai_project_client_class",
        lambda: FakeProjectClient,
    )
    request = FoundryAgentVerificationRequest(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="agent",
        agent_version="7",
        model_deployment_name="model",
        instructions=build_nurse_intake_agent_instructions(),
        managed_identity_client_id="managed-identity-client-id",
    )

    result = FoundryAgentVerification().verify(request)

    assert result.ok is True
    assert len(configurations) == 1
    assert configurations[0].managed_identity_client_id == (
        "managed-identity-client-id"
    )
    assert "managed-identity-client-id" not in json.dumps(result.to_json_dict())


def test_deployment_default_client_path_uses_shared_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_deployment as deployment
    from src.app.services.foundry_agent_deployment import (
        FoundryAgentDeployment,
        FoundryAgentDeploymentRequest,
    )

    configurations: list[object] = []

    class RecordingFactory:
        def create(self, configuration: object) -> object:
            configurations.append(configuration)
            return object()

    class FakeAgents:
        def list_versions(self, agent_name: str, **kwargs: object):
            return iter([])

        def create_version(self, **kwargs: object) -> object:
            return SimpleNamespace(name=kwargs["agent_name"], version="1")

    class FakeProjectClient:
        def __init__(self, **kwargs: object) -> None:
            self.agents = FakeAgents()

    monkeypatch.setattr(
        deployment,
        "FoundryCredentialFactory",
        RecordingFactory,
    )
    monkeypatch.setattr(
        deployment,
        "_get_ai_project_client_class",
        lambda: FakeProjectClient,
    )
    request = FoundryAgentDeploymentRequest(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="agent",
        model_deployment_name="model",
        instructions="instructions",
        managed_identity_client_id="managed-identity-client-id",
    )

    result = FoundryAgentDeployment(
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs)
    ).provision(request)

    assert result.ok is True
    assert len(configurations) == 1
    assert configurations[0].managed_identity_client_id == (
        "managed-identity-client-id"
    )
    assert "managed-identity-client-id" not in json.dumps(result.to_json_dict())


def test_verification_maps_missing_identity_sdk_to_existing_safe_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_verification as verification
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerification,
        FoundryAgentVerificationRequest,
    )
    from src.app.services.foundry_credential_factory import (
        FoundryCredentialFactoryError,
    )

    class UnavailableFactory:
        def create(self, configuration: object) -> object:
            raise FoundryCredentialFactoryError(category="sdk_unavailable")

    monkeypatch.setattr(
        verification,
        "FoundryCredentialFactory",
        UnavailableFactory,
    )
    request = FoundryAgentVerificationRequest(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="agent",
        agent_version="7",
        model_deployment_name="model",
        instructions="instructions",
    )

    result = FoundryAgentVerification().verify(request)

    assert result.category == "sdk_unavailable"
    assert "secret.example" not in json.dumps(result.to_json_dict())


def test_deployment_maps_missing_identity_sdk_to_existing_safe_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services import foundry_agent_deployment as deployment
    from src.app.services.foundry_agent_deployment import (
        FoundryAgentDeployment,
        FoundryAgentDeploymentRequest,
    )
    from src.app.services.foundry_credential_factory import (
        FoundryCredentialFactoryError,
    )

    class UnavailableFactory:
        def create(self, configuration: object) -> object:
            raise FoundryCredentialFactoryError(category="sdk_unavailable")

    monkeypatch.setattr(
        deployment,
        "FoundryCredentialFactory",
        UnavailableFactory,
    )
    request = FoundryAgentDeploymentRequest(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="agent",
        model_deployment_name="model",
        instructions="instructions",
    )

    result = FoundryAgentDeployment().provision(request)

    assert result.category == "sdk_unavailable"
    assert "secret.example" not in json.dumps(result.to_json_dict())
