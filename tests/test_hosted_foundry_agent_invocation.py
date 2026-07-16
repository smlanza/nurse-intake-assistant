import inspect
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.app.services import hosted_foundry_agent_invocation as hosted
from src.app.services.foundry_agent_client import FoundryAgentResponse
from src.app.services.nurse_intake_agent_instructions import (
    build_nurse_intake_agent_fictional_test_input,
    build_nurse_intake_agent_instructions,
)


PROJECT_ENDPOINT = "https://secret.example/api/projects/demo"
STABLE_ENDPOINT = (
    "https://secret.example/api/projects/demo/agents/configured-agent/"
    "endpoint/protocols/openai"
)
AGENT_NAME = "configured-agent"
AGENT_VERSION = "7"
IDENTITY_HEADER = "super-secret-identity-header"


def _valid_content(**overrides: object) -> str:
    payload: dict[str, object] = {
        "extraction": {
            "patient": {
                "name": "Fictional Patient",
                "date_of_birth": None,
                "callback_number": "fictional-callback-003",
            },
            "reason_for_calling": "fictional routine refill",
            "symptoms": ["mild fatigue"],
            "summary": "Fictional patient requests a routine refill callback.",
            "missing_fields": ["date_of_birth"],
            "uncertain_fields": [],
        },
        "urgency": {
            "urgency": "Routine",
            "urgency_rationale": "No urgent fictional symptoms were reported.",
            "advisory_disclaimer": "Advisory only; human nurse review is required.",
        },
    }
    payload.update(overrides)
    return json.dumps(payload)


class StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(
            "Bearer secret-token tenant-secret https://secret.example raw response"
        )
        self.status_code = status_code


class FakeCredential:
    def __init__(self, events: list[str] | None = None, *, close_error=False) -> None:
        self.events = events
        self.close_error = close_error

    def close(self) -> None:
        if self.events is not None:
            self.events.append("credential")
        if self.close_error:
            raise RuntimeError("credential-close-secret")


class FakeInvocationClient:
    def __init__(
        self,
        content: str = "",
        *,
        error: Exception | None = None,
        events: list[str] | None = None,
        close_error: bool = False,
    ) -> None:
        self.content = content or _valid_content()
        self.error = error
        self.events = events
        self.close_error = close_error
        self.requests: list[object] = []

    async def invoke_agent(self, request: object) -> FoundryAgentResponse:
        self.requests.append(request)
        if self.error:
            raise self.error
        return FoundryAgentResponse(content=self.content)

    def close(self) -> None:
        if self.events is not None:
            self.events.append("client")
        if self.close_error:
            raise RuntimeError("client-close-secret")


@pytest.fixture
def invocation_request() -> hosted.HostedFoundryAgentInvocationRequest:
    return hosted.HostedFoundryAgentInvocationRequest(
        mode="live",
        project_endpoint=PROJECT_ENDPOINT,
        stable_agent_endpoint=STABLE_ENDPOINT,
        agent_name=AGENT_NAME,
        agent_version=AGENT_VERSION,
        managed_identity_client_id=None,
        instructions=build_nurse_intake_agent_instructions(),
        fictional_intake_text=build_nurse_intake_agent_fictional_test_input(),
    )


def _invoker(
    client: FakeInvocationClient | None = None,
    *,
    credential_factory=None,
    client_factory=None,
    environment: dict[str, object] | None = None,
):
    if environment is None:
        environment = {
            "WEBSITE_INSTANCE_ID": "fictional-instance",
            "IDENTITY_ENDPOINT": "http://127.0.0.1:41741/MSI/token/",
            "IDENTITY_HEADER": IDENTITY_HEADER,
        }
    credential_factory = credential_factory or FakeCredential
    client_factory = client_factory or (
        lambda _request, _credential: client or FakeInvocationClient()
    )
    return hosted.HostedFoundryAgentInvocation(
        credential_factory=credential_factory,
        invocation_client_factory=client_factory,
        environment_reader=environment.get,
        sdk_available=lambda: True,
    )


def test_check_is_fully_offline_and_constructs_fixed_contract(
    invocation_request,
) -> None:
    invoker = hosted.HostedFoundryAgentInvocation(
        credential_factory=lambda: pytest.fail("check must not create credentials"),
        invocation_client_factory=lambda *_args: pytest.fail(
            "check must not create clients"
        ),
        environment_reader=lambda _name: pytest.fail(
            "check must not inspect App Service identity"
        ),
        sdk_available=lambda: True,
    )

    result = invoker.check(replace(invocation_request, mode="check"))

    assert result.ok is True
    assert result.category == "check_complete"
    assert result.invocation_attempted is False
    assert result.agent_output_valid is False
    assert result.fields_present == ()
    assert result.fictional_data_only is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("project_endpoint", ""),
        ("stable_agent_endpoint", None),
        ("stable_agent_endpoint", "https://other.example/agents/bad"),
        ("agent_name", ""),
        ("agent_version", " "),
        ("managed_identity_client_id", "user-assigned-client-id"),
        ("instructions", "operator supplied instructions"),
        ("fictional_intake_text", "caller supplied patient text"),
        ("mode", "preview"),
    ],
)
def test_invalid_local_configuration_fails_safely_before_dependencies(
    invocation_request, field: str, value: object
) -> None:
    invoker = hosted.HostedFoundryAgentInvocation(
        credential_factory=lambda: pytest.fail("invalid config must stop first"),
        invocation_client_factory=lambda *_args: pytest.fail(
            "invalid config must stop first"
        ),
        environment_reader=lambda _name: pytest.fail("invalid config must stop first"),
        sdk_available=lambda: True,
    )

    result = invoker.invoke(replace(invocation_request, **{field: value}))

    assert result.category == "missing_configuration"
    assert result.invocation_attempted is False
    assert "operator supplied" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    ("marker", "value"),
    [
        ("WEBSITE_INSTANCE_ID", None),
        ("WEBSITE_INSTANCE_ID", ""),
        ("WEBSITE_INSTANCE_ID", "   "),
        ("WEBSITE_INSTANCE_ID", object()),
        ("WEBSITE_INSTANCE_ID", "bad\ninstance"),
        ("IDENTITY_ENDPOINT", None),
        ("IDENTITY_ENDPOINT", ""),
        ("IDENTITY_ENDPOINT", "   "),
        ("IDENTITY_ENDPOINT", object()),
        ("IDENTITY_ENDPOINT", "not-a-url"),
        ("IDENTITY_HEADER", None),
        ("IDENTITY_HEADER", ""),
        ("IDENTITY_HEADER", "   "),
        ("IDENTITY_HEADER", object()),
        ("IDENTITY_HEADER", "bad\nheader"),
    ],
)
def test_hosted_environment_guard_stops_before_credential_or_client(
    invocation_request, marker: str, value: object
) -> None:
    environment = {
        "WEBSITE_INSTANCE_ID": "fictional-instance",
        "IDENTITY_ENDPOINT": "http://127.0.0.1:41741/MSI/token/",
        "IDENTITY_HEADER": IDENTITY_HEADER,
    }
    environment[marker] = value
    result = _invoker(
        environment=environment,
        credential_factory=lambda: pytest.fail("guard must precede credential"),
        client_factory=lambda *_args: pytest.fail("guard must precede client"),
    ).invoke(invocation_request)

    assert result.category == "not_running_in_hosted_environment"
    assert result.invocation_attempted is False


def test_identity_header_is_never_retained_serialized_logged_or_represented(
    invocation_request, caplog: pytest.LogCaptureFixture
) -> None:
    result = _invoker().invoke(invocation_request)
    visible = json.dumps(result.to_json_dict()) + repr(result) + caplog.text

    assert result.ok is True
    assert IDENTITY_HEADER not in visible


def test_default_credential_is_system_assigned_without_chain_or_client_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class ManagedIdentityCredential:
        def __init__(self, **kwargs: object) -> None:
            calls.append(kwargs)

    monkeypatch.setattr(
        hosted, "_get_managed_identity_credential_class", lambda: ManagedIdentityCredential
    )

    credential = hosted.create_system_assigned_managed_identity_credential()

    assert isinstance(credential, ManagedIdentityCredential)
    assert calls == [{}]
    source = inspect.getsource(hosted)
    for forbidden in (
        "DefaultAzureCredential",
        "AzureCliCredential",
        "EnvironmentCredential",
        "WorkloadIdentityCredential",
        "InteractiveBrowserCredential",
    ):
        assert forbidden not in source


def test_credential_construction_failure_is_sanitized(invocation_request) -> None:
    def fail() -> object:
        raise RuntimeError("credential secret-token IDENTITY_HEADER")

    result = _invoker(credential_factory=fail).invoke(invocation_request)

    assert result.category == "authentication_or_authorization_failed"
    assert result.invocation_attempted is False
    assert "secret" not in json.dumps(result.to_json_dict())


def test_exactly_one_fixed_fictional_invocation_uses_stable_configuration(
    invocation_request,
) -> None:
    client = FakeInvocationClient()
    factory_calls: list[tuple[object, object]] = []

    def client_factory(request: object, credential: object) -> object:
        factory_calls.append((request, credential))
        return client

    result = _invoker(client, client_factory=client_factory).invoke(invocation_request)

    assert result.ok is True
    assert len(factory_calls) == 1
    assert factory_calls[0][0].stable_agent_endpoint == STABLE_ENDPOINT
    assert factory_calls[0][0].agent_version == AGENT_VERSION
    assert len(client.requests) == 1
    assert client.requests[0].intake_text == build_nurse_intake_agent_fictional_test_input()
    assert client.requests[0].instructions == build_nurse_intake_agent_instructions()
    assert result.invocation_attempted is True
    assert result.agent_output_valid is True
    assert result.fields_present == ("extraction", "urgency", "handoffNote")


def test_result_exposes_only_approved_sanitized_contract(invocation_request) -> None:
    result = _invoker().invoke(invocation_request)
    payload = result.to_json_dict()

    assert set(payload) == {
        "ok",
        "category",
        "message",
        "invocation_attempted",
        "agent_output_valid",
        "fields_present",
        "fictional_data_only",
        "recommended_next_step",
    }
    assert payload["fields_present"] == ["extraction", "urgency", "handoffNote"]
    serialized = json.dumps(payload)
    for unsafe in (
        "Fictional Patient",
        "fictional-callback-003",
        "routine refill",
        "secret.example",
        AGENT_NAME,
        AGENT_VERSION,
        "raw response",
        "tenant-secret",
        "secret-token",
    ):
        assert unsafe not in serialized


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_and_authorization_failures_are_sanitized(
    invocation_request, status: int
) -> None:
    result = _invoker(FakeInvocationClient(error=StatusError(status))).invoke(
        invocation_request
    )

    assert result.category == "authentication_or_authorization_failed"
    assert result.invocation_attempted is True
    assert result.agent_output_valid is False
    assert "secret" not in json.dumps(result.to_json_dict())


def test_general_azure_request_failure_is_sanitized(invocation_request) -> None:
    result = _invoker(
        FakeInvocationClient(error=RuntimeError("Azure raw-body secret"))
    ).invoke(invocation_request)

    assert result.category == "azure_request_failed"
    assert result.invocation_attempted is True
    assert "raw-body" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize("content", ["", "   ", "not-json", "[]"])
def test_empty_malformed_envelope_or_invalid_json_fails_as_parse_error(
    invocation_request, content: str
) -> None:
    client = FakeInvocationClient(content=_valid_content())
    client.content = content

    result = _invoker(client).invoke(invocation_request)

    assert result.category == "response_parse_failed"
    assert result.invocation_attempted is True
    assert result.agent_output_valid is False


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"urgency": {}}),
        _valid_content(urgency={"urgency": "Emergency"}),
        _valid_content(extraction=[]),
        _valid_content(extraction={"summary": "only summary"}),
    ],
)
def test_invalid_output_contract_fails_closed(
    invocation_request, content: str
) -> None:
    result = _invoker(FakeInvocationClient(content=content)).invoke(invocation_request)

    assert result.category == "contract_invalid"
    assert result.invocation_attempted is True
    assert result.agent_output_valid is False


def test_invalid_or_missing_generated_handoff_fails_contract(
    invocation_request, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hosted, "_build_handoff_note", lambda *_args: "")

    result = _invoker().invoke(invocation_request)

    assert result.category == "contract_invalid"
    assert result.agent_output_valid is False


def test_unexpected_processing_failure_is_sanitized(
    invocation_request, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = hosted._build_handoff_note
    calls = 0

    def fail_live_handoff(*args: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            return original(*args)
        raise RuntimeError("Traceback raw secret")

    monkeypatch.setattr(
        hosted,
        "_build_handoff_note",
        fail_live_handoff,
    )

    result = _invoker().invoke(invocation_request)

    assert result.category == "unexpected_error"
    assert "Traceback" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    "client",
    [
        FakeInvocationClient(),
        FakeInvocationClient(error=StatusError(401)),
        FakeInvocationClient(error=RuntimeError("azure failure")),
        FakeInvocationClient(content="not-json"),
        FakeInvocationClient(content=json.dumps({"urgency": {}})),
    ],
)
def test_client_then_credential_cleanup_on_every_constructed_outcome(
    invocation_request, client: FakeInvocationClient
) -> None:
    events: list[str] = []
    credential = FakeCredential(events)
    client.events = events

    _invoker(
        client,
        credential_factory=lambda: credential,
    ).invoke(invocation_request)

    assert events == ["client", "credential"]


def test_cleanup_exceptions_do_not_replace_success_or_leak(
    invocation_request,
) -> None:
    events: list[str] = []
    client = FakeInvocationClient(events=events, close_error=True)
    credential = FakeCredential(events, close_error=True)

    result = _invoker(
        client,
        credential_factory=lambda: credential,
    ).invoke(invocation_request)

    assert result.ok is True
    assert events == ["client", "credential"]
    serialized = json.dumps(result.to_json_dict())
    assert "close-secret" not in serialized


def test_cleanup_exceptions_preserve_original_failure_category(
    invocation_request,
) -> None:
    events: list[str] = []
    client = FakeInvocationClient(
        error=StatusError(403), events=events, close_error=True
    )
    credential = FakeCredential(events, close_error=True)

    result = _invoker(client, credential_factory=lambda: credential).invoke(
        invocation_request
    )

    assert result.category == "authentication_or_authorization_failed"
    assert events == ["client", "credential"]
    assert "secret" not in json.dumps(result.to_json_dict())


def test_credential_closes_after_client_construction_failure(invocation_request) -> None:
    events: list[str] = []
    credential = FakeCredential(events)

    def fail_client(_request: object, _credential: object) -> object:
        raise RuntimeError("client-construction-secret")

    result = _invoker(
        credential_factory=lambda: credential,
        client_factory=fail_client,
    ).invoke(invocation_request)

    assert result.category == "azure_request_failed"
    assert result.invocation_attempted is False
    assert events == ["credential"]


def test_default_client_factory_reuses_stable_responses_path_and_owned_cleanup(
    invocation_request, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, object]] = []
    events: list[str] = []
    credential = object()

    class ResponsesClient:
        responses = object()

        def close(self) -> None:
            events.append("responses-client")

    responses_client = ResponsesClient()

    class ProjectClient:
        def __init__(self, **kwargs: object) -> None:
            calls.append(("project", kwargs))

        def get_openai_client(self, **kwargs: object) -> object:
            calls.append(("openai", kwargs))
            return responses_client

        def close(self) -> None:
            events.append("project-client")

    monkeypatch.setattr(hosted, "_get_ai_project_client_class", lambda: ProjectClient)

    client = hosted._create_owned_invocation_client(
        invocation_request, credential
    )

    assert calls == [
        (
            "project",
            {
                "endpoint": PROJECT_ENDPOINT,
                "credential": credential,
                "allow_preview": True,
            },
        ),
        ("openai", {"agent_name": AGENT_NAME}),
    ]
    assert client._agent_client.stable_agent_endpoint == STABLE_ENDPOINT
    assert client._agent_client.agent_version == AGENT_VERSION

    client.close()

    assert events == ["responses-client", "project-client"]


def test_default_client_factory_closes_partial_project_client_before_credential(
    invocation_request, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []

    class ProjectClient:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def get_openai_client(self, **_kwargs: object) -> object:
            raise RuntimeError("partial-client-secret")

        def close(self) -> None:
            events.append("project-client")

    credential = FakeCredential(events)
    monkeypatch.setattr(hosted, "_get_ai_project_client_class", lambda: ProjectClient)
    invoker = hosted.HostedFoundryAgentInvocation(
        credential_factory=lambda: credential,
        environment_reader={
            "WEBSITE_INSTANCE_ID": "fictional-instance",
            "IDENTITY_ENDPOINT": "http://127.0.0.1:41741/MSI/token/",
            "IDENTITY_HEADER": IDENTITY_HEADER,
        }.get,
        sdk_available=lambda: True,
    )

    result = invoker.invoke(invocation_request)

    assert result.category == "azure_request_failed"
    assert events == ["project-client", "credential"]


def test_service_has_no_side_effect_retry_poll_or_mutation_dependencies() -> None:
    source = inspect.getsource(hosted)

    for forbidden in (
        "CaseProcessingService",
        "case_repository",
        "Cosmos",
        "email",
        "sms",
        "/intake/text",
        "create_version",
        "role assignment",
        "deploy",
        "retry",
        "poll",
        "sleep(",
    ):
        assert forbidden not in source
