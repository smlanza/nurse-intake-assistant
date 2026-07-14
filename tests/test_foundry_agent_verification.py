import json
from types import SimpleNamespace

import pytest

from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_instructions,
)


STABLE_ENDPOINT = (
    "https://secret.example/api/projects/demo/agents/configured-agent/"
    "endpoint/protocols/openai"
)


class StatusCodeError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(
            "Bearer secret-token https://secret.example patient prompt Traceback"
        )
        self.status_code = status_code


class FakeAgents:
    def __init__(
        self,
        version: SimpleNamespace | None = None,
        *,
        error: Exception | None = None,
        agent_details: SimpleNamespace | None = None,
    ) -> None:
        self.version = version
        self.error = error
        self.agent_details = agent_details
        self.get_calls: list[str] = []
        self.get_version_calls: list[dict[str, str]] = []

    def get(self, agent_name: str) -> SimpleNamespace:
        self.get_calls.append(agent_name)
        assert self.agent_details is not None
        return self.agent_details

    def get_version(self, agent_name: str, agent_version: str) -> SimpleNamespace:
        self.get_version_calls.append(
            {"agent_name": agent_name, "agent_version": agent_version}
        )
        if self.error is not None:
            raise self.error
        assert self.version is not None
        return self.version

    def create_version(self, **kwargs: object) -> None:
        pytest.fail("verification must not create or update an agent version")


class FakeProjectClient:
    def __init__(self, agents: FakeAgents) -> None:
        self.agents = agents

    def get_openai_client(self) -> None:
        pytest.fail("verification must not create an invocation client")


def _request():
    from src.app.services.foundry_agent_verification import (
        FoundryAgentVerificationRequest,
    )

    return FoundryAgentVerificationRequest(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="configured-agent",
        agent_version="7",
        model_deployment_name="gpt-demo",
        instructions=build_nurse_intake_agent_instructions(),
    )


def _stable_request():
    request = _request()
    return type(request)(
        project_endpoint=request.project_endpoint,
        stable_agent_endpoint=STABLE_ENDPOINT,
        agent_name=request.agent_name,
        agent_version=request.agent_version,
        model_deployment_name=request.model_deployment_name,
        instructions=request.instructions,
    )


def _agent_details(
    *,
    protocols: object = ("responses",),
    identity: object | None = None,
    protocol_configuration: object | None = None,
) -> SimpleNamespace:
    if identity is None:
        identity = SimpleNamespace(client_id="secret-identity-id")
    endpoint = SimpleNamespace(
        protocols=protocols,
        protocol_configuration=protocol_configuration,
        version_selector=SimpleNamespace(
            version_selection_rules=[
                SimpleNamespace(
                    type="FixedRatio",
                    agent_version="7",
                    traffic_percentage=100,
                )
            ]
        ),
    )
    return SimpleNamespace(
        id="secret-agent-object-id",
        instance_identity=identity,
        agent_endpoint=endpoint,
    )


def _version(
    *,
    name: str = "configured-agent",
    version: str = "7",
    model: str = "gpt-demo",
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


def _verification(agents: FakeAgents, endpoints: list[str]):
    from src.app.services.foundry_agent_verification import FoundryAgentVerification

    def client_factory(endpoint: str) -> FakeProjectClient:
        endpoints.append(endpoint)
        return FakeProjectClient(agents)

    return FoundryAgentVerification(project_client_factory=client_factory)


def test_verify_confirms_exact_immutable_version_and_definition_read_only() -> None:
    agents = FakeAgents(_version())
    endpoints: list[str] = []

    result = _verification(agents, endpoints).verify(_request())

    assert endpoints == ["https://secret.example/api/projects/demo"]
    assert agents.get_version_calls == [
        {"agent_name": "configured-agent", "agent_version": "7"}
    ]
    assert result.ok is True
    assert result.category == "success"
    assert result.agent_definition_matches is True
    assert result.azure_lookup_attempted is True
    assert result.agent_invoked is False
    assert result.azure_mutation_made is False
    assert result.instruction_version == NURSE_INTAKE_AGENT_INSTRUCTION_VERSION


@pytest.mark.parametrize(
    "version",
    [
        _version(model="older-model"),
        _version(instructions="older centralized instructions"),
    ],
)
def test_verify_reports_definition_mismatch_without_updating(
    version: SimpleNamespace,
) -> None:
    result = _verification(FakeAgents(version), []).verify(_request())

    assert result.ok is False
    assert result.category == "definition_mismatch"
    assert result.agent_definition_matches is False
    assert result.agent_invoked is False
    assert result.azure_mutation_made is False


@pytest.mark.parametrize(
    ("status_code", "expected_category"),
    [
        (404, "agent_version_not_found"),
        (401, "authentication_or_authorization_failed"),
        (403, "authentication_or_authorization_failed"),
        (500, "agent_verification_failed"),
    ],
)
def test_verify_classifies_lookup_failures_with_sanitized_output(
    status_code: int,
    expected_category: str,
) -> None:
    result = _verification(FakeAgents(error=StatusCodeError(status_code)), []).verify(
        _request()
    )

    serialized = json.dumps(result.to_json_dict())
    assert result.ok is False
    assert result.category == expected_category
    assert result.azure_lookup_attempted is True
    assert result.agent_invoked is False
    assert result.azure_mutation_made is False
    for unsafe in (
        "secret-token",
        "secret.example",
        "patient prompt",
        "Traceback",
    ):
        assert unsafe not in serialized


def test_verify_reports_sdk_failure_before_version_lookup() -> None:
    from src.app.services.foundry_agent_verification import FoundryAgentVerification

    def unavailable_client_factory(endpoint: str) -> None:
        raise ModuleNotFoundError(
            "Bearer secret-token https://secret.example raw prompt Traceback"
        )

    result = FoundryAgentVerification(
        project_client_factory=unavailable_client_factory
    ).verify(_request())

    serialized = json.dumps(result.to_json_dict())
    assert result.ok is False
    assert result.category == "sdk_unavailable"
    assert result.azure_lookup_attempted is False
    for unsafe in ("secret-token", "secret.example", "raw prompt", "Traceback"):
        assert unsafe not in serialized


@pytest.mark.parametrize(
    "version",
    [
        _version(name="other-agent"),
        _version(version="8"),
        SimpleNamespace(name="configured-agent", version="7", definition=None),
    ],
)
def test_verify_rejects_invalid_remote_version_contract(
    version: SimpleNamespace,
) -> None:
    result = _verification(FakeAgents(version), []).verify(_request())

    assert result.ok is False
    assert result.category == "response_contract_invalid"
    assert result.agent_definition_matches is False
    assert result.agent_invoked is False
    assert result.azure_mutation_made is False


def test_stable_verification_reads_responses_from_endpoint_protocols() -> None:
    agents = FakeAgents(
        _version(),
        agent_details=_agent_details(protocols=["responses"]),
    )

    result = _verification(agents, []).verify(_stable_request())

    assert result.ok is True
    assert result.responses_protocol_present is True
    assert result.immutable_version_verified is True


@pytest.mark.parametrize(
    "protocols",
    [
        ["RESPONSES"],
        (" Responses ",),
        ["invocations", "rEsPoNsEs"],
    ],
)
def test_responses_protocol_matching_is_case_insensitive_for_sequences(
    protocols: object,
) -> None:
    agents = FakeAgents(
        _version(),
        agent_details=_agent_details(protocols=protocols),
    )

    result = _verification(agents, []).verify(_stable_request())

    assert result.responses_protocol_present is True


@pytest.mark.parametrize(
    "protocols",
    [
        None,
        [],
        (),
        "responses",
        {"responses"},
        {"name": "responses"},
        [None, "", object()],
    ],
)
def test_missing_or_malformed_protocols_are_safely_absent(protocols: object) -> None:
    agents = FakeAgents(
        _version(),
        agent_details=_agent_details(protocols=protocols),
    )

    result = _verification(agents, []).verify(_stable_request())

    assert result.ok is False
    assert result.agent_identity_present is True
    assert result.stable_endpoint_present is True
    assert result.stable_endpoint_matches_configuration is True
    assert result.version_selector_present is True
    assert result.configured_version_traffic_percentage == 100
    assert result.responses_protocol_present is False
    assert result.immutable_version_verified is False


def test_obsolete_protocol_configuration_is_not_used() -> None:
    agents = FakeAgents(
        _version(),
        agent_details=_agent_details(
            protocols=None,
            protocol_configuration=SimpleNamespace(responses=object()),
        ),
    )

    result = _verification(agents, []).verify(_stable_request())

    assert result.responses_protocol_present is False
    assert result.ok is False


def test_missing_identity_preserves_independent_endpoint_metadata() -> None:
    details = _agent_details(identity=SimpleNamespace(client_id=None))
    agents = FakeAgents(_version(), agent_details=details)

    result = _verification(agents, []).verify(_stable_request())

    assert result.ok is False
    assert result.category == "legacy_agent_model"
    assert result.agent_identity_present is False
    assert result.stable_endpoint_present is True
    assert result.stable_endpoint_matches_configuration is True
    assert result.version_selector_present is True
    assert result.responses_protocol_present is True
    assert result.configured_version_traffic_percentage == 100
    assert result.immutable_version_verified is False
    assert agents.get_version_calls == []


def test_missing_endpoint_preserves_independent_identity_metadata() -> None:
    details = SimpleNamespace(
        id="secret-agent-object-id",
        instance_identity=SimpleNamespace(client_id="secret-identity-id"),
        agent_endpoint=None,
    )
    agents = FakeAgents(_version(), agent_details=details)

    result = _verification(agents, []).verify(_stable_request())

    assert result.ok is False
    assert result.category == "stable_endpoint_missing"
    assert result.agent_identity_present is True
    assert result.stable_endpoint_present is False
    assert result.version_selector_present is False
    assert result.responses_protocol_present is False


def test_missing_selector_preserves_independent_protocol_metadata() -> None:
    details = _agent_details()
    details.agent_endpoint.version_selector = None
    agents = FakeAgents(_version(), agent_details=details)

    result = _verification(agents, []).verify(_stable_request())

    assert result.ok is False
    assert result.category == "version_routing_mismatch"
    assert result.agent_identity_present is True
    assert result.stable_endpoint_present is True
    assert result.version_selector_present is False
    assert result.responses_protocol_present is True
    assert result.configured_version_traffic_percentage is None


def test_independent_metadata_diagnostics_remain_sanitized() -> None:
    details = _agent_details(identity=SimpleNamespace(client_id=None))
    agents = FakeAgents(_version(), agent_details=details)

    result = _verification(agents, []).verify(_stable_request())

    serialized = json.dumps(result.to_json_dict())
    for unsafe in (
        "secret.example",
        "configured-agent",
        "secret-agent-object-id",
        "secret-identity-id",
        "\"7\"",
    ):
        assert unsafe not in serialized
