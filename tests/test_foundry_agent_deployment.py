import json
from types import SimpleNamespace

import pytest

from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_instructions,
)


class FakeAgents:
    def __init__(
        self,
        versions: list[SimpleNamespace] | None = None,
        *,
        list_error: Exception | None = None,
        create_error: Exception | None = None,
    ) -> None:
        self.versions = versions or []
        self.list_error = list_error
        self.create_error = create_error
        self.list_version_calls: list[dict[str, object]] = []
        self.create_calls: list[dict[str, object]] = []

    def list_versions(self, agent_name: str, **kwargs: object):
        self.list_version_calls.append({"agent_name": agent_name, **kwargs})
        if self.list_error is not None:
            raise self.list_error
        return iter(self.versions)

    def create_version(self, **kwargs: object) -> SimpleNamespace:
        self.create_calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error
        created = SimpleNamespace(
            name=kwargs["agent_name"],
            version=str(len(self.versions) + 1),
            definition=kwargs["definition"],
        )
        self.versions.insert(0, created)
        return created


class FakeProjectClient:
    def __init__(self, versions: list[SimpleNamespace] | None = None) -> None:
        self.agents = FakeAgents(versions)

    def get_openai_client(self) -> None:
        pytest.fail("provisioning must not create an invocation client")


def _request():
    from src.app.services.foundry_agent_deployment import (
        FoundryAgentDeploymentRequest,
    )

    return FoundryAgentDeploymentRequest(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="configured-agent",
        model_deployment_name="gpt-demo",
        instructions=build_nurse_intake_agent_instructions(),
    )


def _version(*, model: str = "gpt-demo", instructions: str | None = None):
    return SimpleNamespace(
        name="configured-agent",
        version="7",
        definition=SimpleNamespace(
            model=model,
            instructions=instructions or build_nurse_intake_agent_instructions(),
        ),
    )


def _deployment(client: FakeProjectClient, endpoints: list[str]):
    from src.app.services.foundry_agent_deployment import FoundryAgentDeployment

    def client_factory(endpoint: str) -> FakeProjectClient:
        endpoints.append(endpoint)
        return client

    return FoundryAgentDeployment(
        project_client_factory=client_factory,
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )


def test_provision_creates_missing_agent_with_configured_definition() -> None:
    client = FakeProjectClient()
    endpoints: list[str] = []
    deployment = _deployment(client, endpoints)

    result = deployment.provision(_request())

    assert endpoints == ["https://secret.example/api/projects/demo"]
    assert client.agents.list_version_calls == [
        {"agent_name": "configured-agent", "limit": 1, "order": "desc"}
    ]
    definition = client.agents.create_calls[0]["definition"]
    assert definition.model == "gpt-demo"
    assert definition.instructions == build_nurse_intake_agent_instructions()
    assert result.ok is True
    assert result.agent_created is True
    assert result.agent_reused is False
    assert result.agent_updated is False
    assert result.instruction_version == NURSE_INTAKE_AGENT_INSTRUCTION_VERSION


def test_provision_treats_list_versions_404_as_missing_and_creates_once() -> None:
    client = FakeProjectClient()
    client.agents = FakeAgents(list_error=StatusCodeError(404))

    result = _deployment(client, []).provision(_request())

    assert len(client.agents.create_calls) == 1
    assert result.ok is True
    assert result.agent_created is True
    assert result.agent_reused is False
    assert result.agent_updated is False
    assert result.agent_invoked is False


def test_provision_reuses_identical_latest_version_without_creating_duplicate() -> None:
    existing = _version()
    client = FakeProjectClient([existing])
    deployment = _deployment(client, [])

    first = deployment.provision(_request())
    second = deployment.provision(_request())

    assert client.agents.create_calls == []
    assert first.agent_reused is True
    assert second.agent_reused is True
    assert first.agent_version_present is True
    assert second.agent_version_present is True


@pytest.mark.parametrize(
    "existing",
    [
        _version(model="older-model"),
        _version(instructions="older centralized instructions"),
    ],
)
def test_provision_creates_one_updated_version_when_definition_changed(
    existing: SimpleNamespace,
) -> None:
    client = FakeProjectClient([existing])
    deployment = _deployment(client, [])

    first = deployment.provision(_request())
    second = deployment.provision(_request())

    assert len(client.agents.create_calls) == 1
    assert first.agent_updated is True
    assert first.agent_created is False
    assert second.agent_reused is True


class StatusCodeError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(
            "Bearer secret-token https://secret.example patient prompt Traceback"
        )
        self.status_code = status_code


@pytest.mark.parametrize(
    ("status_code", "expected_category"),
    [
        (401, "authentication_or_authorization_failed"),
        (403, "authentication_or_authorization_failed"),
        (500, "agent_provisioning_failed"),
    ],
)
def test_provision_classifies_errors_without_raw_details(
    status_code: int,
    expected_category: str,
) -> None:
    class FailingAgents(FakeAgents):
        def list_versions(self, agent_name: str, **kwargs: object):
            raise StatusCodeError(status_code)

    client = FakeProjectClient()
    client.agents = FailingAgents()
    result = _deployment(client, []).provision(_request())

    serialized = json.dumps(result.to_json_dict())
    assert result.category == expected_category
    for unsafe in (
        "secret-token",
        "secret.example",
        "patient prompt",
        "Traceback",
    ):
        assert unsafe not in serialized


@pytest.mark.parametrize("status_code", [401, 403])
def test_provision_classifies_create_version_auth_errors_without_success_actions(
    status_code: int,
) -> None:
    client = FakeProjectClient()
    client.agents = FakeAgents(create_error=StatusCodeError(status_code))

    result = _deployment(client, []).provision(_request())

    assert result.category == "authentication_or_authorization_failed"
    assert result.agent_created is False
    assert result.agent_reused is False
    assert result.agent_updated is False
    assert result.agent_invoked is False
    _assert_sanitized(result.to_json_dict())


def test_provision_classifies_create_version_server_error_without_invoking() -> None:
    client = FakeProjectClient()
    client.agents = FakeAgents(create_error=StatusCodeError(500))

    result = _deployment(client, []).provision(_request())

    assert result.category == "agent_provisioning_failed"
    assert result.agent_created is False
    assert result.agent_reused is False
    assert result.agent_updated is False
    assert result.agent_invoked is False
    _assert_sanitized(result.to_json_dict())


def _assert_sanitized(payload: dict[str, object]) -> None:
    serialized = json.dumps(payload)
    for unsafe in (
        "secret-token",
        "secret.example",
        "patient prompt",
        "Traceback",
    ):
        assert unsafe not in serialized
