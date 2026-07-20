import json
from collections import UserDict
from types import SimpleNamespace

import pytest

from src.app.services.foundry_agent_endpoint_routing import (
    FoundryAgentEndpointRouting,
    FoundryAgentEndpointRoutingRequest,
)


PROJECT_ENDPOINT = "https://secret.example/api/projects/demo"
STABLE_ENDPOINT = (
    f"{PROJECT_ENDPOINT}/agents/configured-agent/endpoint/protocols/openai"
)


def _request(**overrides: object) -> FoundryAgentEndpointRoutingRequest:
    values: dict[str, object] = {
        "project_endpoint": PROJECT_ENDPOINT,
        "stable_agent_endpoint": STABLE_ENDPOINT,
        "agent_name": "configured-agent",
        "agent_version": "7",
    }
    values.update(overrides)
    return FoundryAgentEndpointRoutingRequest(**values)


def _endpoint(rules: object = None, *, responses: bool = True):
    from azure.ai.projects.models import (
        AgentEndpointConfig,
        FixedRatioVersionSelectionRule,
        InvocationsProtocolConfiguration,
        ProtocolConfiguration,
        ResponsesProtocolConfiguration,
        VersionSelector,
    )

    if rules is None:
        rules = [
            FixedRatioVersionSelectionRule(
                agent_version="7",
                traffic_percentage=100,
            )
        ]
    protocol_configuration = ProtocolConfiguration(
        responses=ResponsesProtocolConfiguration() if responses else None,
        invocations=InvocationsProtocolConfiguration(),
    )
    return AgentEndpointConfig(
        version_selector=VersionSelector(version_selection_rules=rules),
        protocol_configuration=protocol_configuration,
        authorization_schemes=[UserDict({"type": "Entra"})],
    )


def _details(endpoint: object | None, *, name: str = "configured-agent"):
    return UserDict(
        {
            "id": "secret-agent-id",
            "name": name,
            "agent_endpoint": endpoint,
            "instance_identity": UserDict({"client_id": "secret-client-id"}),
        }
    )


class FakeAgents:
    def __init__(
        self,
        endpoint: object | None,
        *,
        update_response: object | None = None,
        get_error: Exception | None = None,
        version: object | None = None,
        version_error: Exception | None = None,
        details_name: str = "configured-agent",
    ) -> None:
        self.endpoint = endpoint
        self.update_response = update_response
        self.get_error = get_error
        self.version = version or UserDict(
            {"name": "configured-agent", "version": "7", "definition": {}}
        )
        self.version_error = version_error
        self.details_name = details_name
        self.get_calls: list[str] = []
        self.get_version_calls: list[tuple[str, str]] = []
        self.update_calls: list[dict[str, object]] = []

    def get(self, agent_name: str) -> object:
        self.get_calls.append(agent_name)
        if self.get_error is not None:
            raise self.get_error
        return _details(self.endpoint, name=self.details_name)

    def get_version(self, agent_name: str, agent_version: str) -> object:
        self.get_version_calls.append((agent_name, agent_version))
        if self.version_error is not None:
            raise self.version_error
        return self.version

    def update_details(self, agent_name: str, **kwargs: object) -> object:
        self.update_calls.append({"agent_name": agent_name, **kwargs})
        if self.update_response is not None:
            return self.update_response
        return _details(kwargs["agent_endpoint"])

    def create_version(self, **kwargs: object) -> None:
        pytest.fail("routing configuration must not create an agent version")


class Closable:
    def __init__(self, label: str, closed: list[str], *, fail: bool = False) -> None:
        self.label = label
        self.closed = closed
        self.fail = fail

    def close(self) -> None:
        self.closed.append(self.label)
        if self.fail:
            raise RuntimeError("Bearer secret cleanup failure")


class FakeProjectClient(Closable):
    def __init__(self, agents: FakeAgents, closed: list[str], *, fail_close=False):
        super().__init__("client", closed, fail=fail_close)
        self.agents = agents

    def get_openai_client(self) -> None:
        pytest.fail("routing configuration must not create an invocation client")


def _service(
    agents: FakeAgents,
    *,
    closed: list[str] | None = None,
    fail_client_close: bool = False,
    fail_credential_close: bool = False,
) -> FoundryAgentEndpointRouting:
    closed = closed if closed is not None else []
    credential = Closable(
        "credential",
        closed,
        fail=fail_credential_close,
    )
    return FoundryAgentEndpointRouting(
        credential_factory=lambda client_id: credential,
        project_client_factory=lambda endpoint, value: FakeProjectClient(
            agents,
            closed,
            fail_close=fail_client_close,
        ),
    )


def test_check_is_offline_and_validates_installed_sdk_contract() -> None:
    service = FoundryAgentEndpointRouting(
        credential_factory=lambda client_id: pytest.fail(
            "check must not create a credential"
        ),
        project_client_factory=lambda endpoint, credential: pytest.fail(
            "check must not create a client"
        ),
    )

    result = service.check(_request())

    assert result.ok is True
    assert result.ready is True
    assert result.azure_call_made is False
    assert result.azure_mutation_made is False
    assert result.agent_invoked is False
    assert result.configured_version_exclusive is False


@pytest.mark.parametrize(
    ("overrides", "expected_category"),
    [
        ({"project_endpoint": ""}, "missing_configuration"),
        ({"stable_agent_endpoint": ""}, "missing_configuration"),
        ({"agent_name": ""}, "missing_configuration"),
        ({"agent_version": ""}, "missing_configuration"),
        ({"project_endpoint": "not-an-endpoint"}, "endpoint_mismatch"),
        ({"stable_agent_endpoint": "http://secret.example"}, "endpoint_mismatch"),
        ({"agent_version": " 7 "}, "missing_configuration"),
    ],
)
def test_check_rejects_missing_or_malformed_configuration(
    overrides: dict[str, object],
    expected_category: str,
) -> None:
    result = FoundryAgentEndpointRouting().check(_request(**overrides))

    assert result.ok is False
    assert result.category == expected_category
    assert result.azure_call_made is False
    assert result.azure_mutation_made is False
    assert result.agent_invoked is False


def test_check_fails_safely_when_sdk_surface_is_unavailable() -> None:
    service = FoundryAgentEndpointRouting(
        sdk_contract_loader=lambda: (_ for _ in ()).throw(
            ModuleNotFoundError("Bearer secret SDK details")
        )
    )

    result = service.check(_request())

    assert result.category == "sdk_unavailable"
    assert "secret" not in json.dumps(result.to_json_dict()).lower()


def test_live_reuses_already_exclusive_routing_without_mutation() -> None:
    agents = FakeAgents(_endpoint())

    result = _service(agents).configure(_request())

    assert result.ok is True
    assert result.routing_reused is True
    assert result.routing_updated is False
    assert result.configured_version_exclusive is True
    assert result.configured_version_traffic_percentage == 100
    assert result.responses_protocol_present is True
    assert result.azure_call_made is True
    assert result.azure_mutation_made is False
    assert result.agent_invoked is False
    assert agents.update_calls == []


def test_live_updates_known_nonexclusive_routing_once_and_preserves_endpoint() -> None:
    from azure.ai.projects.models import FixedRatioVersionSelectionRule

    endpoint = _endpoint(
        [
            FixedRatioVersionSelectionRule(
                agent_version="7", traffic_percentage=50
            ),
            FixedRatioVersionSelectionRule(
                agent_version="8", traffic_percentage=50
            ),
        ]
    )
    agents = FakeAgents(endpoint)

    result = _service(agents).configure(_request())

    assert result.ok is True
    assert result.routing_reused is False
    assert result.routing_updated is True
    assert result.azure_mutation_made is True
    assert result.configured_version_exclusive is True
    assert result.configured_version_traffic_percentage == 100
    assert len(agents.update_calls) == 1
    payload = agents.update_calls[0]["agent_endpoint"]
    rules = payload["version_selector"]["version_selection_rules"]
    assert len(rules) == 1
    assert rules[0]["type"] == "FixedRatio"
    assert rules[0]["agent_version"] == "7"
    assert rules[0]["traffic_percentage"] == 100
    assert "responses" in payload["protocol_configuration"]
    assert "invocations" in payload["protocol_configuration"]
    assert payload["authorization_schemes"] == endpoint["authorization_schemes"]


@pytest.mark.parametrize("rules", [None, []])
def test_live_corrects_unpinned_or_empty_selector(rules: object) -> None:
    endpoint = _endpoint()
    if rules is None:
        endpoint["version_selector"] = None
    else:
        endpoint["version_selector"]["version_selection_rules"] = rules
    agents = FakeAgents(endpoint)

    result = _service(agents).configure(_request())

    assert result.ok is True
    assert result.routing_updated is True
    assert len(agents.update_calls) == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        UserDict({"version_selector": object(), "protocol_configuration": {}}),
        _endpoint([UserDict({"type": "Unknown", "agent_version": "7", "traffic_percentage": 100})]),
        _endpoint([UserDict({"type": "FixedRatio", "agent_version": "7"})]),
        _endpoint(
            [
                UserDict({"type": "FixedRatio", "agent_version": "7", "traffic_percentage": 60}),
                UserDict({"type": "FixedRatio", "agent_version": "8", "traffic_percentage": 60}),
            ]
        ),
        _endpoint(
            [
                UserDict({"type": "FixedRatio", "agent_version": "7", "traffic_percentage": 50}),
                UserDict({"type": "FixedRatio", "agent_version": "7", "traffic_percentage": 50}),
            ]
        ),
    ],
)
def test_live_fails_closed_for_missing_or_ambiguous_endpoint_shapes(
    endpoint: object,
) -> None:
    agents = FakeAgents(endpoint)

    result = _service(agents).configure(_request())

    assert result.ok is False
    assert result.routing_updated is False
    assert result.agent_invoked is False
    assert agents.update_calls == []


def test_live_requires_responses_protocol_before_mutation() -> None:
    agents = FakeAgents(_endpoint([], responses=False))

    result = _service(agents).configure(_request())

    assert result.category == "responses_protocol_missing"
    assert agents.update_calls == []


def test_live_rejects_remote_agent_or_version_mismatch() -> None:
    agents = FakeAgents(
        _endpoint(),
        version=UserDict({"name": "configured-agent", "version": "8"}),
    )

    result = _service(agents).configure(_request())

    assert result.category == "version_routing_mismatch"
    assert agents.update_calls == []


def test_live_rejects_remote_agent_identity_mismatch() -> None:
    agents = FakeAgents(_endpoint(), details_name="other-agent")

    result = _service(agents).configure(_request())

    assert result.category == "endpoint_mismatch"
    assert agents.get_version_calls == []
    assert agents.update_calls == []


def test_live_reports_missing_configured_version_without_mutation() -> None:
    class NotFoundError(Exception):
        status_code = 404

    agents = FakeAgents(
        _endpoint([]),
        version_error=NotFoundError("secret version was not found"),
    )

    result = _service(agents).configure(_request())

    assert result.category == "not_found"
    assert result.configured_version_present is False
    assert agents.update_calls == []


def test_ambiguous_mutation_response_fails_without_retry() -> None:
    agents = FakeAgents(
        _endpoint([]),
        update_response=_details(_endpoint([])),
    )

    result = _service(agents).configure(_request())

    assert result.ok is False
    assert result.category == "response_parse_failed"
    assert result.azure_mutation_made is True
    assert result.routing_updated is False
    assert len(agents.update_calls) == 1


def test_mutation_response_for_different_agent_fails_without_retry() -> None:
    agents = FakeAgents(
        _endpoint([]),
        update_response=_details(_endpoint(), name="other-agent"),
    )

    result = _service(agents).configure(_request())

    assert result.ok is False
    assert result.category == "response_parse_failed"
    assert result.azure_mutation_made is True
    assert len(agents.update_calls) == 1


def test_live_sanitizes_azure_failures_and_closes_client_before_credential() -> None:
    class UnsafeError(Exception):
        status_code = 403

    closed: list[str] = []
    agents = FakeAgents(
        _endpoint(),
        get_error=UnsafeError(
            "Bearer secret-token https://secret.example configured-agent 7"
        ),
    )

    result = _service(
        agents,
        closed=closed,
        fail_client_close=True,
        fail_credential_close=True,
    ).configure(_request())

    payload = json.dumps(result.to_json_dict())
    assert result.category == "authentication_or_authorization_failed"
    assert closed == ["client", "credential"]
    assert result.agent_invoked is False
    for unsafe in ("secret-token", "secret.example", "configured-agent", '"7"'):
        assert unsafe not in payload


def test_partial_client_construction_closes_owned_credential() -> None:
    closed: list[str] = []
    credential = Closable("credential", closed)
    service = FoundryAgentEndpointRouting(
        credential_factory=lambda client_id: credential,
        project_client_factory=lambda endpoint, value: (_ for _ in ()).throw(
            RuntimeError("Bearer secret client failure")
        ),
    )

    result = service.configure(_request())

    assert result.category == "azure_request_failed"
    assert closed == ["credential"]
    assert result.agent_invoked is False
