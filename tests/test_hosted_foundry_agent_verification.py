import inspect
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.app.services import hosted_foundry_agent_verification as hosted
from src.app.services.nurse_intake_agent_instructions import (
    build_nurse_intake_agent_instructions,
)


PROJECT_ENDPOINT = "https://secret.example/api/projects/demo"
STABLE_ENDPOINT = (
    "https://secret.example/api/projects/demo/agents/configured-agent/"
    "endpoint/protocols/openai"
)
AGENT_NAME = "configured-agent"
AGENT_VERSION = "7"
MODEL_NAME = "gpt-demo"


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(
            "Bearer secret-token tenant-secret https://secret.example raw SDK payload"
        )
        self.status_code = status_code


def _agent(
    *,
    protocols: object = ("responses",),
    rules: object | None = None,
) -> SimpleNamespace:
    if rules is None:
        rules = [
            SimpleNamespace(
                type="FixedRatio",
                agent_version=AGENT_VERSION,
                traffic_percentage=100,
            )
        ]
    return SimpleNamespace(
        id="secret-agent-resource-id",
        instance_identity=SimpleNamespace(client_id="secret-client-id"),
        agent_endpoint=SimpleNamespace(
            protocols=protocols,
            version_selector=SimpleNamespace(version_selection_rules=rules),
        ),
    )


def _version(
    *,
    name: str = AGENT_NAME,
    version: str = AGENT_VERSION,
    model: str = MODEL_NAME,
    instructions: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        version=version,
        definition=SimpleNamespace(
            model=model,
            instructions=instructions or build_nurse_intake_agent_instructions(),
        ),
    )


class FakeAgents:
    def __init__(
        self,
        *,
        agent: object | None = None,
        version: object | None = None,
        get_error: Exception | None = None,
        version_error: Exception | None = None,
    ) -> None:
        self.agent = agent if agent is not None else _agent()
        self.version = version if version is not None else _version()
        self.get_error = get_error
        self.version_error = version_error
        self.get_calls: list[str] = []
        self.get_version_calls: list[tuple[str, str]] = []

    def get(self, agent_name: str) -> object:
        self.get_calls.append(agent_name)
        if self.get_error:
            raise self.get_error
        return self.agent

    def get_version(self, agent_name: str, agent_version: str) -> object:
        self.get_version_calls.append((agent_name, agent_version))
        if self.version_error:
            raise self.version_error
        return self.version

    def create_version(self, **_kwargs: object) -> None:
        pytest.fail("hosted verification must never provision an agent version")

    def update(self, **_kwargs: object) -> None:
        pytest.fail("hosted verification must never update an agent")

    def delete(self, **_kwargs: object) -> None:
        pytest.fail("hosted verification must never delete an agent")


class FakeProjectClient:
    def __init__(self, agents: object) -> None:
        self.agents = agents

    def get_openai_client(self, **_kwargs: object) -> None:
        pytest.fail("hosted verification must never create an inference client")

    def deploy(self, **_kwargs: object) -> None:
        pytest.fail("hosted verification must never deploy")


@pytest.fixture
def verification_request() -> hosted.HostedFoundryAgentVerificationRequest:
    return hosted.HostedFoundryAgentVerificationRequest(
        mode="live",
        project_endpoint=PROJECT_ENDPOINT,
        stable_agent_endpoint=STABLE_ENDPOINT,
        agent_name=AGENT_NAME,
        agent_version=AGENT_VERSION,
        model_deployment_name=MODEL_NAME,
        instructions=build_nurse_intake_agent_instructions(),
    )


def _verifier(
    agents: object | None = None,
    *,
    credential_factory=None,
    project_client_factory=None,
    environment: dict[str, object] | None = None,
):
    if environment is None:
        environment = {
            "WEBSITE_INSTANCE_ID": "secret-instance-id",
            "IDENTITY_ENDPOINT": "http://secret.identity.endpoint",
            "IDENTITY_HEADER": "secret-identity-header",
        }
    credential_factory = credential_factory or (lambda: object())
    project_client_factory = project_client_factory or (
        lambda _endpoint, _credential: FakeProjectClient(agents or FakeAgents())
    )
    return hosted.HostedFoundryAgentVerification(
        credential_factory=credential_factory,
        project_client_factory=project_client_factory,
        environment_reader=environment.get,
        sdk_available=lambda: True,
    )


def test_check_validates_without_credential_client_environment_or_azure(
    verification_request,
) -> None:
    verifier = hosted.HostedFoundryAgentVerification(
        credential_factory=lambda: pytest.fail("check must not create a credential"),
        project_client_factory=lambda *_args: pytest.fail("check must not create a client"),
        environment_reader=lambda _name: pytest.fail("check must not read hosted env"),
        sdk_available=lambda: True,
    )

    result = verifier.check(replace(verification_request, mode="check"))

    assert result.ok is True
    assert result.mode == "check"
    assert result.category == "success"
    assert result.local_contract_validated is True
    assert result.hosted_environment_present is False
    assert result.managed_identity_attempted is False
    assert result.project_access_verified is False
    assert result.agent_invocation_attempted is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_endpoint", ""),
        ("stable_agent_endpoint", None),
        ("stable_agent_endpoint", "https://other.example/agent"),
        ("agent_name", ""),
        ("agent_version", " "),
        ("model_deployment_name", ""),
        ("instructions", "different instructions"),
        ("mode", "what-if"),
    ],
)
def test_invalid_configuration_fails_before_factories(
    verification_request, field: str, value: object
) -> None:
    verifier = hosted.HostedFoundryAgentVerification(
        credential_factory=lambda: pytest.fail("invalid config must stop first"),
        project_client_factory=lambda *_args: pytest.fail("invalid config must stop first"),
        environment_reader=lambda _name: pytest.fail("invalid config must stop first"),
        sdk_available=lambda: True,
    )

    result = verifier.verify(replace(verification_request, **{field: value}))

    assert result.category == "missing_configuration"
    assert result.local_contract_validated is False
    assert result.managed_identity_attempted is False


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"WEBSITE_INSTANCE_ID": "instance"},
        {"IDENTITY_ENDPOINT": "http://identity"},
    ],
)
def test_live_requires_intended_hosted_managed_identity_environment(
    verification_request, environment: dict[str, str]
) -> None:
    result = _verifier(environment=environment).verify(verification_request)

    assert result.category == "not_running_in_hosted_environment"
    assert result.hosted_environment_present is False
    assert result.managed_identity_attempted is False


@pytest.mark.parametrize("identity_header", [None, "", "   ", object()])
def test_missing_or_blank_identity_header_stops_before_credential_construction(
    verification_request, identity_header: object
) -> None:
    credential_calls: list[bool] = []
    environment = {
        "WEBSITE_INSTANCE_ID": "secret-instance-id",
        "IDENTITY_ENDPOINT": "http://secret.identity.endpoint",
        "IDENTITY_HEADER": identity_header,
    }
    verifier = _verifier(
        environment=environment,
        credential_factory=lambda: credential_calls.append(True),
        project_client_factory=lambda *_args: pytest.fail(
            "invalid hosted environment must stop before client creation"
        ),
    )

    result = verifier.verify(verification_request)

    assert result.category == "not_running_in_hosted_environment"
    assert result.hosted_environment_present is False
    assert result.managed_identity_attempted is False
    assert credential_calls == []


def test_complete_hosted_environment_continues_without_serializing_identity_header(
    verification_request,
) -> None:
    sensitive_header = "super-secret-identity-header-value"
    result = _verifier(
        environment={
            "WEBSITE_INSTANCE_ID": "secret-instance-id",
            "IDENTITY_ENDPOINT": "http://secret.identity.endpoint",
            "IDENTITY_HEADER": sensitive_header,
        }
    ).verify(verification_request)

    serialized = json.dumps(result.to_json_dict())
    assert result.ok is True
    assert result.hosted_environment_present is True
    assert result.managed_identity_attempted is True
    assert sensitive_header not in serialized


def test_live_uses_injected_managed_identity_only_factory(verification_request) -> None:
    credentials: list[object] = []
    client_arguments: list[tuple[str, object]] = []

    def credential_factory() -> object:
        credential = object()
        credentials.append(credential)
        return credential

    def project_client_factory(endpoint: str, credential: object) -> object:
        client_arguments.append((endpoint, credential))
        return FakeProjectClient(FakeAgents())

    result = _verifier(
        credential_factory=credential_factory,
        project_client_factory=project_client_factory,
    ).verify(verification_request)

    assert result.ok is True
    assert len(credentials) == 1
    assert client_arguments == [(PROJECT_ENDPOINT, credentials[0])]
    assert result.managed_identity_attempted is True
    assert result.managed_identity_authenticated is True


def test_default_credential_factory_is_system_assigned_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class ManagedIdentityCredential:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        hosted,
        "_get_managed_identity_credential_class",
        lambda: ManagedIdentityCredential,
    )

    credential = hosted.create_system_assigned_managed_identity_credential()

    assert isinstance(credential, ManagedIdentityCredential)
    assert calls == [{}]
    source = inspect.getsource(hosted)
    assert "DefaultAzureCredential" not in source
    assert "AzureCliCredential" not in source
    assert "EnvironmentCredential" not in source


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_and_authorization_failures_are_sanitized(
    verification_request, status: int
) -> None:
    result = _verifier(FakeAgents(get_error=StatusError(status))).verify(
        verification_request
    )

    serialized = json.dumps(result.to_json_dict())
    assert result.category == "authentication_or_authorization_failed"
    assert result.managed_identity_attempted is True
    assert result.managed_identity_authenticated is False
    for unsafe in ("secret-token", "tenant-secret", "secret.example", "raw SDK"):
        assert unsafe not in serialized


def test_managed_identity_unavailable_is_sanitized(verification_request) -> None:
    class CredentialUnavailableError(Exception):
        pass

    def unavailable() -> object:
        raise CredentialUnavailableError("IDENTITY_ENDPOINT secret-token")

    result = _verifier(credential_factory=unavailable).verify(verification_request)

    assert result.category == "managed_identity_unavailable"
    assert result.managed_identity_attempted is True
    assert result.managed_identity_authenticated is False
    assert "secret" not in json.dumps(result.to_json_dict())


def test_project_access_failure_stops_before_version_lookup(verification_request) -> None:
    agents = FakeAgents(get_error=RuntimeError("raw project failure secret"))

    result = _verifier(agents).verify(verification_request)

    assert result.category == "project_access_failed"
    assert result.project_access_verified is False
    assert agents.get_version_calls == []


def test_missing_agent_fails_safely(verification_request) -> None:
    agents = FakeAgents(get_error=StatusError(404))

    result = _verifier(agents).verify(verification_request)

    assert result.category == "agent_not_found"
    assert result.project_access_verified is True
    assert result.agent_present is False
    assert agents.get_version_calls == []


def test_missing_configured_version_fails_safely(verification_request) -> None:
    agents = FakeAgents(version_error=StatusError(404))

    result = _verifier(agents).verify(verification_request)

    assert result.category == "configured_version_not_found"
    assert result.agent_present is True
    assert result.configured_version_present is False


def test_exact_configured_version_and_existing_contract_are_verified(
    verification_request,
) -> None:
    agents = FakeAgents()

    result = _verifier(agents).verify(verification_request)

    assert agents.get_calls == [AGENT_NAME]
    assert agents.get_version_calls == [(AGENT_NAME, AGENT_VERSION)]
    assert result.ok is True
    assert result.category == "success"
    assert result.project_access_verified is True
    assert result.agent_present is True
    assert result.configured_version_present is True
    assert result.agent_contract_verified is True
    assert result.agent_invocation_attempted is False
    assert result.azure_mutation_made is False
    assert result.recommended_next_step == (
        "Run the separate fictional-data hosted agent invocation."
    )


@pytest.mark.parametrize(
    ("agents", "expected"),
    [
        (FakeAgents(version=_version(model="other-model")), "agent_contract_invalid"),
        (
            FakeAgents(
                agent=_agent(
                    rules=[
                        SimpleNamespace(
                            type="FixedRatio",
                            agent_version="8",
                            traffic_percentage=100,
                        )
                    ]
                )
            ),
            "agent_contract_invalid",
        ),
        (FakeAgents(agent=_agent(protocols=("invocations",))), "agent_contract_invalid"),
    ],
)
def test_existing_definition_stable_endpoint_and_routing_rules_are_reused(
    verification_request, agents: FakeAgents, expected: str
) -> None:
    result = _verifier(agents).verify(verification_request)

    assert result.category == expected
    assert result.agent_contract_verified is False


@pytest.mark.parametrize(
    ("agent", "version"),
    [
        ({"unknown": "raw-secret"}, _version()),
        (_agent(), {"unknown": "raw-secret"}),
        (SimpleNamespace(id="id"), _version()),
        (_agent(), SimpleNamespace(name=AGENT_NAME, version=AGENT_VERSION)),
    ],
)
def test_unknown_or_malformed_sdk_shapes_fail_closed(
    verification_request, agent: object, version: object
) -> None:
    result = _verifier(FakeAgents(agent=agent, version=version)).verify(
        verification_request
    )

    assert result.category == "response_parse_failed"
    assert "raw-secret" not in json.dumps(result.to_json_dict())


def test_no_invocation_mutation_retry_poll_deploy_or_rbac_surface_is_used(
    verification_request,
) -> None:
    agents = FakeAgents()
    client = FakeProjectClient(agents)

    result = _verifier(
        project_client_factory=lambda _endpoint, _credential: client
    ).verify(verification_request)

    assert result.ok is True
    assert agents.get_calls == [AGENT_NAME]
    assert agents.get_version_calls == [(AGENT_NAME, AGENT_VERSION)]
    assert result.agent_invocation_attempted is False
    assert result.azure_mutation_made is False


def test_serialized_result_excludes_configuration_ids_errors_and_payloads(
    verification_request,
) -> None:
    result = _verifier().verify(verification_request)
    serialized = json.dumps(result.to_json_dict())

    for unsafe in (
        PROJECT_ENDPOINT,
        "secret.example",
        STABLE_ENDPOINT,
        AGENT_NAME,
        AGENT_VERSION,
        MODEL_NAME,
        "secret-agent-resource-id",
        "secret-client-id",
        "tenant",
        "subscription",
        "Bearer",
        "prompt",
        "SDK payload",
    ):
        assert unsafe not in serialized


def test_credential_and_client_close_after_success(verification_request) -> None:
    events: list[str] = []

    class Credential:
        def close(self) -> None:
            events.append("credential")

    class ProjectClient(FakeProjectClient):
        def close(self) -> None:
            events.append("client")

    credential = Credential()
    client = ProjectClient(FakeAgents())

    result = _verifier(
        credential_factory=lambda: credential,
        project_client_factory=lambda _endpoint, _credential: client,
    ).verify(verification_request)

    assert result.ok is True
    assert events == ["client", "credential"]


@pytest.mark.parametrize(
    "agents",
    [
        FakeAgents(get_error=StatusError(403)),
        FakeAgents(version=_version(model="contract-mismatch")),
    ],
)
def test_credential_and_client_close_after_verification_failure(
    verification_request, agents: FakeAgents
) -> None:
    events: list[str] = []

    class Credential:
        def close(self) -> None:
            events.append("credential")

    class ProjectClient(FakeProjectClient):
        def close(self) -> None:
            events.append("client")

    result = _verifier(
        credential_factory=Credential,
        project_client_factory=lambda _endpoint, _credential: ProjectClient(agents),
    ).verify(verification_request)

    assert result.ok is False
    assert events == ["client", "credential"]


def test_cleanup_failures_do_not_replace_or_leak_primary_result(
    verification_request,
) -> None:
    events: list[str] = []

    class Credential:
        def close(self) -> None:
            events.append("credential")
            raise RuntimeError("credential-close-secret")

    class ProjectClient(FakeProjectClient):
        def close(self) -> None:
            events.append("client")
            raise RuntimeError("client-close-secret")

    result = _verifier(
        FakeAgents(get_error=RuntimeError("primary-project-secret")),
        credential_factory=Credential,
        project_client_factory=lambda _endpoint, _credential: ProjectClient(
            FakeAgents(get_error=RuntimeError("primary-project-secret"))
        ),
    ).verify(verification_request)

    serialized = json.dumps(result.to_json_dict())
    assert result.category == "project_access_failed"
    assert events == ["client", "credential"]
    for unsafe in (
        "credential-close-secret",
        "client-close-secret",
        "primary-project-secret",
    ):
        assert unsafe not in serialized


def test_credential_closes_when_project_client_construction_fails(
    verification_request,
) -> None:
    events: list[str] = []

    class Credential:
        def close(self) -> None:
            events.append("credential")

    def fail_client(_endpoint: str, _credential: object) -> object:
        raise RuntimeError("client-construction-secret")

    result = _verifier(
        credential_factory=Credential,
        project_client_factory=fail_client,
    ).verify(verification_request)

    assert result.category == "azure_request_failed"
    assert events == ["credential"]
    assert "client-construction-secret" not in json.dumps(result.to_json_dict())
