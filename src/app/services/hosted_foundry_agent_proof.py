from collections.abc import Callable
from dataclasses import dataclass
import os
from typing import Any, Literal

from src.app.services.hosted_foundry_agent_invocation import (
    HostedFoundryAgentInvocation,
    HostedFoundryAgentInvocationRequest,
    HostedFoundryAgentInvocationResult,
    build_hosted_foundry_agent_invocation_request,
)
from src.app.services.hosted_foundry_agent_verification import (
    HostedFoundryAgentVerification,
    HostedFoundryAgentVerificationRequest,
    HostedFoundryAgentVerificationResult,
    _hosted_environment_valid,
    build_hosted_foundry_agent_verification_request,
)


HostedProofMode = Literal["check", "live"]
HostedProofCategory = Literal[
    "check_passed",
    "success",
    "configuration_invalid",
    "dependency_check_failed",
    "not_running_in_hosted_environment",
    "metadata_verification_failed",
    "metadata_result_invalid",
    "metadata_proof_incomplete",
    "invocation_failed",
    "invocation_result_invalid",
    "agent_output_invalid",
    "unexpected_error",
]

OPERATION = "prove_hosted_foundry_agent"
EXECUTION_BOUNDARY = "app_service_ssh"


@dataclass(frozen=True)
class HostedFoundryAgentProofRequest:
    mode: str
    verification: HostedFoundryAgentVerificationRequest
    invocation: HostedFoundryAgentInvocationRequest


@dataclass(frozen=True)
class HostedFoundryAgentProofResult:
    ok: bool
    category: HostedProofCategory
    operation: str
    mode: str
    execution_boundary: str
    command_execution_attempted: bool
    local_contract_validated: bool
    hosted_environment_present: bool
    managed_identity_attempted: bool
    metadata_verification_attempted: bool
    metadata_verified: bool
    agent_invocation_attempted: bool
    agent_output_valid: bool
    fictional_data_only: bool
    route_invoked: bool
    persistence_attempted: bool
    notification_attempted: bool
    deterministic_rules_executed: bool
    azure_call_made: bool
    azure_mutation_made: bool

    @classmethod
    def check_passed(cls) -> "HostedFoundryAgentProofResult":
        return cls._build(ok=True, category="check_passed", mode="check")

    @classmethod
    def success(cls) -> "HostedFoundryAgentProofResult":
        return cls._build(
            ok=True,
            category="success",
            mode="live",
            command_execution_attempted=True,
            local_contract_validated=True,
            hosted_environment_present=True,
            managed_identity_attempted=True,
            metadata_verification_attempted=True,
            metadata_verified=True,
            agent_invocation_attempted=True,
            agent_output_valid=True,
            azure_call_made=True,
        )

    @classmethod
    def failure(
        cls,
        mode: str,
        category: HostedProofCategory,
        **progress: bool,
    ) -> "HostedFoundryAgentProofResult":
        return cls._build(
            ok=False,
            category=category,
            mode=mode if mode in {"check", "live"} else "invalid",
            **progress,
        )

    @classmethod
    def _build(
        cls,
        *,
        ok: bool,
        category: HostedProofCategory,
        mode: str,
        command_execution_attempted: bool = False,
        local_contract_validated: bool = True,
        hosted_environment_present: bool = False,
        managed_identity_attempted: bool = False,
        metadata_verification_attempted: bool = False,
        metadata_verified: bool = False,
        agent_invocation_attempted: bool = False,
        agent_output_valid: bool = False,
        azure_call_made: bool = False,
    ) -> "HostedFoundryAgentProofResult":
        return cls(
            ok=ok,
            category=category,
            operation=OPERATION,
            mode=mode,
            execution_boundary=EXECUTION_BOUNDARY,
            command_execution_attempted=command_execution_attempted,
            local_contract_validated=local_contract_validated,
            hosted_environment_present=hosted_environment_present,
            managed_identity_attempted=managed_identity_attempted,
            metadata_verification_attempted=metadata_verification_attempted,
            metadata_verified=metadata_verified,
            agent_invocation_attempted=agent_invocation_attempted,
            agent_output_valid=agent_output_valid,
            fictional_data_only=True,
            route_invoked=False,
            persistence_attempted=False,
            notification_attempted=False,
            deterministic_rules_executed=False,
            azure_call_made=azure_call_made,
            azure_mutation_made=False,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "execution_boundary": self.execution_boundary,
            "command_execution_attempted": self.command_execution_attempted,
            "local_contract_validated": self.local_contract_validated,
            "hosted_environment_present": self.hosted_environment_present,
            "managed_identity_attempted": self.managed_identity_attempted,
            "metadata_verification_attempted": self.metadata_verification_attempted,
            "metadata_verified": self.metadata_verified,
            "agent_invocation_attempted": self.agent_invocation_attempted,
            "agent_output_valid": self.agent_output_valid,
            "fictional_data_only": self.fictional_data_only,
            "route_invoked": self.route_invoked,
            "persistence_attempted": self.persistence_attempted,
            "notification_attempted": self.notification_attempted,
            "deterministic_rules_executed": self.deterministic_rules_executed,
            "azure_call_made": self.azure_call_made,
            "azure_mutation_made": self.azure_mutation_made,
        }


class _CheckSettings:
    azure_ai_foundry_agent_project_endpoint = (
        "https://contract.example.invalid/api/projects/contract-project"
    )
    azure_ai_foundry_agent_endpoint = (
        "https://contract.example.invalid/api/projects/contract-project/agents/"
        "contract-agent/endpoint/protocols/openai"
    )
    azure_ai_foundry_agent_name = "contract-agent"
    azure_ai_foundry_agent_version = "1"
    azure_ai_foundry_model_deployment_name = "contract-model"
    azure_ai_foundry_managed_identity_client_id = None


def build_hosted_foundry_agent_proof_check_request(
    *,
    mode: str = "check",
) -> HostedFoundryAgentProofRequest:
    return build_hosted_foundry_agent_proof_request(_CheckSettings(), mode=mode)


def build_hosted_foundry_agent_proof_request(
    settings: Any,
    *,
    mode: str,
) -> HostedFoundryAgentProofRequest:
    return HostedFoundryAgentProofRequest(
        mode=mode,
        verification=build_hosted_foundry_agent_verification_request(
            settings,
            mode=mode,
        ),
        invocation=build_hosted_foundry_agent_invocation_request(
            settings,
            mode=mode,
        ),
    )


def _check_verification_dependency(
    request: HostedFoundryAgentVerificationRequest,
) -> HostedFoundryAgentVerificationResult:
    return HostedFoundryAgentVerification().check(request)


def _check_invocation_dependency(
    request: HostedFoundryAgentInvocationRequest,
) -> HostedFoundryAgentInvocationResult:
    return HostedFoundryAgentInvocation().check(request)


class HostedFoundryAgentProof:
    """Compose hosted metadata and one fixed-fictional invocation fail-closed."""

    def __init__(
        self,
        *,
        verification_checker: Callable[
            [HostedFoundryAgentVerificationRequest], object
        ] = _check_verification_dependency,
        invocation_checker: Callable[
            [HostedFoundryAgentInvocationRequest], object
        ] = _check_invocation_dependency,
        verification_factory: Callable[[], object] = HostedFoundryAgentVerification,
        invocation_factory: Callable[[], object] = HostedFoundryAgentInvocation,
        environment_reader: Callable[[str], object] = os.getenv,
    ) -> None:
        self._verification_checker = verification_checker
        self._invocation_checker = invocation_checker
        self._verification_factory = verification_factory
        self._invocation_factory = invocation_factory
        self._environment_reader = environment_reader

    def check(
        self,
        request: HostedFoundryAgentProofRequest,
    ) -> HostedFoundryAgentProofResult:
        if not _request_contract_valid(request, expected_mode="check"):
            return HostedFoundryAgentProofResult.failure(
                request.mode,
                "configuration_invalid",
                local_contract_validated=False,
            )
        try:
            verification = self._verification_checker(request.verification)
            invocation = self._invocation_checker(request.invocation)
        except Exception:
            return HostedFoundryAgentProofResult.failure(
                "check", "dependency_check_failed"
            )
        if not (
            _exact_verification_result(
                verification,
                HostedFoundryAgentVerificationResult.success("check"),
            )
            and _exact_invocation_result(
                invocation,
                HostedFoundryAgentInvocationResult.check_complete(),
            )
        ):
            return HostedFoundryAgentProofResult.failure(
                "check", "dependency_check_failed"
            )
        return HostedFoundryAgentProofResult.check_passed()

    def prove(
        self,
        request: HostedFoundryAgentProofRequest,
    ) -> HostedFoundryAgentProofResult:
        if not _request_contract_valid(request, expected_mode="live"):
            return HostedFoundryAgentProofResult.failure(
                request.mode,
                "configuration_invalid",
                command_execution_attempted=True,
                local_contract_validated=False,
            )
        if not _hosted_environment_valid(self._environment_reader):
            return HostedFoundryAgentProofResult.failure(
                "live",
                "not_running_in_hosted_environment",
                command_execution_attempted=True,
            )

        common_progress = {
            "command_execution_attempted": True,
            "hosted_environment_present": True,
        }
        try:
            verifier = self._verification_factory()
            verification = verifier.verify(request.verification)
        except Exception:
            return HostedFoundryAgentProofResult.failure(
                "live",
                "metadata_verification_failed",
                metadata_verification_attempted=True,
                azure_call_made=True,
                **common_progress,
            )
        if type(verification) is not HostedFoundryAgentVerificationResult:
            return HostedFoundryAgentProofResult.failure(
                "live",
                "metadata_result_invalid",
                metadata_verification_attempted=True,
                azure_call_made=True,
                **common_progress,
            )
        verification_progress = {
            **common_progress,
            "managed_identity_attempted": verification.managed_identity_attempted
            is True,
            "metadata_verification_attempted": True,
            "azure_call_made": verification.managed_identity_attempted is True,
        }
        if verification.ok is False:
            return HostedFoundryAgentProofResult.failure(
                "live",
                "metadata_verification_failed",
                **verification_progress,
            )
        if not _exact_verification_result(
            verification,
            HostedFoundryAgentVerificationResult.success("live"),
        ):
            return HostedFoundryAgentProofResult.failure(
                "live",
                "metadata_proof_incomplete",
                **verification_progress,
            )

        verified_progress = {
            **verification_progress,
            "metadata_verified": True,
        }
        try:
            invoker = self._invocation_factory()
            invocation = invoker.invoke(request.invocation)
        except Exception:
            return HostedFoundryAgentProofResult.failure(
                "live",
                "invocation_failed",
                agent_invocation_attempted=True,
                **verified_progress,
            )
        if type(invocation) is not HostedFoundryAgentInvocationResult:
            return HostedFoundryAgentProofResult.failure(
                "live",
                "invocation_result_invalid",
                agent_invocation_attempted=True,
                **verified_progress,
            )
        if invocation.ok is False:
            if not _authoritative_invocation_failure(invocation):
                return HostedFoundryAgentProofResult.failure(
                    "live",
                    "invocation_result_invalid",
                    agent_invocation_attempted=False,
                    **verified_progress,
                )
            category: HostedProofCategory = (
                "agent_output_invalid"
                if invocation.invocation_attempted is True
                and invocation.category in {"response_parse_failed", "contract_invalid"}
                else "invocation_failed"
            )
            return HostedFoundryAgentProofResult.failure(
                "live",
                category,
                agent_invocation_attempted=invocation.invocation_attempted is True,
                **verified_progress,
            )
        if not _exact_invocation_result(
            invocation,
            HostedFoundryAgentInvocationResult.success(),
        ):
            return HostedFoundryAgentProofResult.failure(
                "live",
                "invocation_result_invalid",
                agent_invocation_attempted=invocation.invocation_attempted is True,
                **verified_progress,
            )
        return HostedFoundryAgentProofResult.success()


def _exact_verification_result(
    actual: object,
    expected: HostedFoundryAgentVerificationResult,
) -> bool:
    if type(actual) is not HostedFoundryAgentVerificationResult:
        return False
    boolean_fields = (
        "ok",
        "local_contract_validated",
        "hosted_environment_present",
        "managed_identity_attempted",
        "managed_identity_authenticated",
        "project_access_verified",
        "agent_present",
        "configured_version_present",
        "agent_contract_verified",
        "agent_invocation_attempted",
        "azure_mutation_made",
    )
    value_fields = (
        "category",
        "operation",
        "mode",
        "recommended_next_step",
    )
    return bool(
        all(getattr(actual, field) is getattr(expected, field) for field in boolean_fields)
        and all(
            getattr(actual, field) == getattr(expected, field) for field in value_fields
        )
    )


def _exact_invocation_result(
    actual: object,
    expected: HostedFoundryAgentInvocationResult,
) -> bool:
    if type(actual) is not HostedFoundryAgentInvocationResult:
        return False
    return bool(
        actual.ok is expected.ok
        and actual.invocation_attempted is expected.invocation_attempted
        and actual.agent_output_valid is expected.agent_output_valid
        and actual.fictional_data_only is expected.fictional_data_only
        and actual.category == expected.category
        and actual.message == expected.message
        and actual.fields_present == expected.fields_present
        and actual.recommended_next_step == expected.recommended_next_step
    )


def _authoritative_invocation_failure(
    result: HostedFoundryAgentInvocationResult,
) -> bool:
    if result.category in {"check_complete", "success"} or not isinstance(
        result.invocation_attempted, bool
    ):
        return False
    try:
        expected = HostedFoundryAgentInvocationResult.failure(
            result.category,
            invocation_attempted=result.invocation_attempted,
        )
    except (KeyError, TypeError):
        return False
    return _exact_invocation_result(result, expected)


def _request_contract_valid(
    request: object,
    *,
    expected_mode: HostedProofMode,
) -> bool:
    return bool(
        type(request) is HostedFoundryAgentProofRequest
        and request.mode == expected_mode
        and type(request.verification) is HostedFoundryAgentVerificationRequest
        and type(request.invocation) is HostedFoundryAgentInvocationRequest
        and request.verification.mode == expected_mode
        and request.invocation.mode == expected_mode
        and request.verification.project_endpoint == request.invocation.project_endpoint
        and request.verification.stable_agent_endpoint
        == request.invocation.stable_agent_endpoint
        and request.verification.agent_name == request.invocation.agent_name
        and request.verification.agent_version == request.invocation.agent_version
        and request.verification.instructions == request.invocation.instructions
        and request.invocation.managed_identity_client_id is None
    )


def hosted_foundry_agent_proof_check_result_valid(result: object) -> bool:
    if type(result) is not HostedFoundryAgentProofResult:
        return False
    expected = HostedFoundryAgentProofResult.check_passed()
    boolean_fields = (
        "ok",
        "command_execution_attempted",
        "local_contract_validated",
        "hosted_environment_present",
        "managed_identity_attempted",
        "metadata_verification_attempted",
        "metadata_verified",
        "agent_invocation_attempted",
        "agent_output_valid",
        "fictional_data_only",
        "route_invoked",
        "persistence_attempted",
        "notification_attempted",
        "deterministic_rules_executed",
        "azure_call_made",
        "azure_mutation_made",
    )
    value_fields = ("category", "operation", "mode", "execution_boundary")
    return bool(
        all(getattr(result, field) is getattr(expected, field) for field in boolean_fields)
        and all(
            getattr(result, field) == getattr(expected, field) for field in value_fields
        )
    )
