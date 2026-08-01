from dataclasses import replace
import importlib
import inspect
import json

import pytest

from src.app.services.hosted_foundry_agent_invocation import (
    HostedFoundryAgentInvocationResult,
)
from src.app.services.hosted_foundry_agent_verification import (
    HostedFoundryAgentVerificationResult,
)


_UNSET = object()


def _proof_module():
    return importlib.import_module("src.app.services.hosted_foundry_agent_proof")


def _request():
    return _proof_module().build_hosted_foundry_agent_proof_check_request(mode="live")


def _hosted_environment(name: str) -> object:
    return {
        "WEBSITE_INSTANCE_ID": "fictional-instance",
        "IDENTITY_ENDPOINT": "http://identity.internal/metadata",
        "IDENTITY_HEADER": "fictional-sensitive-header",
    }.get(name)


class _Verifier:
    def __init__(self, result: object, calls: list[object]) -> None:
        self._result = result
        self._calls = calls

    def verify(self, request: object) -> object:
        self._calls.append(request)
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


class _Invoker:
    def __init__(self, result: object, calls: list[object]) -> None:
        self._result = result
        self._calls = calls

    def invoke(self, request: object) -> object:
        self._calls.append(request)
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _service(
    *,
    verification: object = _UNSET,
    invocation: object = _UNSET,
    verification_calls: list[object] | None = None,
    invocation_calls: list[object] | None = None,
    environment_reader=_hosted_environment,
):
    proof = _proof_module()
    verification_calls = verification_calls if verification_calls is not None else []
    invocation_calls = invocation_calls if invocation_calls is not None else []
    verification = (
        HostedFoundryAgentVerificationResult.success("live")
        if verification is _UNSET
        else verification
    )
    invocation = (
        HostedFoundryAgentInvocationResult.success()
        if invocation is _UNSET
        else invocation
    )
    return proof.HostedFoundryAgentProof(
        verification_factory=lambda: _Verifier(verification, verification_calls),
        invocation_factory=lambda: _Invoker(invocation, invocation_calls),
        environment_reader=environment_reader,
    )


def test_check_is_successful_deterministic_and_constructs_no_live_dependency() -> None:
    proof = _proof_module()
    service = proof.HostedFoundryAgentProof(
        verification_factory=lambda: pytest.fail("check must not create a verifier"),
        invocation_factory=lambda: pytest.fail("check must not create an invoker"),
        environment_reader=lambda _name: pytest.fail("check must not read hosted markers"),
    )
    request = proof.build_hosted_foundry_agent_proof_check_request(mode="check")

    first = service.check(request)
    second = service.check(request)

    assert first == second
    assert first.ok is True
    assert first.category == "check_passed"
    assert first.mode == "check"
    assert first.execution_boundary == "app_service_ssh"
    assert first.local_contract_validated is True
    for field in (
        "command_execution_attempted",
        "hosted_environment_present",
        "managed_identity_attempted",
        "metadata_verification_attempted",
        "metadata_verified",
        "agent_invocation_attempted",
        "agent_output_valid",
        "route_invoked",
        "persistence_attempted",
        "notification_attempted",
        "deterministic_rules_executed",
        "azure_call_made",
        "azure_mutation_made",
    ):
        assert getattr(first, field) is False
    assert first.fictional_data_only is True
    assert json.dumps(first.to_json_dict(), sort_keys=True) == json.dumps(
        second.to_json_dict(), sort_keys=True
    )


def test_invalid_hosted_environment_stops_before_either_dependency() -> None:
    proof = _proof_module()
    service = proof.HostedFoundryAgentProof(
        verification_factory=lambda: pytest.fail("invalid environment must stop"),
        invocation_factory=lambda: pytest.fail("invalid environment must stop"),
        environment_reader=lambda _name: None,
    )

    result = service.prove(_request())

    assert result.category == "not_running_in_hosted_environment"
    assert result.metadata_verification_attempted is False
    assert result.agent_invocation_attempted is False
    assert result.azure_call_made is False


def test_verification_failure_blocks_invocation() -> None:
    invocation_calls: list[object] = []
    service = _service(
        verification=HostedFoundryAgentVerificationResult.failure(
            "live", "authentication_or_authorization_failed"
        ),
        invocation_calls=invocation_calls,
    )

    result = service.prove(_request())

    assert result.category == "metadata_verification_failed"
    assert result.metadata_verification_attempted is True
    assert result.metadata_verified is False
    assert result.agent_invocation_attempted is False
    assert invocation_calls == []


def test_sdk_unavailable_before_managed_identity_reports_no_azure_call() -> None:
    invocation_calls: list[object] = []
    service = _service(
        verification=HostedFoundryAgentVerificationResult.failure(
            "live",
            "sdk_unavailable",
            local_contract_validated=True,
        ),
        invocation_calls=invocation_calls,
    )

    result = service.prove(_request())

    assert result.category == "metadata_verification_failed"
    assert result.metadata_verification_attempted is True
    assert result.managed_identity_attempted is False
    assert result.azure_call_made is False
    assert result.agent_invocation_attempted is False
    assert invocation_calls == []


@pytest.mark.parametrize("verification", [object(), {"ok": True}, None])
def test_wrong_or_malformed_verification_result_blocks_invocation(
    verification: object,
) -> None:
    invocation_calls: list[object] = []

    result = _service(
        verification=verification,
        invocation_calls=invocation_calls,
    ).prove(_request())

    assert result.category == "metadata_result_invalid"
    assert result.agent_invocation_attempted is False
    assert invocation_calls == []


@pytest.mark.parametrize(
    "field",
    [
        "local_contract_validated",
        "hosted_environment_present",
        "managed_identity_attempted",
        "managed_identity_authenticated",
        "project_access_verified",
        "agent_present",
        "configured_version_present",
        "agent_contract_verified",
    ],
)
@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_every_verification_proof_must_be_exact_true(field: str, value: object) -> None:
    invocation_calls: list[object] = []
    malformed = replace(
        HostedFoundryAgentVerificationResult.success("live"),
        **{field: value},
    )

    result = _service(
        verification=malformed,
        invocation_calls=invocation_calls,
    ).prove(_request())

    assert result.category == "metadata_proof_incomplete"
    assert invocation_calls == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_invocation_attempted", True),
        ("azure_mutation_made", True),
        ("category", "unknown"),
        ("mode", "unknown"),
        ("operation", "unknown"),
    ],
)
def test_unknown_or_unsafe_verification_state_blocks_invocation(
    field: str,
    value: object,
) -> None:
    invocation_calls: list[object] = []
    malformed = replace(
        HostedFoundryAgentVerificationResult.success("live"),
        **{field: value},
    )

    result = _service(
        verification=malformed,
        invocation_calls=invocation_calls,
    ).prove(_request())

    assert result.category == "metadata_proof_incomplete"
    assert invocation_calls == []


def test_verification_exception_is_sanitized_and_blocks_invocation() -> None:
    invocation_calls: list[object] = []
    secret = "secret-endpoint.example/agent/raw-response"

    result = _service(
        verification=RuntimeError(secret),
        invocation_calls=invocation_calls,
    ).prove(_request())

    assert result.category == "metadata_verification_failed"
    assert secret not in json.dumps(result.to_json_dict())
    assert invocation_calls == []


def test_valid_verification_causes_exactly_one_fixed_invocation() -> None:
    verification_calls: list[object] = []
    invocation_calls: list[object] = []

    result = _service(
        verification_calls=verification_calls,
        invocation_calls=invocation_calls,
    ).prove(_request())

    assert result.ok is True
    assert result.category == "success"
    assert result.metadata_verified is True
    assert result.agent_invocation_attempted is True
    assert result.agent_output_valid is True
    assert result.azure_call_made is True
    assert len(verification_calls) == 1
    assert len(invocation_calls) == 1
    assert invocation_calls[0].fictional_intake_text
    assert invocation_calls[0].managed_identity_client_id is None


@pytest.mark.parametrize("invocation", [object(), {"ok": True}, None])
def test_wrong_invocation_result_type_fails_closed(invocation: object) -> None:
    result = _service(invocation=invocation).prove(_request())

    assert result.category == "invocation_result_invalid"
    assert result.ok is False
    assert result.agent_output_valid is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ok", 1),
        ("category", "unknown"),
        ("invocation_attempted", "true"),
        ("agent_output_valid", None),
        ("fields_present", ("extraction",)),
        ("fictional_data_only", 1),
        ("message", "unsafe"),
        ("recommended_next_step", "unsafe"),
    ],
)
def test_malformed_invocation_result_fails_closed(field: str, value: object) -> None:
    malformed = replace(
        HostedFoundryAgentInvocationResult.success(),
        **{field: value},
    )

    result = _service(invocation=malformed).prove(_request())

    assert result.category == "invocation_result_invalid"
    assert result.agent_output_valid is False


def test_invalid_agent_output_fails_closed() -> None:
    invalid = HostedFoundryAgentInvocationResult.failure(
        "contract_invalid", invocation_attempted=True
    )

    result = _service(invocation=invalid).prove(_request())

    assert result.category == "agent_output_invalid"
    assert result.agent_invocation_attempted is True
    assert result.agent_output_valid is False


def test_invocation_exception_is_sanitized_and_not_retried() -> None:
    calls: list[object] = []
    secret = "secret-generated-clinical-content"

    result = _service(
        invocation=RuntimeError(secret),
        invocation_calls=calls,
    ).prove(_request())

    assert result.category == "invocation_failed"
    assert len(calls) == 1
    assert secret not in json.dumps(result.to_json_dict())


def test_result_schema_has_only_sanitized_status_and_safety_fields() -> None:
    result = _service().prove(_request())
    payload = result.to_json_dict()

    assert set(payload) == {
        "agent_invocation_attempted",
        "agent_output_valid",
        "azure_call_made",
        "azure_mutation_made",
        "category",
        "command_execution_attempted",
        "deterministic_rules_executed",
        "execution_boundary",
        "fictional_data_only",
        "hosted_environment_present",
        "local_contract_validated",
        "managed_identity_attempted",
        "metadata_verification_attempted",
        "metadata_verified",
        "mode",
        "notification_attempted",
        "ok",
        "operation",
        "persistence_attempted",
        "route_invoked",
    }
    serialized = json.dumps(payload, sort_keys=True)
    for forbidden in (
        "fictional-sensitive-header",
        "identity.internal",
        "configured-agent",
        "project-endpoint",
        "agent-version",
        "model-deployment",
        "prompt",
        "patient",
        "handoffNote",
        "Traceback",
        "/home/",
    ):
        assert forbidden not in serialized


def test_service_has_no_runtime_side_effect_or_transport_surface() -> None:
    source = inspect.getsource(_proof_module())

    for forbidden in (
        "CaseProcessingService",
        "UrgencyRulesService",
        "case_repository",
        "notification_sender",
        "subprocess",
        "requests",
        "httpx",
        "paramiko",
        "WebJob",
        "Kudu",
        "retry(",
        "poll(",
    ):
        assert forbidden not in source
