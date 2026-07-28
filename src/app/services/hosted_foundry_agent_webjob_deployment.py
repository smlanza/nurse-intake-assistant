from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from src.app.services.daily_azure_environment_rebuild import (
    DailyAzureReadinessReceipt,
    REBUILD_OPERATION,
)
from src.app.services.hosted_foundry_agent_webjob_execution import (
    AzureCliRunner,
    WEBJOB_NAME,
    environment_generation_fingerprint,
)
from src.app.services.hosted_foundry_agent_webjob_handoff import (
    GENERATION_HANDOFF_SCHEMA_VERSION,
    HostedFoundryAgentWebJobGenerationHandoff,
)
from src.app.services.hosted_foundry_agent_webjob_package import (
    HostedFoundryAgentWebJobPackage,
    HostedWebJobPackageAuthorizationSession,
    HostedWebJobPackageError,
    WEBJOB_PACKAGE_FILENAME,
    build_hosted_foundry_agent_webjob_package,
    consume_hosted_webjob_package_authorization,
    create_hosted_webjob_package_authorization_session,
    plan_hosted_foundry_agent_webjob_package,
)
from src.app.services.hosted_foundry_agent_webjob_kudu import (
    KuduWebJobDiscoverer,
    KuduWebJobDiscoveryResult,
    acquire_kudu_bearer_token,
    kudu_triggered_webjob_url,
)


DeploymentMode = Literal["check", "live"]
DeploymentCategory = Literal[
    "check_complete",
    "success",
    "invalid_request",
    "readiness_receipt_invalid",
    "generation_handoff_invalid",
    "local_package_invalid",
    "generation_invalid",
    "generation_changed",
    "approval_required",
    "package_changed",
    "authentication_or_authorization_failed",
    "upload_request_invalid",
    "upload_throttled",
    "upload_service_failed",
    "upload_failed",
    "upload_acceptance_ambiguous",
    "remote_webjob_missing",
    "remote_webjob_ambiguous",
    "discovery_throttled",
    "discovery_service_failed",
    "discovery_ambiguous",
    "discovery_response_invalid",
    "discovery_failed",
    "unexpected_error",
]


@dataclass(frozen=True)
class HostedFoundryAgentWebJobDeploymentRequest:
    mode: str
    source_root: Path
    resource_group: str
    web_app_name: str
    webjob_name: str


@dataclass(frozen=True)
class WebJobDeploymentApprovalSummary:
    heading: str = "HOSTED FOUNDRY AGENT WEBJOB DEPLOYMENT"
    facts: tuple[tuple[str, str], ...] = (
        ("Fixed triggered WebJob package valid", "yes"),
        ("Current environment generation validated", "yes"),
        ("Upload replaces only the fixed WebJob contents", "yes"),
        ("Trigger requested", "no"),
    )


@dataclass(frozen=True)
class HostedFoundryAgentWebJobDeploymentResult:
    ok: bool
    category: DeploymentCategory
    operation: str
    mode: str
    local_webjob_package_valid: bool
    readiness_receipt_validated: bool
    generation_handoff_validated: bool
    generation_validated: bool
    operator_approval_obtained: bool
    upload_attempted: bool
    upload_accepted: bool
    remote_discovery_attempted: bool
    remote_webjob_discovered: bool
    trigger_attempted: bool
    trigger_accepted: bool
    correlated_execution_observed: bool
    metadata_verification_proven: bool
    fictional_invocation_proven: bool
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


def _result(
    request: HostedFoundryAgentWebJobDeploymentRequest,
    category: DeploymentCategory,
    *,
    ok: bool = False,
    local_webjob_package_valid: bool = False,
    readiness_receipt_validated: bool = False,
    generation_handoff_validated: bool = False,
    generation_validated: bool = False,
    operator_approval_obtained: bool = False,
    upload_attempted: bool = False,
    upload_accepted: bool = False,
    remote_discovery_attempted: bool = False,
    remote_webjob_discovered: bool = False,
) -> HostedFoundryAgentWebJobDeploymentResult:
    return HostedFoundryAgentWebJobDeploymentResult(
        ok=ok,
        category=category,
        operation="deploy_hosted_foundry_agent_webjob",
        mode=request.mode if request.mode in {"check", "live"} else "invalid",
        local_webjob_package_valid=local_webjob_package_valid,
        readiness_receipt_validated=readiness_receipt_validated,
        generation_handoff_validated=generation_handoff_validated,
        generation_validated=generation_validated,
        operator_approval_obtained=operator_approval_obtained,
        upload_attempted=upload_attempted,
        upload_accepted=upload_accepted,
        remote_discovery_attempted=remote_discovery_attempted,
        remote_webjob_discovered=remote_webjob_discovered,
        trigger_attempted=False,
        trigger_accepted=False,
        correlated_execution_observed=False,
        metadata_verification_proven=False,
        fictional_invocation_proven=False,
        recommended_next_step=(
            (
                "Stop after reviewing the offline package contract."
                if request.mode == "check"
                else "Stop after reviewing successful remote WebJob discovery."
            )
            if ok
            else (
                "Stop and review the sanitized category without triggering "
                "the WebJob."
            )
        ),
    )


@dataclass(frozen=True)
class KuduWebJobUploadResult:
    category: Literal[
        "accepted",
        "authentication_or_authorization_failed",
        "upload_request_invalid",
        "upload_throttled",
        "upload_service_failed",
        "upload_failed",
        "upload_acceptance_ambiguous",
    ]
    upload_attempted: bool
    upload_accepted: bool

    @classmethod
    def accepted(cls) -> "KuduWebJobUploadResult":
        return cls("accepted", True, True)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "upload_attempted": self.upload_attempted,
            "upload_accepted": self.upload_accepted,
        }


class KuduWebJobUploader(Protocol):
    def upload(
        self,
        web_app_name: str,
        webjob_name: str,
        package: bytes,
    ) -> KuduWebJobUploadResult: ...


class KuduTriggeredWebJobUploader:
    _CONTENT_DISPOSITION = (
        f'attachment; filename="{WEBJOB_PACKAGE_FILENAME}"'
    )
    _REQUEST_INVALID_STATUSES = frozenset(
        {400, 404, 405, 409, 413, 415, 422}
    )

    @classmethod
    def _http_rejection_category(cls, status: object) -> str:
        if status in {401, 403}:
            return "authentication_or_authorization_failed"
        if status in cls._REQUEST_INVALID_STATUSES:
            return "upload_request_invalid"
        if status == 429:
            return "upload_throttled"
        if isinstance(status, int) and 500 <= status <= 599:
            return "upload_service_failed"
        return "upload_failed"

    def __init__(
        self,
        *,
        token_runner: AzureCliRunner,
        opener=None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._token_runner = token_runner
        self._opener = opener or build_opener()
        self._timeout_seconds = timeout_seconds

    def _token(self) -> str | None:
        return acquire_kudu_bearer_token(self._token_runner)

    def upload(
        self,
        web_app_name: str,
        webjob_name: str,
        package: bytes,
    ) -> KuduWebJobUploadResult:
        token = self._token()
        if token is None:
            return KuduWebJobUploadResult(
                "authentication_or_authorization_failed",
                False,
                False,
            )
        url = kudu_triggered_webjob_url(web_app_name, webjob_name)
        if url is None:
            return KuduWebJobUploadResult(
                "upload_request_invalid",
                False,
                False,
            )
        request = Request(
            url,
            data=package,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/zip",
                "Content-Disposition": self._CONTENT_DISPOSITION,
            },
            method="PUT",
        )
        try:
            with self._opener.open(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = getattr(response, "status", None)
        except HTTPError as error:
            return KuduWebJobUploadResult(
                self._http_rejection_category(error.code),
                True,
                False,
            )
        except (URLError, TimeoutError, OSError):
            return KuduWebJobUploadResult(
                "upload_acceptance_ambiguous",
                True,
                False,
            )
        except Exception:
            return KuduWebJobUploadResult(
                "upload_acceptance_ambiguous",
                True,
                False,
            )
        if status in {200, 201, 202, 204}:
            return KuduWebJobUploadResult.accepted()
        if not isinstance(status, int):
            return KuduWebJobUploadResult(
                "upload_acceptance_ambiguous",
                True,
                False,
            )
        return KuduWebJobUploadResult(
            self._http_rejection_category(status),
            True,
            False,
        )


def _safe_name(value: object, *, maximum: int) -> bool:
    return bool(
        isinstance(value, str)
        and 1 <= len(value) <= maximum
        and value == value.strip()
        and re.fullmatch(r"[A-Za-z0-9_.()\-]+", value)
    )


def _valid_fingerprint(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _valid_request(
    request: HostedFoundryAgentWebJobDeploymentRequest,
) -> bool:
    return bool(
        request.mode in {"check", "live"}
        and request.source_root.is_absolute()
        and _safe_name(request.resource_group, maximum=90)
        and _safe_name(request.web_app_name, maximum=60)
        and request.webjob_name == WEBJOB_NAME
    )


def _receipt_valid(
    receipt: object,
    request: HostedFoundryAgentWebJobDeploymentRequest,
) -> bool:
    return bool(
        type(receipt) is DailyAzureReadinessReceipt
        and receipt.operation == REBUILD_OPERATION
        and receipt.ready is True
        and receipt.resource_group == request.resource_group
        and receipt.web_app_name == request.web_app_name
        and _valid_fingerprint(receipt.configuration_fingerprint)
        and _valid_fingerprint(receipt.correlation_fingerprint)
        and isinstance(receipt.run_epoch, str)
        and bool(receipt.run_epoch)
    )


def _handoff_valid(
    handoff: object,
    receipt: DailyAzureReadinessReceipt,
    request: HostedFoundryAgentWebJobDeploymentRequest,
) -> bool:
    return bool(
        type(handoff) is HostedFoundryAgentWebJobGenerationHandoff
        and handoff.schema_version == GENERATION_HANDOFF_SCHEMA_VERSION
        and handoff.state == "prepared"
        and handoff.readiness_configuration_fingerprint
        == receipt.configuration_fingerprint
        and handoff.readiness_run_epoch == receipt.run_epoch
        and handoff.readiness_correlation_fingerprint
        == receipt.correlation_fingerprint
        and handoff.resource_group
        == receipt.resource_group
        == request.resource_group
        and handoff.web_app_name
        == receipt.web_app_name
        == request.web_app_name
        and _valid_fingerprint(handoff.environment_fingerprint)
    )


def _generation(
    evidence_reader: Callable[[], object] | None,
) -> str | None:
    if evidence_reader is None:
        return None
    try:
        return environment_generation_fingerprint(evidence_reader())
    except Exception:
        return None


def _approval_binding(
    request: HostedFoundryAgentWebJobDeploymentRequest,
    receipt: DailyAzureReadinessReceipt,
    handoff: HostedFoundryAgentWebJobGenerationHandoff,
    package: HostedFoundryAgentWebJobPackage,
) -> str:
    values = (
        request.resource_group,
        request.web_app_name,
        request.webjob_name,
        receipt.configuration_fingerprint,
        receipt.run_epoch,
        receipt.correlation_fingerprint,
        handoff.environment_fingerprint,
        package.sha256,
    )
    return hashlib.sha256(
        json.dumps(values, separators=(",", ":")).encode()
    ).hexdigest()


def deploy_hosted_foundry_agent_webjob(
    request: HostedFoundryAgentWebJobDeploymentRequest,
    *,
    readiness_receipt: DailyAzureReadinessReceipt | None,
    generation_handoff: HostedFoundryAgentWebJobGenerationHandoff | None,
    evidence_reader: Callable[[], object] | None = None,
    current_binding_reader: Callable[
        [],
        tuple[
            DailyAzureReadinessReceipt | None,
            HostedFoundryAgentWebJobGenerationHandoff | None,
        ],
    ]
    | None = None,
    approver: Callable[[WebJobDeploymentApprovalSummary], bool] | None = None,
    uploader_factory: Callable[[], KuduWebJobUploader] | None = None,
    discovery_factory: Callable[[], KuduWebJobDiscoverer] | None = None,
    package_builder: Callable[..., HostedFoundryAgentWebJobPackage] = (
        build_hosted_foundry_agent_webjob_package
    ),
) -> HostedFoundryAgentWebJobDeploymentResult:
    if not _valid_request(request):
        return _result(request, "invalid_request")
    if request.mode == "check":
        try:
            plan = plan_hosted_foundry_agent_webjob_package(
                request.source_root
            )
            package_valid = plan.member_names == ("run.py",)
        except HostedWebJobPackageError:
            package_valid = False
        return _result(
            request,
            "check_complete" if package_valid else "local_package_invalid",
            ok=package_valid,
            local_webjob_package_valid=package_valid,
        )
    if not _receipt_valid(readiness_receipt, request):
        return _result(request, "readiness_receipt_invalid")
    assert readiness_receipt is not None
    if not _handoff_valid(generation_handoff, readiness_receipt, request):
        return _result(
            request,
            "generation_handoff_invalid",
            readiness_receipt_validated=True,
        )
    assert generation_handoff is not None
    if current_binding_reader is None:
        return _result(
            request,
            "generation_handoff_invalid",
            readiness_receipt_validated=True,
            generation_handoff_validated=True,
        )
    session = create_hosted_webjob_package_authorization_session()
    try:
        package = package_builder(
            request.source_root,
            authorization_session=session,
        )
    except Exception:
        return _result(
            request,
            "local_package_invalid",
            readiness_receipt_validated=True,
            generation_handoff_validated=True,
        )
    common = {
        "local_webjob_package_valid": True,
        "readiness_receipt_validated": True,
        "generation_handoff_validated": True,
    }
    initial_generation = _generation(evidence_reader)
    if initial_generation != generation_handoff.environment_fingerprint:
        return _result(request, "generation_invalid", **common)
    common["generation_validated"] = True
    binding = _approval_binding(
        request,
        readiness_receipt,
        generation_handoff,
        package,
    )
    try:
        approved = (
            approver is not None
            and approver(WebJobDeploymentApprovalSummary()) is True
        )
    except (EOFError, KeyboardInterrupt, OSError, TimeoutError):
        approved = False
    if not approved:
        return _result(request, "approval_required", **common)
    common["operator_approval_obtained"] = True
    try:
        current_receipt, current_handoff = current_binding_reader()
    except Exception:
        current_receipt, current_handoff = None, None
    if (
        current_receipt != readiness_receipt
        or current_handoff != generation_handoff
        or not _receipt_valid(current_receipt, request)
        or not _handoff_valid(current_handoff, current_receipt, request)
    ):
        return _result(request, "generation_changed", **common)
    current_generation = _generation(evidence_reader)
    if (
        current_generation != initial_generation
        or current_generation != generation_handoff.environment_fingerprint
        or binding
        != _approval_binding(
            request,
            readiness_receipt,
            generation_handoff,
            package,
        )
    ):
        return _result(request, "generation_changed", **common)
    try:
        package_bytes = consume_hosted_webjob_package_authorization(
            package,
            request.source_root,
            session,
        )
    except HostedWebJobPackageError:
        return _result(request, "package_changed", **common)
    if uploader_factory is None:
        return _result(request, "unexpected_error", **common)
    try:
        uploader = uploader_factory()
    except Exception:
        return _result(request, "unexpected_error", **common)
    try:
        upload = uploader.upload(
            request.web_app_name,
            request.webjob_name,
            package_bytes,
        )
    except Exception:
        upload = KuduWebJobUploadResult(
            "upload_acceptance_ambiguous",
            True,
            False,
        )
    upload_common = {
        **common,
        "upload_attempted": upload.upload_attempted,
        "upload_accepted": upload.upload_accepted,
    }
    if not upload.upload_accepted:
        return _result(request, upload.category, **upload_common)
    if discovery_factory is None:
        return _result(request, "discovery_failed", **upload_common)
    try:
        discoverer = discovery_factory()
    except Exception:
        return _result(request, "discovery_failed", **upload_common)
    try:
        discovery = discoverer.discover(
            request.web_app_name,
            request.webjob_name,
        )
        if type(discovery) is not KuduWebJobDiscoveryResult:
            raise TypeError()
    except Exception:
        discovery = KuduWebJobDiscoveryResult(
            "discovery_ambiguous",
            True,
            False,
        )
    discovery_common = {
        **upload_common,
        "remote_discovery_attempted": discovery.discovery_attempted,
        "remote_webjob_discovered": discovery.remote_webjob_discovered,
    }
    if not discovery.remote_webjob_discovered:
        return _result(
            request,
            discovery.category,
            **discovery_common,
        )
    return _result(
        request,
        "success",
        ok=True,
        **discovery_common,
    )
