import json
from types import SimpleNamespace

import pytest

from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_fictional_test_input,
    build_nurse_intake_agent_instructions,
)


def _valid_output() -> str:
    return json.dumps(
        {
            "extraction": {
                "patient": {
                    "name": "Taylor Quinn",
                    "date_of_birth": None,
                    "callback_number": "demo-callback-002",
                },
                "reason_for_calling": "routine medication refill",
                "symptoms": [],
                "summary": "Fictional patient requests a routine refill.",
                "missing_fields": ["date_of_birth"],
                "uncertain_fields": [],
            },
            "urgency": {
                "urgency": "Routine",
                "urgency_rationale": "No urgent symptoms were reported.",
                "advisory_disclaimer": "Advisory only; nurse review is required.",
            },
        }
    )


class FakeResponses:
    def __init__(self, output_text: str | None, events: list[str]) -> None:
        self.output_text = output_text
        self.events = events
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.events.append("invoke")
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeProjectClient:
    def __init__(
        self,
        output_text: str | None = None,
        *,
        create_error: Exception | None = None,
        invoke_error: Exception | None = None,
    ) -> None:
        self.events: list[str] = []
        self.create_calls: list[dict[str, object]] = []
        self.responses = FakeResponses(output_text, self.events)
        self.openai_client = SimpleNamespace(responses=self.responses)
        self.create_error = create_error
        self.invoke_error = invoke_error
        self.agents = self

    def create_version(self, **kwargs: object) -> SimpleNamespace:
        self.events.append("create_version")
        self.create_calls.append(kwargs)
        if self.create_error is not None:
            raise self.create_error
        return SimpleNamespace(name="configured-agent", version="7")

    def get_openai_client(self) -> SimpleNamespace:
        self.events.append("get_openai_client")
        if self.invoke_error is not None:
            raise self.invoke_error
        return self.openai_client


def _request():
    from src.app.services.foundry_agent_deployment import (
        FoundryAgentDeploymentRequest,
    )

    return FoundryAgentDeploymentRequest(
        project_endpoint="https://secret.example/api/projects/demo",
        agent_name="configured-agent",
        model_deployment_name="gpt-demo",
        instructions=build_nurse_intake_agent_instructions(),
        fictional_validation_input=build_nurse_intake_agent_fictional_test_input(),
    )


def test_deployment_uses_centralized_prompt_agent_definition_and_captures_version() -> None:
    from src.app.services.foundry_agent_deployment import FoundryAgentDeployment

    project_client = FakeProjectClient(_valid_output())
    definitions: list[SimpleNamespace] = []

    def definition_factory(**kwargs: str) -> SimpleNamespace:
        definition = SimpleNamespace(**kwargs)
        definitions.append(definition)
        return definition

    deployment = FoundryAgentDeployment(
        project_client_factory=lambda endpoint: project_client,
        prompt_agent_definition_factory=definition_factory,
    )

    result = deployment.create_and_validate(_request())

    assert len(definitions) == 1
    assert definitions[0].model == "gpt-demo"
    assert definitions[0].instructions == build_nurse_intake_agent_instructions()
    assert project_client.create_calls == [
        {"agent_name": "configured-agent", "definition": definitions[0]}
    ]
    assert result.agent_created is True
    assert result.created_version == "7"
    assert result.instruction_version == NURSE_INTAKE_AGENT_INSTRUCTION_VERSION


def test_deployment_creates_before_agent_reference_invocation_and_validates_output() -> None:
    from src.app.services.foundry_agent_deployment import FoundryAgentDeployment

    project_client = FakeProjectClient(_valid_output())
    deployment = FoundryAgentDeployment(
        project_client_factory=lambda endpoint: project_client,
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    result = deployment.create_and_validate(_request())

    assert project_client.events == [
        "create_version",
        "get_openai_client",
        "invoke",
    ]
    assert project_client.responses.calls == [
        {
            "input": build_nurse_intake_agent_fictional_test_input(),
            "extra_body": {
                "agent_reference": {
                    "name": "configured-agent",
                    "version": "7",
                    "type": "agent_reference",
                }
            },
        }
    ]
    assert result.ok is True
    assert result.agent_invoked is True
    assert result.agent_output_valid is True
    assert result.fields_present == ["extraction", "urgency"]
    assert "Taylor" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    ("output_text", "expected_category"),
    [
        ("{malformed", "response_parse_failed"),
        (json.dumps({"extraction": {}, "urgency": {}}), "contract_invalid"),
        (None, "agent_invocation_failed"),
    ],
)
def test_deployment_sanitizes_invalid_agent_output(
    output_text: str | None,
    expected_category: str,
) -> None:
    from src.app.services.foundry_agent_deployment import FoundryAgentDeployment

    project_client = FakeProjectClient(output_text)
    deployment = FoundryAgentDeployment(
        project_client_factory=lambda endpoint: project_client,
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    result = deployment.create_and_validate(_request())

    assert result.ok is False
    assert result.category == expected_category
    assert result.agent_output_valid is False
    serialized = json.dumps(result.to_json_dict())
    assert "malformed" not in serialized
    assert "Taylor" not in serialized


class StatusCodeError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__("raw endpoint token and patient details")
        self.status_code = status_code


@pytest.mark.parametrize("status_code", [401, 403])
def test_deployment_classifies_auth_failures_without_raw_details(
    status_code: int,
) -> None:
    from src.app.services.foundry_agent_deployment import FoundryAgentDeployment

    project_client = FakeProjectClient(
        _valid_output(),
        create_error=StatusCodeError(status_code),
    )
    deployment = FoundryAgentDeployment(
        project_client_factory=lambda endpoint: project_client,
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    result = deployment.create_and_validate(_request())

    assert result.category == "authentication_or_authorization_failed"
    assert "token" not in json.dumps(result.to_json_dict())


def test_deployment_classifies_creation_and_invocation_http_failures() -> None:
    from src.app.services.foundry_agent_deployment import FoundryAgentDeployment

    creation_client = FakeProjectClient(
        _valid_output(), create_error=StatusCodeError(500)
    )
    creation_result = FoundryAgentDeployment(
        project_client_factory=lambda endpoint: creation_client,
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    ).create_and_validate(_request())

    invocation_client = FakeProjectClient(
        _valid_output(), invoke_error=StatusCodeError(500)
    )
    invocation_result = FoundryAgentDeployment(
        project_client_factory=lambda endpoint: invocation_client,
        prompt_agent_definition_factory=lambda **kwargs: SimpleNamespace(**kwargs),
    ).create_and_validate(_request())

    assert creation_result.category == "agent_version_creation_failed"
    assert invocation_result.category == "agent_invocation_failed"
