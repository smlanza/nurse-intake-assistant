from dataclasses import dataclass
from importlib.util import find_spec
from typing import Any, Callable, Literal

from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_instructions,
)
from src.app.services.foundry_agent_client import (
    is_valid_stable_agent_endpoint,
    stable_agent_endpoint_matches_configuration,
)
from src.app.services.foundry_credential_factory import (
    FoundryCredentialConfiguration,
    FoundryCredentialFactory,
)


VerificationCategory = Literal[
    "success",
    "missing_configuration",
    "agent_version_not_found",
    "definition_mismatch",
    "response_contract_invalid",
    "sdk_unavailable",
    "authentication_or_authorization_failed",
    "agent_verification_failed",
    "legacy_agent_model",
    "stable_endpoint_missing",
    "stable_endpoint_invalid",
    "stable_endpoint_mismatch",
    "version_routing_mismatch",
]
VERIFICATION_OPERATION = "verify_prompt_agent"
VERIFICATION_SUCCESS_MESSAGE = "Foundry prompt-agent verification completed."
VERIFICATION_FAILURE_MESSAGE = "Foundry prompt-agent verification did not complete."
VERIFICATION_NEXT_STEP = (
    "Run the separate fictional-data Foundry Agent smoke only after verification "
    "succeeds; nurse review remains required."
)
LEGACY_AGENT_NEXT_STEP = (
    "The agent must be recreated through the existing prompt-agent provisioning "
    "workflow, then configured with its stable endpoint and immutable version."
)


@dataclass(frozen=True)
class FoundryAgentVerificationRequest:
    project_endpoint: str
    agent_name: str
    agent_version: str
    model_deployment_name: str
    instructions: str
    managed_identity_client_id: str | None = None
    stable_agent_endpoint: str | None = None


@dataclass(frozen=True)
class VersionRoutingValidation:
    valid: bool
    configured_version_traffic_percentage: int | None


def build_foundry_agent_verification_request(
    settings: Any,
) -> FoundryAgentVerificationRequest:
    """Build the shared immutable-version verification request from settings."""

    return FoundryAgentVerificationRequest(
        project_endpoint=settings.azure_ai_foundry_agent_project_endpoint,
        stable_agent_endpoint=getattr(
            settings,
            "azure_ai_foundry_agent_endpoint",
            None,
        ),
        agent_name=settings.azure_ai_foundry_agent_name,
        agent_version=settings.azure_ai_foundry_agent_version,
        model_deployment_name=settings.azure_ai_foundry_model_deployment_name,
        instructions=build_nurse_intake_agent_instructions(),
        managed_identity_client_id=getattr(
            settings,
            "azure_ai_foundry_managed_identity_client_id",
            None,
        ),
    )


@dataclass(frozen=True)
class FoundryAgentVerificationResult:
    ok: bool
    mode: Literal["live"]
    operation: str
    category: VerificationCategory
    message: str
    agent_name_present: bool
    agent_version_present: bool
    model_deployment_name_present: bool
    instruction_version: str
    agent_definition_matches: bool
    agent_identity_present: bool
    stable_endpoint_present: bool
    version_selector_present: bool
    responses_protocol_present: bool
    stable_endpoint_matches_configuration: bool
    configured_version_traffic_percentage: int | None
    immutable_version_verified: bool
    azure_lookup_attempted: bool
    agent_invoked: bool
    azure_mutation_made: bool
    recommended_next_step: str

    @classmethod
    def success(
        cls,
        *,
        agent_identity_present: bool = False,
        stable_endpoint_present: bool = False,
        stable_endpoint_matches_configuration: bool = False,
        version_selector_present: bool = False,
        responses_protocol_present: bool = False,
        configured_version_traffic_percentage: int | None = None,
    ) -> "FoundryAgentVerificationResult":
        immutable_version_verified = bool(
            agent_identity_present
            and stable_endpoint_present
            and stable_endpoint_matches_configuration
            and version_selector_present
            and responses_protocol_present
            and configured_version_traffic_percentage == 100
        )
        return cls(
            ok=True,
            mode="live",
            operation=VERIFICATION_OPERATION,
            category="success",
            message=VERIFICATION_SUCCESS_MESSAGE,
            agent_name_present=True,
            agent_version_present=True,
            model_deployment_name_present=True,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            agent_definition_matches=True,
            agent_identity_present=agent_identity_present,
            stable_endpoint_present=stable_endpoint_present,
            stable_endpoint_matches_configuration=(
                stable_endpoint_matches_configuration
            ),
            version_selector_present=version_selector_present,
            responses_protocol_present=responses_protocol_present,
            configured_version_traffic_percentage=(
                configured_version_traffic_percentage
            ),
            immutable_version_verified=immutable_version_verified,
            azure_lookup_attempted=True,
            agent_invoked=False,
            azure_mutation_made=False,
            recommended_next_step=VERIFICATION_NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        category: VerificationCategory,
        *,
        agent_name_present: bool = False,
        agent_version_present: bool = False,
        model_deployment_name_present: bool = False,
        azure_lookup_attempted: bool = False,
        agent_identity_present: bool = False,
        stable_endpoint_present: bool = False,
        version_selector_present: bool = False,
        responses_protocol_present: bool = False,
        stable_endpoint_matches_configuration: bool = False,
        configured_version_traffic_percentage: int | None = None,
    ) -> "FoundryAgentVerificationResult":
        return cls(
            ok=False,
            mode="live",
            operation=VERIFICATION_OPERATION,
            category=category,
            message=VERIFICATION_FAILURE_MESSAGE,
            agent_name_present=agent_name_present,
            agent_version_present=agent_version_present,
            model_deployment_name_present=model_deployment_name_present,
            instruction_version=NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
            agent_definition_matches=False,
            agent_identity_present=agent_identity_present,
            stable_endpoint_present=stable_endpoint_present,
            version_selector_present=version_selector_present,
            responses_protocol_present=responses_protocol_present,
            stable_endpoint_matches_configuration=(
                stable_endpoint_matches_configuration
            ),
            configured_version_traffic_percentage=(
                configured_version_traffic_percentage
            ),
            immutable_version_verified=False,
            azure_lookup_attempted=azure_lookup_attempted,
            agent_invoked=False,
            azure_mutation_made=False,
            recommended_next_step=(
                LEGACY_AGENT_NEXT_STEP
                if category == "legacy_agent_model"
                else VERIFICATION_NEXT_STEP
            ),
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "operation": self.operation,
            "category": self.category,
            "message": self.message,
            "agent_name_present": self.agent_name_present,
            "agent_version_present": self.agent_version_present,
            "model_deployment_name_present": self.model_deployment_name_present,
            "instruction_version": self.instruction_version,
            "agent_definition_matches": self.agent_definition_matches,
            "agent_identity_present": self.agent_identity_present,
            "stable_endpoint_present": self.stable_endpoint_present,
            "version_selector_present": self.version_selector_present,
            "responses_protocol_present": self.responses_protocol_present,
            "stable_endpoint_matches_configuration": (
                self.stable_endpoint_matches_configuration
            ),
            "configured_version_traffic_percentage": (
                self.configured_version_traffic_percentage
            ),
            "immutable_version_verified": self.immutable_version_verified,
            "agent_invoked": self.agent_invoked,
            "azure_mutation_made": self.azure_mutation_made,
            "recommended_next_step": self.recommended_next_step,
        }


class FoundryAgentVerification:
    """Read-only verification of one configured immutable prompt-agent version."""

    def __init__(
        self,
        *,
        project_client_factory: Callable[[str], Any] | None = None,
    ) -> None:
        self.project_client_factory = project_client_factory

    def verify(
        self,
        request: FoundryAgentVerificationRequest,
    ) -> FoundryAgentVerificationResult:
        presence = {
            "agent_name_present": bool(request.agent_name),
            "agent_version_present": bool(request.agent_version),
            "model_deployment_name_present": bool(request.model_deployment_name),
        }
        azure_lookup_attempted = False
        metadata_presence = {
            "agent_identity_present": False,
            "stable_endpoint_present": False,
            "version_selector_present": False,
            "responses_protocol_present": False,
            "stable_endpoint_matches_configuration": False,
            "configured_version_traffic_percentage": None,
        }
        routing_validation = VersionRoutingValidation(False, None)
        stable_endpoint_requested = request.stable_agent_endpoint is not None
        if not request.project_endpoint:
            return FoundryAgentVerificationResult.failure(
                "missing_configuration",
                **presence,
            )
        if stable_endpoint_requested and not is_valid_stable_agent_endpoint(
            request.stable_agent_endpoint
        ):
            return FoundryAgentVerificationResult.failure(
                "stable_endpoint_invalid",
                **presence,
            )
        if stable_endpoint_requested and not stable_agent_endpoint_matches_configuration(
            project_endpoint=request.project_endpoint,
            stable_agent_endpoint=request.stable_agent_endpoint,
            agent_name=request.agent_name,
        ):
            return FoundryAgentVerificationResult.failure(
                "stable_endpoint_mismatch",
                **presence,
            )
        try:
            if self.project_client_factory is None:
                project_client = _create_live_project_client(
                    request.project_endpoint,
                    request.managed_identity_client_id,
                )
            else:
                project_client = self.project_client_factory(
                    request.project_endpoint
                )
            azure_lookup_attempted = True
            if stable_endpoint_requested:
                remote_agent = project_client.agents.get(request.agent_name)
                metadata_presence, routing_validation = _new_agent_metadata_presence(
                    remote_agent,
                    request,
                )
                if not metadata_presence["agent_identity_present"]:
                    return FoundryAgentVerificationResult.failure(
                        "legacy_agent_model",
                        azure_lookup_attempted=True,
                        **presence,
                        **metadata_presence,
                    )
                if not metadata_presence["stable_endpoint_present"]:
                    return FoundryAgentVerificationResult.failure(
                        "stable_endpoint_missing",
                        azure_lookup_attempted=True,
                        **presence,
                        **metadata_presence,
                    )
                if not metadata_presence["responses_protocol_present"]:
                    return FoundryAgentVerificationResult.failure(
                        "response_contract_invalid",
                        azure_lookup_attempted=True,
                        **presence,
                        **metadata_presence,
                    )
                if not routing_validation.valid:
                    return FoundryAgentVerificationResult.failure(
                        "version_routing_mismatch",
                        azure_lookup_attempted=True,
                        **presence,
                        **metadata_presence,
                    )
            remote_version = project_client.agents.get_version(
                request.agent_name,
                request.agent_version,
            )
        except Exception as exc:
            return FoundryAgentVerificationResult.failure(
                _category_for_exception(exc),
                azure_lookup_attempted=azure_lookup_attempted,
                **metadata_presence,
                **presence,
            )

        if not _remote_contract_is_valid(remote_version, request):
            return FoundryAgentVerificationResult.failure(
                "response_contract_invalid",
                azure_lookup_attempted=True,
                **metadata_presence,
                **presence,
            )

        if not _definition_matches(remote_version, request):
            return FoundryAgentVerificationResult.failure(
                "definition_mismatch",
                azure_lookup_attempted=True,
                **metadata_presence,
                **presence,
            )

        return FoundryAgentVerificationResult.success(
            **metadata_presence,
        )


def foundry_agent_verification_sdk_available() -> bool:
    try:
        return (
            find_spec("azure.ai.projects") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _create_live_project_client(
    project_endpoint: str,
    managed_identity_client_id: str | None = None,
) -> Any:
    project_client_class = _get_ai_project_client_class()
    credential = FoundryCredentialFactory().create(
        FoundryCredentialConfiguration(managed_identity_client_id)
    )
    return project_client_class(
        endpoint=project_endpoint,
        credential=credential,
    )


def _get_ai_project_client_class():
    from azure.ai.projects import AIProjectClient

    return AIProjectClient


def _remote_contract_is_valid(
    remote_version: Any,
    request: FoundryAgentVerificationRequest,
) -> bool:
    return (
        _object_value(remote_version, "name") == request.agent_name
        and _object_value(remote_version, "version") == request.agent_version
        and _raw_object_value(remote_version, "definition") is not None
    )


def _new_agent_metadata_presence(
    remote_agent: Any,
    request: FoundryAgentVerificationRequest,
) -> tuple[dict[str, Any], VersionRoutingValidation]:
    """Collect independent, sanitized metadata signals from one remote agent.

    ``stable_endpoint_present`` means the remote agent exposes an endpoint object
    and the locally configured deterministic URL is valid. The SDK response does
    not expose a remote endpoint URL to compare.
    ``stable_endpoint_matches_configuration`` means that local URL matches the
    configured project and agent name.
    """

    identity = _raw_object_value(remote_agent, "instance_identity")
    identity_present = bool(
        _object_value(remote_agent, "id")
        and identity is not None
        and _object_value(identity, "client_id")
    )
    endpoint = _raw_object_value(remote_agent, "agent_endpoint")
    stable_endpoint_present = bool(
        endpoint is not None
        and is_valid_stable_agent_endpoint(request.stable_agent_endpoint)
    )
    endpoint_matches_configuration = bool(
        stable_endpoint_present
        and stable_agent_endpoint_matches_configuration(
            project_endpoint=request.project_endpoint,
            stable_agent_endpoint=request.stable_agent_endpoint,
            agent_name=request.agent_name,
        )
    )
    version_selector = _raw_object_value(endpoint, "version_selector")
    rules = _raw_object_value(version_selector, "version_selection_rules")
    version_selector_present = bool(
        isinstance(rules, (list, tuple)) and rules
    )
    routing_validation = validate_exclusive_immutable_version_routing(
        rules,
        request.agent_version,
    )
    responses_protocol_present = _responses_protocol_is_present(endpoint)
    return {
        "agent_identity_present": identity_present,
        "stable_endpoint_present": stable_endpoint_present,
        "version_selector_present": version_selector_present,
        "responses_protocol_present": responses_protocol_present,
        "stable_endpoint_matches_configuration": endpoint_matches_configuration,
        "configured_version_traffic_percentage": (
            routing_validation.configured_version_traffic_percentage
        ),
    }, routing_validation


def _responses_protocol_is_present(endpoint: Any) -> bool:
    protocols = _raw_object_value(endpoint, "protocols")
    if not isinstance(protocols, (list, tuple)):
        return False
    return any(
        isinstance(protocol, str)
        and protocol.strip().lower() == "responses"
        for protocol in protocols
    )


def validate_exclusive_immutable_version_routing(
    rules: Any,
    configured_version: str,
) -> VersionRoutingValidation:
    """Validate one unambiguous FixedRatio allocation with exact total traffic."""

    if not isinstance(rules, (list, tuple)) or not rules:
        return VersionRoutingValidation(False, None)
    if not isinstance(configured_version, str) or not configured_version:
        return VersionRoutingValidation(False, None)

    seen_versions: set[str] = set()
    total_traffic = 0
    configured_traffic: int | None = None
    for rule in rules:
        rule_type = _raw_object_value(rule, "type")
        version = _raw_object_value(rule, "agent_version")
        traffic = _raw_object_value(rule, "traffic_percentage")
        if (
            rule_type != "FixedRatio"
            or not isinstance(version, str)
            or not version
            or version.strip() != version
            or version in seen_versions
            or isinstance(traffic, bool)
            or not isinstance(traffic, int)
            or not 0 <= traffic <= 100
        ):
            return VersionRoutingValidation(False, configured_traffic)
        seen_versions.add(version)
        total_traffic += traffic
        if version == configured_version:
            configured_traffic = traffic

    valid = bool(
        configured_traffic == 100
        and total_traffic == 100
        and all(
            _raw_object_value(rule, "agent_version") == configured_version
            or _raw_object_value(rule, "traffic_percentage") == 0
            for rule in rules
        )
    )
    return VersionRoutingValidation(valid, configured_traffic)


def _definition_matches(
    remote_version: Any,
    request: FoundryAgentVerificationRequest,
) -> bool:
    definition = _raw_object_value(remote_version, "definition")
    return (
        _object_value(definition, "model") == request.model_deployment_name
        and _object_value(definition, "instructions") == request.instructions
    )


def _raw_object_value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _object_value(value: Any, name: str) -> str:
    raw_value = _raw_object_value(value, name)
    return str(raw_value).strip() if raw_value is not None else ""


def _category_for_exception(error: BaseException) -> VerificationCategory:
    for current in _exception_chain(error):
        if getattr(current, "category", None) == "sdk_unavailable":
            return "sdk_unavailable"
        status = _status_code(current)
        if status == 404:
            return "agent_version_not_found"
        if status in {401, 403}:
            return "authentication_or_authorization_failed"
        name = type(current).__name__.lower()
        if "authentication" in name or "credential" in name or "forbidden" in name:
            return "authentication_or_authorization_failed"
        if isinstance(current, (ImportError, ModuleNotFoundError)):
            return "sdk_unavailable"
    return "agent_verification_failed"


def _exception_chain(error: BaseException):
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _status_code(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(error, "response", None)
    response_status = getattr(response, "status_code", None)
    return response_status if isinstance(response_status, int) else None
