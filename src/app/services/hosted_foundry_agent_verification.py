from collections.abc import Callable
from dataclasses import dataclass
from importlib.util import find_spec
import os
from typing import Any, Literal

from src.app.services.foundry_agent_client import (
    is_valid_stable_agent_endpoint,
    stable_agent_endpoint_matches_configuration,
)
from src.app.services.foundry_agent_verification import (
    FoundryAgentVerification,
    FoundryAgentVerificationRequest,
    FoundryAgentVerificationResult,
)
from src.app.services.nurse_intake_agent_instructions import (
    build_nurse_intake_agent_instructions,
)


HostedVerificationMode = Literal["check", "live"]
HostedVerificationCategory = Literal[
    "success",
    "missing_configuration",
    "sdk_unavailable",
    "not_running_in_hosted_environment",
    "managed_identity_unavailable",
    "authentication_or_authorization_failed",
    "project_access_failed",
    "agent_not_found",
    "configured_version_not_found",
    "agent_contract_invalid",
    "azure_request_failed",
    "response_parse_failed",
    "unexpected_error",
]

HOSTED_ENVIRONMENT_MARKERS = (
    "WEBSITE_INSTANCE_ID",
    "IDENTITY_ENDPOINT",
    "IDENTITY_HEADER",
)
OPERATION = "verify_hosted_foundry_agent"
CHECK_NEXT_STEP = (
    "After deployment and RBAC proof, run explicit --live --json inside the Web App."
)
LIVE_NEXT_STEP = "Run the separate fictional-data hosted agent invocation."
FAILURE_NEXT_STEP = "Review the sanitized category before retrying verification."


@dataclass(frozen=True)
class HostedFoundryAgentVerificationRequest:
    mode: str
    project_endpoint: str | None
    stable_agent_endpoint: str | None
    agent_name: str | None
    agent_version: str | None
    model_deployment_name: str | None
    instructions: str


@dataclass(frozen=True)
class HostedFoundryAgentVerificationResult:
    ok: bool
    category: HostedVerificationCategory
    operation: str
    mode: str
    local_contract_validated: bool
    hosted_environment_present: bool
    managed_identity_attempted: bool
    managed_identity_authenticated: bool
    project_access_verified: bool
    agent_present: bool
    configured_version_present: bool
    agent_contract_verified: bool
    agent_invocation_attempted: bool
    azure_mutation_made: bool
    recommended_next_step: str

    @classmethod
    def success(
        cls,
        mode: HostedVerificationMode,
    ) -> "HostedFoundryAgentVerificationResult":
        live = mode == "live"
        return cls(
            ok=True,
            category="success",
            operation=OPERATION,
            mode=mode,
            local_contract_validated=True,
            hosted_environment_present=live,
            managed_identity_attempted=live,
            managed_identity_authenticated=live,
            project_access_verified=live,
            agent_present=live,
            configured_version_present=live,
            agent_contract_verified=live,
            agent_invocation_attempted=False,
            azure_mutation_made=False,
            recommended_next_step=LIVE_NEXT_STEP if live else CHECK_NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        mode: str,
        category: HostedVerificationCategory,
        *,
        local_contract_validated: bool = False,
        hosted_environment_present: bool = False,
        managed_identity_attempted: bool = False,
        managed_identity_authenticated: bool = False,
        project_access_verified: bool = False,
        agent_present: bool = False,
        configured_version_present: bool = False,
    ) -> "HostedFoundryAgentVerificationResult":
        return cls(
            ok=False,
            category=category,
            operation=OPERATION,
            mode=mode if mode in {"check", "live"} else "invalid",
            local_contract_validated=local_contract_validated,
            hosted_environment_present=hosted_environment_present,
            managed_identity_attempted=managed_identity_attempted,
            managed_identity_authenticated=managed_identity_authenticated,
            project_access_verified=project_access_verified,
            agent_present=agent_present,
            configured_version_present=configured_version_present,
            agent_contract_verified=False,
            agent_invocation_attempted=False,
            azure_mutation_made=False,
            recommended_next_step=FAILURE_NEXT_STEP,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "local_contract_validated": self.local_contract_validated,
            "hosted_environment_present": self.hosted_environment_present,
            "managed_identity_attempted": self.managed_identity_attempted,
            "managed_identity_authenticated": self.managed_identity_authenticated,
            "project_access_verified": self.project_access_verified,
            "agent_present": self.agent_present,
            "configured_version_present": self.configured_version_present,
            "agent_contract_verified": self.agent_contract_verified,
            "agent_invocation_attempted": self.agent_invocation_attempted,
            "azure_mutation_made": self.azure_mutation_made,
            "recommended_next_step": self.recommended_next_step,
        }


def build_hosted_foundry_agent_verification_request(
    settings: Any,
    *,
    mode: str,
) -> HostedFoundryAgentVerificationRequest:
    return HostedFoundryAgentVerificationRequest(
        mode=mode,
        project_endpoint=getattr(
            settings, "azure_ai_foundry_agent_project_endpoint", None
        ),
        stable_agent_endpoint=getattr(
            settings, "azure_ai_foundry_agent_endpoint", None
        ),
        agent_name=getattr(settings, "azure_ai_foundry_agent_name", None),
        agent_version=getattr(settings, "azure_ai_foundry_agent_version", None),
        model_deployment_name=getattr(
            settings, "azure_ai_foundry_model_deployment_name", None
        ),
        instructions=build_nurse_intake_agent_instructions(),
    )


def hosted_verification_sdk_available() -> bool:
    try:
        return (
            find_spec("azure.ai.projects") is not None
            and find_spec("azure.identity") is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def create_system_assigned_managed_identity_credential() -> object:
    """Create only the platform system-assigned managed-identity credential."""

    credential_class = _get_managed_identity_credential_class()
    return credential_class()


def _get_managed_identity_credential_class():
    from azure.identity import ManagedIdentityCredential

    return ManagedIdentityCredential


def _create_project_client(project_endpoint: str, credential: object) -> object:
    from azure.ai.projects import AIProjectClient

    return AIProjectClient(endpoint=project_endpoint, credential=credential)


class HostedFoundryAgentVerification:
    """Verify hosted system-identity access without inference or mutation."""

    def __init__(
        self,
        *,
        credential_factory: Callable[[], object] = (
            create_system_assigned_managed_identity_credential
        ),
        project_client_factory: Callable[[str, object], object] = (
            _create_project_client
        ),
        environment_reader: Callable[[str], object] = os.getenv,
        sdk_available: Callable[[], bool] = hosted_verification_sdk_available,
    ) -> None:
        self._credential_factory = credential_factory
        self._project_client_factory = project_client_factory
        self._environment_reader = environment_reader
        self._sdk_available = sdk_available

    def check(
        self,
        request: HostedFoundryAgentVerificationRequest,
    ) -> HostedFoundryAgentVerificationResult:
        if not _request_contract_valid(request, expected_mode="check"):
            return HostedFoundryAgentVerificationResult.failure(
                request.mode, "missing_configuration"
            )
        if not self._sdk_available():
            return HostedFoundryAgentVerificationResult.failure(
                request.mode,
                "sdk_unavailable",
                local_contract_validated=True,
            )
        return HostedFoundryAgentVerificationResult.success("check")

    def verify(
        self,
        request: HostedFoundryAgentVerificationRequest,
    ) -> HostedFoundryAgentVerificationResult:
        if not _request_contract_valid(request, expected_mode="live"):
            return HostedFoundryAgentVerificationResult.failure(
                request.mode, "missing_configuration"
            )
        if not self._sdk_available():
            return HostedFoundryAgentVerificationResult.failure(
                request.mode,
                "sdk_unavailable",
                local_contract_validated=True,
            )
        if not all(_present(self._environment_reader(name)) for name in HOSTED_ENVIRONMENT_MARKERS):
            return HostedFoundryAgentVerificationResult.failure(
                request.mode,
                "not_running_in_hosted_environment",
                local_contract_validated=True,
            )

        progress: dict[str, bool] = {
            "local_contract_validated": True,
            "hosted_environment_present": True,
            "managed_identity_attempted": True,
            "managed_identity_authenticated": False,
            "project_access_verified": False,
            "agent_present": False,
            "configured_version_present": False,
        }
        try:
            credential = self._credential_factory()
        except Exception as error:
            return HostedFoundryAgentVerificationResult.failure(
                request.mode,
                _credential_failure_category(error),
                **progress,
            )
        project_client: object | None = None
        try:
            try:
                project_client = self._project_client_factory(
                    request.project_endpoint,
                    credential,
                )
                tracker = _ReadOnlyLookupTracker(project_client)
            except (ImportError, ModuleNotFoundError):
                return HostedFoundryAgentVerificationResult.failure(
                    request.mode, "sdk_unavailable", **progress
                )
            except HostedResponseShapeError:
                return HostedFoundryAgentVerificationResult.failure(
                    request.mode, "response_parse_failed", **progress
                )
            except Exception:
                return HostedFoundryAgentVerificationResult.failure(
                    request.mode, "azure_request_failed", **progress
                )

            try:
                shared_request = FoundryAgentVerificationRequest(
                    project_endpoint=request.project_endpoint,
                    stable_agent_endpoint=request.stable_agent_endpoint,
                    agent_name=request.agent_name,
                    agent_version=request.agent_version,
                    model_deployment_name=request.model_deployment_name,
                    instructions=request.instructions,
                )
                shared_result = FoundryAgentVerification(
                    project_client_factory=lambda _endpoint: tracker.project_client
                ).verify(shared_request)
                progress.update(
                    managed_identity_authenticated=tracker.authenticated,
                    project_access_verified=tracker.project_access_verified,
                    agent_present=tracker.agent_present,
                    configured_version_present=tracker.version_present,
                )
                category = _hosted_category(shared_result, tracker)
                if category == "success":
                    return HostedFoundryAgentVerificationResult.success("live")
                return HostedFoundryAgentVerificationResult.failure(
                    request.mode,
                    category,
                    **progress,
                )
            except Exception:
                return HostedFoundryAgentVerificationResult.failure(
                    request.mode,
                    "unexpected_error",
                    **progress,
                )
        finally:
            _close_safely(project_client)
            _close_safely(credential)


class HostedResponseShapeError(Exception):
    pass


def _close_safely(resource: object | None) -> None:
    if resource is None:
        return
    try:
        close = getattr(resource, "close", None)
        if callable(close):
            close()
    except Exception:
        pass


class _ReadOnlyAgentsAdapter:
    def __init__(self, source: object, tracker: "_ReadOnlyLookupTracker") -> None:
        if not callable(getattr(source, "get", None)) or not callable(
            getattr(source, "get_version", None)
        ):
            raise HostedResponseShapeError()
        self._source = source
        self._tracker = tracker

    def get(self, agent_name: str) -> object:
        self._tracker.stage = "agent"
        try:
            response = self._source.get(agent_name)
        except Exception as error:
            self._tracker.error = error
            if _status_code(error) == 404:
                self._tracker.authenticated = True
                self._tracker.project_access_verified = True
            raise
        self._tracker.authenticated = True
        self._tracker.project_access_verified = True
        if not _agent_response_shape_valid(response):
            self._tracker.parse_failed = True
            raise HostedResponseShapeError()
        self._tracker.agent_present = True
        return response

    def get_version(self, agent_name: str, agent_version: str) -> object:
        self._tracker.stage = "version"
        try:
            response = self._source.get_version(agent_name, agent_version)
        except Exception as error:
            self._tracker.error = error
            raise
        if not _version_response_shape_valid(response):
            self._tracker.parse_failed = True
            raise HostedResponseShapeError()
        self._tracker.version_present = True
        return response


class _ReadOnlyProjectClientAdapter:
    def __init__(self, agents: _ReadOnlyAgentsAdapter) -> None:
        self.agents = agents


class _ReadOnlyLookupTracker:
    def __init__(self, project_client: object) -> None:
        source_agents = getattr(project_client, "agents", None)
        if source_agents is None:
            raise HostedResponseShapeError()
        self.stage: str | None = None
        self.error: BaseException | None = None
        self.parse_failed = False
        self.authenticated = False
        self.project_access_verified = False
        self.agent_present = False
        self.version_present = False
        self.project_client = _ReadOnlyProjectClientAdapter(
            _ReadOnlyAgentsAdapter(source_agents, self)
        )


def _request_contract_valid(
    request: HostedFoundryAgentVerificationRequest,
    *,
    expected_mode: HostedVerificationMode,
) -> bool:
    if request.mode != expected_mode:
        return False
    values = (
        request.project_endpoint,
        request.stable_agent_endpoint,
        request.agent_name,
        request.agent_version,
        request.model_deployment_name,
        request.instructions,
    )
    if not all(_present(value) and value == value.strip() for value in values):
        return False
    if request.instructions != build_nurse_intake_agent_instructions():
        return False
    return bool(
        is_valid_stable_agent_endpoint(request.stable_agent_endpoint)
        and stable_agent_endpoint_matches_configuration(
            project_endpoint=request.project_endpoint,
            stable_agent_endpoint=request.stable_agent_endpoint,
            agent_name=request.agent_name,
        )
    )


def _present(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _raw_value(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _agent_response_shape_valid(response: object) -> bool:
    identity = _raw_value(response, "instance_identity")
    endpoint = _raw_value(response, "agent_endpoint")
    selector = _raw_value(endpoint, "version_selector")
    protocols = _raw_value(endpoint, "protocols")
    rules = _raw_value(selector, "version_selection_rules")
    if not (
        _present(_raw_value(response, "id"))
        and _present(_raw_value(identity, "client_id"))
        and isinstance(protocols, (list, tuple))
        and bool(protocols)
        and all(_present(protocol) for protocol in protocols)
        and isinstance(rules, (list, tuple))
        and bool(rules)
    ):
        return False
    return all(
        _present(_raw_value(rule, "type"))
        and _present(_raw_value(rule, "agent_version"))
        and isinstance(_raw_value(rule, "traffic_percentage"), int)
        and not isinstance(_raw_value(rule, "traffic_percentage"), bool)
        for rule in rules
    )


def _version_response_shape_valid(response: object) -> bool:
    definition = _raw_value(response, "definition")
    return bool(
        _present(_raw_value(response, "name"))
        and _present(_raw_value(response, "version"))
        and _present(_raw_value(definition, "model"))
        and _present(_raw_value(definition, "instructions"))
    )


def _hosted_category(
    result: FoundryAgentVerificationResult,
    tracker: _ReadOnlyLookupTracker,
) -> HostedVerificationCategory:
    if tracker.parse_failed:
        return "response_parse_failed"
    if result.ok:
        return "success"
    if tracker.error is not None:
        status = _status_code(tracker.error)
        if status in {401, 403}:
            return "authentication_or_authorization_failed"
        if tracker.stage == "agent":
            return "agent_not_found" if status == 404 else "project_access_failed"
        if tracker.stage == "version":
            return (
                "configured_version_not_found"
                if status == 404
                else "azure_request_failed"
            )
    if result.category == "authentication_or_authorization_failed":
        return "authentication_or_authorization_failed"
    if result.category == "sdk_unavailable":
        return "sdk_unavailable"
    if result.category in {
        "definition_mismatch",
        "response_contract_invalid",
        "legacy_agent_model",
        "stable_endpoint_missing",
        "stable_endpoint_invalid",
        "stable_endpoint_mismatch",
        "version_routing_mismatch",
    }:
        return "agent_contract_invalid"
    return "azure_request_failed"


def _credential_failure_category(error: BaseException) -> HostedVerificationCategory:
    for current in _exception_chain(error):
        if isinstance(current, (ImportError, ModuleNotFoundError)):
            return "sdk_unavailable"
        status = _status_code(current)
        if status in {401, 403}:
            return "authentication_or_authorization_failed"
        name = type(current).__name__.casefold()
        if "credentialunavailable" in name or "managedidentity" in name:
            return "managed_identity_unavailable"
        if "authentication" in name or "forbidden" in name:
            return "authentication_or_authorization_failed"
    return "managed_identity_unavailable"


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
