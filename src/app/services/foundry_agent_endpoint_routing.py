from collections.abc import Callable, Mapping
from dataclasses import dataclass
import re
from typing import Any, Literal

from src.app.services.foundry_agent_client import (
    is_valid_stable_agent_endpoint,
    stable_agent_endpoint_matches_configuration,
)
from src.app.services.foundry_credential_factory import (
    FoundryCredentialConfiguration,
    FoundryCredentialFactory,
)
from src.app.services.foundry_agent_verification import (
    validate_exclusive_immutable_version_routing,
)


RoutingCategory = Literal[
    "success",
    "missing_configuration",
    "sdk_unavailable",
    "not_found",
    "authentication_or_authorization_failed",
    "azure_request_failed",
    "response_parse_failed",
    "endpoint_mismatch",
    "responses_protocol_missing",
    "version_routing_mismatch",
    "unexpected_error",
]
ROUTING_OPERATION = "configure_prompt_agent_endpoint_routing"
SUCCESS_MESSAGE = "Foundry prompt-agent endpoint routing configuration completed."
FAILURE_MESSAGE = "Foundry prompt-agent endpoint routing configuration did not complete."
NEXT_STEP = (
    "Run one separately authorized read-only prompt-agent verification; routing "
    "configuration does not prove the final verifier contract."
)
_MISSING = object()
_PROTOCOL_FIELDS = (
    "activity",
    "responses",
    "a2a",
    "mcp",
    "invocations",
    "invocations_ws",
)
_AGENT_NAME_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?")


@dataclass(frozen=True)
class FoundryAgentEndpointRoutingRequest:
    project_endpoint: str
    stable_agent_endpoint: str
    agent_name: str
    agent_version: str
    managed_identity_client_id: str | None = None


@dataclass(frozen=True)
class FoundryAgentEndpointRoutingResult:
    ok: bool
    mode: Literal["check", "live"]
    operation: str
    category: RoutingCategory
    message: str
    ready: bool
    azure_call_made: bool
    azure_mutation_made: bool
    agent_invoked: bool
    stable_endpoint_present: bool
    stable_endpoint_matches_configuration: bool
    version_selector_present: bool
    configured_version_present: bool
    configured_version_exclusive: bool
    configured_version_traffic_percentage: int | None
    responses_protocol_present: bool
    routing_reused: bool
    routing_updated: bool
    recommended_next_step: str

    @classmethod
    def check_success(cls) -> "FoundryAgentEndpointRoutingResult":
        return cls(
            ok=True,
            mode="check",
            operation=ROUTING_OPERATION,
            category="success",
            message=SUCCESS_MESSAGE,
            ready=True,
            azure_call_made=False,
            azure_mutation_made=False,
            agent_invoked=False,
            stable_endpoint_present=True,
            stable_endpoint_matches_configuration=True,
            version_selector_present=True,
            configured_version_present=True,
            configured_version_exclusive=False,
            configured_version_traffic_percentage=None,
            responses_protocol_present=True,
            routing_reused=False,
            routing_updated=False,
            recommended_next_step=NEXT_STEP,
        )

    @classmethod
    def live_success(
        cls,
        *,
        updated: bool,
    ) -> "FoundryAgentEndpointRoutingResult":
        return cls(
            ok=True,
            mode="live",
            operation=ROUTING_OPERATION,
            category="success",
            message=SUCCESS_MESSAGE,
            ready=True,
            azure_call_made=True,
            azure_mutation_made=updated,
            agent_invoked=False,
            stable_endpoint_present=True,
            stable_endpoint_matches_configuration=True,
            version_selector_present=True,
            configured_version_present=True,
            configured_version_exclusive=True,
            configured_version_traffic_percentage=100,
            responses_protocol_present=True,
            routing_reused=not updated,
            routing_updated=updated,
            recommended_next_step=NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        category: RoutingCategory,
        *,
        mode: Literal["check", "live"],
        azure_call_made: bool = False,
        azure_mutation_made: bool = False,
        stable_endpoint_present: bool = False,
        stable_endpoint_matches_configuration: bool = False,
        version_selector_present: bool = False,
        configured_version_present: bool = False,
        configured_version_traffic_percentage: int | None = None,
        responses_protocol_present: bool = False,
    ) -> "FoundryAgentEndpointRoutingResult":
        return cls(
            ok=False,
            mode=mode,
            operation=ROUTING_OPERATION,
            category=category,
            message=FAILURE_MESSAGE,
            ready=False,
            azure_call_made=azure_call_made,
            azure_mutation_made=azure_mutation_made,
            agent_invoked=False,
            stable_endpoint_present=stable_endpoint_present,
            stable_endpoint_matches_configuration=(
                stable_endpoint_matches_configuration
            ),
            version_selector_present=version_selector_present,
            configured_version_present=configured_version_present,
            configured_version_exclusive=False,
            configured_version_traffic_percentage=(
                configured_version_traffic_percentage
            ),
            responses_protocol_present=responses_protocol_present,
            routing_reused=False,
            routing_updated=False,
            recommended_next_step=NEXT_STEP,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "operation": self.operation,
            "category": self.category,
            "message": self.message,
            "ready": self.ready,
            "azure_call_made": self.azure_call_made,
            "azure_mutation_made": self.azure_mutation_made,
            "agent_invoked": self.agent_invoked,
            "stable_endpoint_present": self.stable_endpoint_present,
            "stable_endpoint_matches_configuration": (
                self.stable_endpoint_matches_configuration
            ),
            "version_selector_present": self.version_selector_present,
            "configured_version_present": self.configured_version_present,
            "configured_version_exclusive": self.configured_version_exclusive,
            "configured_version_traffic_percentage": (
                self.configured_version_traffic_percentage
            ),
            "responses_protocol_present": self.responses_protocol_present,
            "routing_reused": self.routing_reused,
            "routing_updated": self.routing_updated,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class _RoutingSdkContract:
    agent_endpoint_config: Callable[..., Any]
    protocol_configuration: Callable[..., Any]
    responses_protocol_configuration: Callable[..., Any]
    version_selector: Callable[..., Any]
    fixed_ratio_rule: Callable[..., Any]


@dataclass(frozen=True)
class _RoutingState:
    valid: bool
    selector_present: bool
    exclusive: bool
    configured_traffic: int | None


class FoundryAgentEndpointRouting:
    """Configure one existing agent endpoint without provisioning or invocation."""

    def __init__(
        self,
        *,
        sdk_contract_loader: Callable[[], _RoutingSdkContract] = (
            lambda: _load_sdk_contract()
        ),
        credential_factory: Callable[[str | None], object] = (
            lambda client_id: _create_credential(client_id)
        ),
        project_client_factory: Callable[[str, object], object] = (
            lambda endpoint, credential: _create_project_client(endpoint, credential)
        ),
    ) -> None:
        self._sdk_contract_loader = sdk_contract_loader
        self._credential_factory = credential_factory
        self._project_client_factory = project_client_factory

    def check(
        self,
        request: FoundryAgentEndpointRoutingRequest,
    ) -> FoundryAgentEndpointRoutingResult:
        invalid_category = _request_error_category(request)
        if invalid_category is not None:
            return FoundryAgentEndpointRoutingResult.failure(
                invalid_category,
                mode="check",
            )
        try:
            sdk = self._sdk_contract_loader()
            intended = _build_endpoint_configuration(
                sdk,
                request.agent_version,
                preserved_protocols={},
                authorization_schemes=None,
            )
            state = _routing_state(intended, request.agent_version)
            if not state.valid or not state.exclusive or not _responses_enabled(intended):
                raise TypeError("Unsupported SDK routing contract.")
        except (ImportError, ModuleNotFoundError, TypeError, ValueError):
            return FoundryAgentEndpointRoutingResult.failure(
                "sdk_unavailable",
                mode="check",
            )
        except Exception:
            return FoundryAgentEndpointRoutingResult.failure(
                "sdk_unavailable",
                mode="check",
            )
        return FoundryAgentEndpointRoutingResult.check_success()

    def configure(
        self,
        request: FoundryAgentEndpointRoutingRequest,
    ) -> FoundryAgentEndpointRoutingResult:
        invalid_category = _request_error_category(request)
        if invalid_category is not None:
            return FoundryAgentEndpointRoutingResult.failure(
                invalid_category,
                mode="live",
            )
        try:
            sdk = self._sdk_contract_loader()
            _build_endpoint_configuration(
                sdk,
                request.agent_version,
                preserved_protocols={},
                authorization_schemes=None,
            )
        except Exception:
            return FoundryAgentEndpointRoutingResult.failure(
                "sdk_unavailable",
                mode="live",
            )

        credential: object | None = None
        project_client: object | None = None
        azure_call_made = False
        try:
            try:
                credential = self._credential_factory(
                    request.managed_identity_client_id
                )
                project_client = self._project_client_factory(
                    request.project_endpoint,
                    credential,
                )
            except Exception as error:
                return FoundryAgentEndpointRoutingResult.failure(
                    _azure_error_category(error),
                    mode="live",
                )

            agents = getattr(project_client, "agents", None)
            if agents is None or not callable(getattr(agents, "get", None)):
                return FoundryAgentEndpointRoutingResult.failure(
                    "response_parse_failed",
                    mode="live",
                )

            try:
                azure_call_made = True
                remote_agent = agents.get(request.agent_name)
            except Exception as error:
                return FoundryAgentEndpointRoutingResult.failure(
                    _azure_error_category(error),
                    mode="live",
                    azure_call_made=True,
                )

            agent_name = _string_field(remote_agent, "name")
            endpoint = _raw_field(remote_agent, "agent_endpoint")
            endpoint_present = endpoint is not None
            endpoint_matches = bool(
                agent_name == request.agent_name
                and stable_agent_endpoint_matches_configuration(
                    project_endpoint=request.project_endpoint,
                    stable_agent_endpoint=request.stable_agent_endpoint,
                    agent_name=request.agent_name,
                )
            )
            if not endpoint_present:
                return FoundryAgentEndpointRoutingResult.failure(
                    "not_found",
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_matches_configuration=endpoint_matches,
                )
            if not endpoint_matches:
                return FoundryAgentEndpointRoutingResult.failure(
                    "endpoint_mismatch",
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_present=True,
                )

            protocol_status = _preserved_protocols(endpoint)
            if protocol_status is None:
                return FoundryAgentEndpointRoutingResult.failure(
                    "responses_protocol_missing",
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                )
            preserved_protocols, authorization_schemes = protocol_status
            routing = _routing_state(endpoint, request.agent_version)
            if not routing.valid:
                return FoundryAgentEndpointRoutingResult.failure(
                    "version_routing_mismatch",
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                    version_selector_present=routing.selector_present,
                    configured_version_traffic_percentage=(
                        routing.configured_traffic
                    ),
                    responses_protocol_present=True,
                )

            if not callable(getattr(agents, "get_version", None)):
                return FoundryAgentEndpointRoutingResult.failure(
                    "response_parse_failed",
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                    version_selector_present=routing.selector_present,
                    responses_protocol_present=True,
                )
            try:
                remote_version = agents.get_version(
                    request.agent_name,
                    request.agent_version,
                )
            except Exception as error:
                return FoundryAgentEndpointRoutingResult.failure(
                    _azure_error_category(error),
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                    version_selector_present=routing.selector_present,
                    responses_protocol_present=True,
                )
            version_present = bool(
                _string_field(remote_version, "name") == request.agent_name
                and _string_field(remote_version, "version")
                == request.agent_version
            )
            if not version_present:
                return FoundryAgentEndpointRoutingResult.failure(
                    "version_routing_mismatch",
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                    version_selector_present=routing.selector_present,
                    responses_protocol_present=True,
                )

            if routing.exclusive:
                return FoundryAgentEndpointRoutingResult.live_success(
                    updated=False
                )

            update = _build_endpoint_configuration(
                sdk,
                request.agent_version,
                preserved_protocols=preserved_protocols,
                authorization_schemes=authorization_schemes,
            )
            if not callable(getattr(agents, "update_details", None)):
                return FoundryAgentEndpointRoutingResult.failure(
                    "sdk_unavailable",
                    mode="live",
                    azure_call_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                    version_selector_present=routing.selector_present,
                    configured_version_present=True,
                    configured_version_traffic_percentage=(
                        routing.configured_traffic
                    ),
                    responses_protocol_present=True,
                )
            try:
                updated_agent = agents.update_details(
                    request.agent_name,
                    agent_endpoint=update,
                )
            except Exception as error:
                return FoundryAgentEndpointRoutingResult.failure(
                    _azure_error_category(error),
                    mode="live",
                    azure_call_made=True,
                    azure_mutation_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                    version_selector_present=routing.selector_present,
                    configured_version_present=True,
                    configured_version_traffic_percentage=(
                        routing.configured_traffic
                    ),
                    responses_protocol_present=True,
                )

            updated_endpoint = _raw_field(updated_agent, "agent_endpoint")
            updated_routing = _routing_state(
                updated_endpoint,
                request.agent_version,
            )
            update_accepted = bool(
                _string_field(updated_agent, "name") == request.agent_name
                and updated_endpoint is not None
                and _responses_enabled(updated_endpoint)
                and updated_routing.valid
                and updated_routing.exclusive
            )
            if not update_accepted:
                return FoundryAgentEndpointRoutingResult.failure(
                    "response_parse_failed",
                    mode="live",
                    azure_call_made=True,
                    azure_mutation_made=True,
                    stable_endpoint_present=True,
                    stable_endpoint_matches_configuration=True,
                    version_selector_present=updated_routing.selector_present,
                    configured_version_present=True,
                    configured_version_traffic_percentage=(
                        updated_routing.configured_traffic
                    ),
                    responses_protocol_present=_responses_enabled(
                        updated_endpoint
                    ),
                )
            return FoundryAgentEndpointRoutingResult.live_success(updated=True)
        except Exception:
            return FoundryAgentEndpointRoutingResult.failure(
                "unexpected_error",
                mode="live",
                azure_call_made=azure_call_made,
            )
        finally:
            _close_safely(project_client)
            _close_safely(credential)


def _load_sdk_contract() -> _RoutingSdkContract:
    from azure.ai.projects.models import (
        AgentEndpointConfig,
        FixedRatioVersionSelectionRule,
        ProtocolConfiguration,
        ResponsesProtocolConfiguration,
        VersionSelector,
    )

    return _RoutingSdkContract(
        agent_endpoint_config=AgentEndpointConfig,
        protocol_configuration=ProtocolConfiguration,
        responses_protocol_configuration=ResponsesProtocolConfiguration,
        version_selector=VersionSelector,
        fixed_ratio_rule=FixedRatioVersionSelectionRule,
    )


def _create_credential(managed_identity_client_id: str | None) -> object:
    return FoundryCredentialFactory().create(
        FoundryCredentialConfiguration(managed_identity_client_id)
    )


def _create_project_client(project_endpoint: str, credential: object) -> object:
    from azure.ai.projects import AIProjectClient

    return AIProjectClient(endpoint=project_endpoint, credential=credential)


def _request_error_category(
    request: FoundryAgentEndpointRoutingRequest,
) -> RoutingCategory | None:
    values = (
        request.project_endpoint,
        request.stable_agent_endpoint,
        request.agent_name,
        request.agent_version,
    )
    if not all(
        isinstance(value, str) and bool(value) and value == value.strip()
        for value in values
    ):
        return "missing_configuration"
    if _AGENT_NAME_PATTERN.fullmatch(request.agent_name) is None:
        return "endpoint_mismatch"
    if not is_valid_stable_agent_endpoint(request.stable_agent_endpoint):
        return "endpoint_mismatch"
    if not stable_agent_endpoint_matches_configuration(
        project_endpoint=request.project_endpoint,
        stable_agent_endpoint=request.stable_agent_endpoint,
        agent_name=request.agent_name,
    ):
        return "endpoint_mismatch"
    return None


def _build_endpoint_configuration(
    sdk: _RoutingSdkContract,
    agent_version: str,
    *,
    preserved_protocols: dict[str, object],
    authorization_schemes: list[object] | None,
) -> object:
    protocol_values = {
        name: value
        for name, value in preserved_protocols.items()
        if name in _PROTOCOL_FIELDS and name != "responses" and value is not None
    }
    protocol_values["responses"] = sdk.responses_protocol_configuration()
    protocol_configuration = sdk.protocol_configuration(**protocol_values)
    rule = sdk.fixed_ratio_rule(
        agent_version=agent_version,
        traffic_percentage=100,
    )
    selector = sdk.version_selector(version_selection_rules=[rule])
    endpoint = sdk.agent_endpoint_config(
        version_selector=selector,
        protocol_configuration=protocol_configuration,
        authorization_schemes=authorization_schemes,
    )
    if not isinstance(endpoint, Mapping):
        raise TypeError("Unsupported endpoint model.")
    return endpoint


def _preserved_protocols(
    endpoint: object,
) -> tuple[dict[str, object], list[object] | None] | None:
    configuration = _raw_field(endpoint, "protocol_configuration")
    if not isinstance(configuration, Mapping):
        return None
    if any(name not in _PROTOCOL_FIELDS for name in configuration):
        return None
    values: dict[str, object] = {}
    for name in _PROTOCOL_FIELDS:
        value = _field(configuration, name)
        if value is _MISSING or value is None:
            continue
        if not isinstance(value, Mapping):
            return None
        values[name] = value
    if "responses" not in values:
        return None

    authorization = _field(endpoint, "authorization_schemes")
    if authorization is _MISSING or authorization is None:
        authorization_values = None
    elif isinstance(authorization, (list, tuple)) and all(
        isinstance(item, Mapping) for item in authorization
    ):
        authorization_values = list(authorization)
    else:
        return None
    return values, authorization_values


def _responses_enabled(endpoint: object) -> bool:
    preserved = _preserved_protocols(endpoint)
    return preserved is not None


def _routing_state(endpoint: object, configured_version: str) -> _RoutingState:
    selector = _raw_field(endpoint, "version_selector")
    if selector is None:
        return _RoutingState(True, False, False, None)
    if not isinstance(selector, Mapping):
        return _RoutingState(False, True, False, None)
    rules = _field(selector, "version_selection_rules")
    if not isinstance(rules, (list, tuple)):
        return _RoutingState(False, True, False, None)
    if not rules:
        return _RoutingState(True, True, False, None)

    seen_versions: set[str] = set()
    total_traffic = 0
    configured_traffic: int | None = None
    for rule in rules:
        rule_type = _raw_field(rule, "type")
        version = _raw_field(rule, "agent_version")
        traffic = _raw_field(rule, "traffic_percentage")
        if (
            rule_type != "FixedRatio"
            or not isinstance(version, str)
            or not version
            or version != version.strip()
            or version in seen_versions
            or isinstance(traffic, bool)
            or not isinstance(traffic, int)
            or not 0 <= traffic <= 100
        ):
            return _RoutingState(False, True, False, configured_traffic)
        seen_versions.add(version)
        total_traffic += traffic
        if version == configured_version:
            configured_traffic = traffic
    if total_traffic != 100:
        return _RoutingState(False, True, False, configured_traffic)
    validation = validate_exclusive_immutable_version_routing(
        rules,
        configured_version,
    )
    return _RoutingState(
        True,
        True,
        validation.valid,
        configured_traffic,
    )


def _field(value: object, name: str) -> object:
    if isinstance(value, Mapping):
        return value[name] if name in value else _MISSING
    return getattr(value, name, _MISSING)


def _raw_field(value: object, name: str) -> object | None:
    field = _field(value, name)
    return None if field is _MISSING else field


def _string_field(value: object, name: str) -> str:
    field = _raw_field(value, name)
    return field.strip() if isinstance(field, str) else ""


def _azure_error_category(error: BaseException) -> RoutingCategory:
    for current in _exception_chain(error):
        if isinstance(current, (ImportError, ModuleNotFoundError)):
            return "sdk_unavailable"
        status = _status_code(current)
        if status == 404:
            return "not_found"
        if status in {401, 403}:
            return "authentication_or_authorization_failed"
        name = type(current).__name__.lower()
        if "authentication" in name or "credential" in name or "forbidden" in name:
            return "authentication_or_authorization_failed"
    return "azure_request_failed"


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


def _close_safely(resource: object | None) -> None:
    if resource is None:
        return
    try:
        close = getattr(resource, "close", None)
        if callable(close):
            close()
    except Exception:
        pass
