from __future__ import annotations

from dataclasses import dataclass, fields, replace
from importlib.util import find_spec
import os
from pathlib import Path
import re
import json
import subprocess
import tempfile
from typing import Callable, Literal, Protocol

from src.app.services.azure_what_if_evidence import SanitizedWhatIfChange


REBUILD_OPERATION = "rebuild_daily_azure_environment"
READY_MESSAGE = "DAILY AZURE ENVIRONMENT READY"
NOT_READY_MESSAGE = "DAILY AZURE ENVIRONMENT NOT READY"
RECOMMENDED_NEXT_STEP = (
    "The daily Azure environment is ready for the approved Azure-dependent slice."
)
FAILURE_NEXT_STEP = (
    "Review the sanitized failed stage and rerun only through an explicit new command."
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SESSION_FILE = Path(".artifacts/daily-azure-rebuild/current-session.env")

_REQUIRED_SETTINGS = (
    "AZURE_SUBSCRIPTION_NAME",
    "AZURE_LOCATION",
    "AZURE_RESOURCE_GROUP",
    "AZURE_ENVIRONMENT_NAME",
    "AZURE_PROJECT_NAME",
    "AZURE_FOUNDRY_ACCOUNT_NAME",
    "AZURE_FOUNDRY_PROJECT_NAME",
    "AZURE_FOUNDRY_MODEL_DEPLOYMENT_NAME",
    "AZURE_FOUNDRY_MODEL_NAME",
    "AZURE_FOUNDRY_MODEL_VERSION",
    "AZURE_FOUNDRY_MODEL_SKU",
    "AZURE_FOUNDRY_MODEL_CAPACITY",
    "AZURE_FOUNDRY_AGENT_NAME",
    "AZURE_WEB_APP_NAME",
    "AZURE_WEB_APP_SKU",
    "ENABLE_HOSTED_FOUNDRY_VERIFIER",
    "DISCOVER_HOSTED_FOUNDRY_WEBJOB",
)
_FORBIDDEN_SETTING_MARKERS = (
    "SECRET",
    "PASSWORD",
    "TOKEN",
    "KEY",
    "CONNECTION_STRING",
    "TENANT_ID",
    "SUBSCRIPTION_ID",
    "PRINCIPAL_ID",
    "RESOURCE_ID",
    "IDENTITY_HEADER",
    "ENDPOINT",
    "CREDENTIAL",
)
_PLACEHOLDER = re.compile(r"^<[^<>]+>$")
_AZURE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.()\-]*")
_RESOURCE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]*")
_LOCATION = re.compile(r"[a-z][a-z0-9]+")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.\-]*")


class ConfigValidationError(ValueError):
    def __init__(self, category: str) -> None:
        super().__init__("Daily Azure configuration is invalid.")
        self.category = category


@dataclass(frozen=True)
class DailyAzureConfig:
    subscription_name: str
    location: str
    resource_group: str
    environment_name: str
    project_name: str
    foundry_account_name: str
    foundry_project_name: str
    model_deployment_name: str
    model_name: str
    model_version: str
    model_sku: str
    model_capacity: int
    agent_name: str
    web_app_name: str
    web_app_sku: str
    enable_hosted_foundry_verifier: bool
    discover_hosted_foundry_webjob: bool


@dataclass(frozen=True)
class DailyAzureRuntimeContext:
    resource_group: str
    location: str
    foundry_account_name: str
    foundry_project_name: str
    project_endpoint: str
    model_deployment_name: str
    agent_name: str
    immutable_agent_version: str | None
    stable_agent_endpoint: str
    web_app_name: str
    hosted_origin: str


@dataclass(frozen=True)
class RuntimeUpdates:
    foundry_account_name: str | None = None
    project_endpoint: str | None = None
    immutable_agent_version: str | None = None
    stable_agent_endpoint: str | None = None
    hosted_origin: str | None = None


StageState = Literal["verified", "absent", "failed"]


@dataclass(frozen=True)
class StageResult:
    ok: bool
    state: StageState
    category: str
    reused: bool = False
    mutation_made: bool | None = False
    updates: RuntimeUpdates = RuntimeUpdates()
    attempted: bool = False
    accepted: bool = False
    artifact_current: bool = False

    def __post_init__(self) -> None:
        if self.ok and not isinstance(self.mutation_made, bool):
            raise ValueError("Successful stages require conclusive mutation state.")

    @classmethod
    def success(
        cls,
        *,
        reused: bool = False,
        mutation_made: bool | None = False,
        updates: RuntimeUpdates = RuntimeUpdates(),
        attempted: bool = False,
        accepted: bool = False,
        artifact_current: bool = False,
    ) -> "StageResult":
        return cls(
            True,
            "verified",
            "success",
            reused,
            mutation_made,
            updates,
            attempted,
            accepted,
            artifact_current,
        )

    @classmethod
    def absent(cls, category: str) -> "StageResult":
        return cls(False, "absent", category)

    @classmethod
    def failure(
        cls,
        category: str,
        *,
        mutation_made: bool | None = False,
        attempted: bool = False,
    ) -> "StageResult":
        return cls(
            False,
            "failed",
            category,
            mutation_made=mutation_made,
            attempted=attempted,
        )


@dataclass(frozen=True)
class ChangeEvidence:
    action: str
    logical_category: str
    boundary: str
    approved_boundary: bool
    expected_identity_match: bool = False
    expected_parent_match: bool = False
    expected_scope_match: bool = False
    expected_multiplicity_match: bool = False


@dataclass(frozen=True)
class PlanResult:
    create_count: int = 0
    modify_count: int = 0
    no_change_count: int = 0
    delete_count: int = 0
    ignore_count: int = 0
    deploy_count: int = 0
    unsupported_count: int = 0
    unknown_count: int = 0
    unrelated_resource_count: int = 0
    malformed: bool = False
    change_evidence: tuple[ChangeEvidence, ...] = ()
    exact_topology_match: bool = False

    @classmethod
    def create_only(cls) -> "PlanResult":
        return cls(create_count=1)

class DailyAzureStageRunner(Protocol):
    def verify_account(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def ensure_resource_group(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def verify_foundry(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def plan_foundry(self, context: DailyAzureRuntimeContext) -> PlanResult: ...
    def deploy_foundry(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def provision_agent(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def configure_agent_routing(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def verify_agent(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def verify_web_app_configuration(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def plan_web_app(self, context: DailyAzureRuntimeContext) -> PlanResult: ...
    def deploy_web_app(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def build_package(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def deploy_code(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def verify_readiness(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def verify_rbac(self, context: DailyAzureRuntimeContext) -> StageResult: ...
    def discover_webjob(self, context: DailyAzureRuntimeContext) -> StageResult: ...


@dataclass(frozen=True)
class DailyAzureEnvironmentRebuildResult:
    ok: bool
    category: str
    mode: Literal["check", "live"]
    local_orchestration_ready: bool = False
    daily_environment_ready: bool = False
    resource_group_ready: bool = False
    foundry_infrastructure_verified: bool = False
    prompt_agent_verified: bool = False
    immutable_routing_verified: bool = False
    web_app_configuration_verified: bool = False
    application_package_created: bool = False
    application_artifact_current: bool = False
    application_deployment_reused: bool = False
    application_deployment_attempted: bool = False
    application_deployment_accepted: bool = False
    hosted_readiness_verified: bool = False
    consumer_rbac_verified: bool = False
    webjob_discovered: bool = False
    azure_mutation_made: bool | None = False
    agent_invoked: bool = False
    webjob_triggered: bool = False
    webjob_status_read: bool = False
    managed_identity_verification_performed: bool = False
    recommended_next_step: str = FAILURE_NEXT_STEP

    def __post_init__(self) -> None:
        if self.daily_environment_ready and (
            not self.ok or not isinstance(self.azure_mutation_made, bool)
        ):
            raise ValueError("READY requires conclusive mutation state.")

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": REBUILD_OPERATION,
            "mode": self.mode,
            "local_orchestration_ready": self.local_orchestration_ready,
            "daily_environment_ready": self.daily_environment_ready,
            "resource_group_ready": self.resource_group_ready,
            "foundry_infrastructure_verified": self.foundry_infrastructure_verified,
            "prompt_agent_verified": self.prompt_agent_verified,
            "immutable_routing_verified": self.immutable_routing_verified,
            "web_app_configuration_verified": self.web_app_configuration_verified,
            "application_package_created": self.application_package_created,
            "application_artifact_current": self.application_artifact_current,
            "application_deployment_reused": self.application_deployment_reused,
            "application_deployment_attempted": self.application_deployment_attempted,
            "application_deployment_accepted": self.application_deployment_accepted,
            "hosted_readiness_verified": self.hosted_readiness_verified,
            "consumer_rbac_verified": self.consumer_rbac_verified,
            "webjob_discovered": self.webjob_discovered,
            "azure_mutation_made": self.azure_mutation_made,
            "agent_invoked": False,
            "webjob_triggered": False,
            "webjob_status_read": False,
            "managed_identity_verification_performed": False,
            "readiness_declaration": (
                READY_MESSAGE if self.daily_environment_ready else NOT_READY_MESSAGE
            ),
            "recommended_next_step": self.recommended_next_step,
        }


def load_daily_azure_config(
    path: Path | str,
    *,
    repository_root: Path = REPOSITORY_ROOT,
    repository_state_checker: Callable[[Path, Path], bool] = (
        lambda root, config: _config_is_ignored_and_untracked(root, config)
    ),
) -> DailyAzureConfig:
    config_path = Path(path)
    root = repository_root.resolve()
    try:
        resolved = config_path.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError):
        raise ConfigValidationError("missing_configuration") from None
    except ValueError:
        raise ConfigValidationError("committed_config_risk") from None
    if config_path.is_symlink() or resolved.name != ".env.daily-azure.local":
        raise ConfigValidationError("committed_config_risk")
    if not repository_state_checker(root, resolved):
        raise ConfigValidationError("committed_config_risk")

    values: dict[str, str] = {}
    try:
        lines = resolved.read_text().splitlines()
    except OSError:
        raise ConfigValidationError("missing_configuration") from None
    for line in lines:
        if not line or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            raise ConfigValidationError("invalid_configuration")
        key, value = line.split("=", 1)
        if key != key.strip() or not key or key in values:
            raise ConfigValidationError("invalid_configuration")
        if any(marker in key.upper() for marker in _FORBIDDEN_SETTING_MARKERS):
            raise ConfigValidationError("forbidden_setting")
        if key not in _REQUIRED_SETTINGS:
            raise ConfigValidationError("invalid_configuration")
        values[key] = value

    missing = [name for name in _REQUIRED_SETTINGS if name not in values]
    if missing:
        raise ConfigValidationError("missing_configuration")
    if any(not value or value != value.strip() for value in values.values()):
        raise ConfigValidationError("invalid_configuration")
    if any(_PLACEHOLDER.fullmatch(value) for value in values.values()):
        raise ConfigValidationError("placeholder_value")

    if not _LOCATION.fullmatch(values["AZURE_LOCATION"]):
        raise ConfigValidationError("invalid_configuration")
    if not _valid(values["AZURE_RESOURCE_GROUP"], _AZURE_NAME, 1, 90):
        raise ConfigValidationError("invalid_configuration")
    for name, minimum, maximum in (
        ("AZURE_ENVIRONMENT_NAME", 3, 10),
        ("AZURE_PROJECT_NAME", 3, 20),
        ("AZURE_FOUNDRY_ACCOUNT_NAME", 2, 64),
        ("AZURE_FOUNDRY_PROJECT_NAME", 2, 64),
        ("AZURE_FOUNDRY_MODEL_DEPLOYMENT_NAME", 2, 64),
        ("AZURE_FOUNDRY_AGENT_NAME", 2, 63),
        ("AZURE_WEB_APP_NAME", 2, 60),
    ):
        if not _valid(values[name], _RESOURCE_NAME, minimum, maximum):
            raise ConfigValidationError("invalid_configuration")
    if not _VERSION.fullmatch(values["AZURE_FOUNDRY_MODEL_NAME"]):
        raise ConfigValidationError("invalid_configuration")
    if not _VERSION.fullmatch(values["AZURE_FOUNDRY_MODEL_VERSION"]):
        raise ConfigValidationError("invalid_configuration")
    if values["AZURE_FOUNDRY_MODEL_SKU"] != "GlobalStandard":
        raise ConfigValidationError("invalid_configuration")
    if values["AZURE_WEB_APP_SKU"] != "B1":
        raise ConfigValidationError("invalid_configuration")
    try:
        capacity = int(values["AZURE_FOUNDRY_MODEL_CAPACITY"])
    except ValueError:
        raise ConfigValidationError("invalid_configuration") from None
    if capacity < 1:
        raise ConfigValidationError("invalid_configuration")
    hosted = _parse_bool(values["ENABLE_HOSTED_FOUNDRY_VERIFIER"])
    discovery = _parse_bool(values["DISCOVER_HOSTED_FOUNDRY_WEBJOB"])
    if hosted is None or discovery is None:
        raise ConfigValidationError("invalid_configuration")
    if discovery and not hosted:
        raise ConfigValidationError("incompatible_options")
    if not hosted:
        raise ConfigValidationError("incompatible_options")

    return DailyAzureConfig(
        subscription_name=values["AZURE_SUBSCRIPTION_NAME"],
        location=values["AZURE_LOCATION"],
        resource_group=values["AZURE_RESOURCE_GROUP"],
        environment_name=values["AZURE_ENVIRONMENT_NAME"],
        project_name=values["AZURE_PROJECT_NAME"],
        foundry_account_name=values["AZURE_FOUNDRY_ACCOUNT_NAME"],
        foundry_project_name=values["AZURE_FOUNDRY_PROJECT_NAME"],
        model_deployment_name=values["AZURE_FOUNDRY_MODEL_DEPLOYMENT_NAME"],
        model_name=values["AZURE_FOUNDRY_MODEL_NAME"],
        model_version=values["AZURE_FOUNDRY_MODEL_VERSION"],
        model_sku=values["AZURE_FOUNDRY_MODEL_SKU"],
        model_capacity=capacity,
        agent_name=values["AZURE_FOUNDRY_AGENT_NAME"],
        web_app_name=values["AZURE_WEB_APP_NAME"],
        web_app_sku=values["AZURE_WEB_APP_SKU"],
        enable_hosted_foundry_verifier=hosted,
        discover_hosted_foundry_webjob=discovery,
    )


def _valid(value: str, pattern: re.Pattern[str], minimum: int, maximum: int) -> bool:
    return minimum <= len(value) <= maximum and pattern.fullmatch(value) is not None


def _parse_bool(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _config_is_ignored_and_untracked(root: Path, config_path: Path) -> bool:
    try:
        relative = config_path.relative_to(root)
    except ValueError:
        return False
    ignored = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "--quiet", "--", str(relative)],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    tracked = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", str(relative)],
        shell=False,
        capture_output=True,
        text=True,
        check=False,
    )
    return ignored.returncode == 0 and tracked.returncode != 0


def safe_automatic_plan(
    plan: PlanResult,
    *,
    expected_boundary: str | None = None,
    require_create: bool = False,
) -> bool:
    if (
        plan.malformed
        or not plan.exact_topology_match
        or plan.modify_count
        or plan.delete_count
        or plan.deploy_count
        or plan.unknown_count
        or plan.unrelated_resource_count
        or (require_create and plan.create_count == 0)
    ):
        return False
    if plan.unsupported_count:
        return False
    expected_evidence_count = sum(
        (
            plan.create_count,
            plan.modify_count,
            plan.no_change_count,
            plan.delete_count,
            plan.ignore_count,
            plan.deploy_count,
            plan.unsupported_count,
        )
    )
    evidence_counts = {
        action: sum(change.action == action for change in plan.change_evidence)
        for action in ("Create", "Modify", "NoChange", "Delete", "Ignore", "Deploy", "Unsupported")
    }
    counts_match = evidence_counts == {
        "Create": plan.create_count,
        "Modify": plan.modify_count,
        "NoChange": plan.no_change_count,
        "Delete": plan.delete_count,
        "Ignore": plan.ignore_count,
        "Deploy": plan.deploy_count,
        "Unsupported": plan.unsupported_count,
    }
    return bool(
        expected_evidence_count == len(plan.change_evidence)
        and counts_match
        and all(
            change.approved_boundary
            and change.expected_identity_match
            and change.expected_parent_match
            and change.expected_scope_match
            and change.expected_multiplicity_match
            for change in plan.change_evidence
        )
        and (
            expected_boundary is None
            or all(
                change.boundary == expected_boundary
                for change in plan.change_evidence
            )
        )
    )


def validate_local_orchestration_contract(repository_root: Path) -> tuple[str, ...]:
    required = (
        "infra/foundry-only.bicep",
        "infra/main.bicep",
        "infra/foundry-agent-consumer-rbac.bicep",
        "scripts/deploy_foundry_infra.py",
        "scripts/verify_foundry_infra.py",
        "scripts/deploy_foundry_agent.py",
        "scripts/configure_foundry_agent_endpoint_routing.py",
        "scripts/verify_foundry_agent.py",
        "scripts/deploy_web_app_infra.py",
        "scripts/verify_web_app_configuration.py",
        "scripts/package_web_app.py",
        "scripts/deploy_web_app_code.py",
        "scripts/verify_web_app_readiness.py",
        "scripts/deploy_foundry_agent_consumer_rbac.py",
        "scripts/verify_foundry_agent_consumer_rbac.py",
        "scripts/run_hosted_foundry_agent_verification.py",
    )
    failures = [name for name in required if not (repository_root / name).is_file()]
    for dependency in ("azure.ai.projects", "azure.identity", "dotenv"):
        try:
            available = find_spec(dependency) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            failures.append(f"sdk:{dependency}")
    if failures:
        return tuple(failures)

    project_endpoint = (
        "https://fictional-account.services.ai.azure.com/"
        "api/projects/fictional-project"
    )
    stable_endpoint = (
        f"{project_endpoint}/agents/fictional-agent/endpoint/protocols/openai"
    )
    try:
        from scripts.deploy_foundry_infra import DeploymentRequest, _validate_files

        _, error = _validate_files(
            DeploymentRequest(
                "check",
                "foundry-only",
                repository_root / "infra/foundry-only.example.bicepparam",
                "fictional-rg",
                "eastus2",
            )
        )
        if error is not None:
            failures.append("contract:foundry_infrastructure")
    except Exception:
        failures.append("contract:foundry_infrastructure")
    try:
        from scripts.verify_foundry_infra import parse_project_endpoint

        if parse_project_endpoint(project_endpoint) != (
            "fictional-account",
            "fictional-project",
        ):
            failures.append("contract:foundry_verification")
    except Exception:
        failures.append("contract:foundry_verification")
    try:
        from src.app.services.foundry_agent_deployment import (
            foundry_agent_deployment_sdk_available,
        )
        from src.app.services.foundry_agent_verification import (
            foundry_agent_verification_sdk_available,
        )
        from src.app.services.foundry_agent_endpoint_routing import (
            FoundryAgentEndpointRouting,
            FoundryAgentEndpointRoutingRequest,
        )

        routing = FoundryAgentEndpointRouting().check(
            FoundryAgentEndpointRoutingRequest(
                project_endpoint,
                stable_endpoint,
                "fictional-agent",
                "1",
            )
        )
        if (
            not foundry_agent_deployment_sdk_available()
            or not foundry_agent_verification_sdk_available()
            or not routing.ok
        ):
            failures.append("contract:prompt_agent")
    except Exception:
        failures.append("contract:prompt_agent")
    try:
        from src.app.services.web_app_infra_deployment import (
            WebAppInfrastructureDeploymentRequest,
            deploy_web_app_infrastructure,
        )

        web = deploy_web_app_infrastructure(
            WebAppInfrastructureDeploymentRequest(
                mode="check",
                resource_group="fictional-rg",
                location="eastus2",
                environment_name="daily",
                project_name="nurse-intake",
                web_app_name="fictional-nurse-intake-web",
                cosmos_database_name="nurse-intake",
                cosmos_container_name="cases",
                template_file=repository_root / "infra/main.bicep",
                enable_hosted_foundry_verifier=True,
                hosted_verifier_project_endpoint=project_endpoint,
                hosted_verifier_stable_agent_endpoint=stable_endpoint,
                hosted_verifier_agent_name="fictional-agent",
                hosted_verifier_agent_version="1",
                hosted_verifier_model_deployment_name="fictional-model",
            )
        )
        if not web.ok:
            failures.append("contract:web_app_infrastructure")
    except Exception:
        failures.append("contract:web_app_infrastructure")
    try:
        from src.app.services.web_app_configuration_verification import (
            check_web_app_configuration_contract,
        )
        from src.app.services.web_app_package import plan_web_app_package
        from src.app.services.web_app_readiness_verification import (
            check_web_app_readiness_configuration,
        )

        if not check_web_app_configuration_contract().ok:
            failures.append("contract:web_app_configuration")
        plan_web_app_package(repository_root)
        if not check_web_app_readiness_configuration(
            "https://fictional-nurse-intake-web.azurewebsites.net"
        ).ok:
            failures.append("contract:web_app_readiness")
    except Exception:
        failures.append("contract:web_app_package_or_readiness")
    try:
        from src.app.services.foundry_agent_consumer_rbac_deployment import (
            EXPECTED_TEMPLATE,
            FoundryAgentConsumerRbacDeploymentRequest,
            deploy_foundry_agent_consumer_rbac,
        )
        from src.app.services.foundry_agent_consumer_rbac_verification import (
            FoundryAgentConsumerRbacVerificationRequest,
            verify_foundry_agent_consumer_rbac,
        )

        rbac_deploy = deploy_foundry_agent_consumer_rbac(
            FoundryAgentConsumerRbacDeploymentRequest(
                "check",
                "fictional-rg",
                "fictional-nurse-intake-web",
                "fictional-account",
                "fictional-project",
                EXPECTED_TEMPLATE,
            )
        )
        rbac_verify = verify_foundry_agent_consumer_rbac(
            FoundryAgentConsumerRbacVerificationRequest(
                "check",
                "fictional-rg",
                "fictional-nurse-intake-web",
                "fictional-account",
                "fictional-project",
            )
        )
        if not rbac_deploy.ok or not rbac_verify.ok:
            failures.append("contract:consumer_rbac")
    except Exception:
        failures.append("contract:consumer_rbac")
    try:
        from src.app.services.hosted_foundry_agent_webjob_execution import (
            HostedFoundryAgentWebJobExecutionRequest,
            execute_hosted_foundry_agent_webjob,
        )

        discovery = execute_hosted_foundry_agent_webjob(
            HostedFoundryAgentWebJobExecutionRequest(
                "check",
                "fictional-rg",
                "fictional-nurse-intake-web",
                repository_root,
            )
        )
        if not discovery.ok:
            failures.append("contract:webjob_discovery")
    except Exception:
        failures.append("contract:webjob_discovery")
    return tuple(failures)


def write_runtime_session_file(
    path: Path,
    context: DailyAzureRuntimeContext,
) -> None:
    if _path_has_symlink(path):
        raise OSError("Unsafe runtime session path.")
    path.parent.mkdir(parents=True, exist_ok=True)
    if _path_has_symlink(path):
        raise OSError("Unsafe runtime session path.")
    values = {
        "AZURE_RESOURCE_GROUP": context.resource_group,
        "AZURE_LOCATION": context.location,
        "AZURE_FOUNDRY_ACCOUNT_NAME": context.foundry_account_name,
        "AZURE_FOUNDRY_PROJECT_NAME": context.foundry_project_name,
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": context.project_endpoint,
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": context.model_deployment_name,
        "AZURE_AI_FOUNDRY_AGENT_NAME": context.agent_name,
        "AZURE_AI_FOUNDRY_AGENT_VERSION": context.immutable_agent_version or "",
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": context.stable_agent_endpoint,
        "AZURE_WEB_APP_NAME": context.web_app_name,
        "AZURE_WEB_APP_ORIGIN": context.hosted_origin,
    }
    payload = "".join(f"{name}={value}\n" for name, value in values.items())
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=".current-session.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(file_descriptor, 0o600)
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


class DailyAzureEnvironmentRebuild:
    def __init__(
        self,
        config: DailyAzureConfig,
        *,
        repository_root: Path = REPOSITORY_ROOT,
        runner_factory: Callable[[], DailyAzureStageRunner] | None = None,
        local_contract_checker: Callable[[Path], tuple[str, ...]] = (
            validate_local_orchestration_contract
        ),
    ) -> None:
        self.config = config
        self.repository_root = repository_root
        self.runner_factory = runner_factory
        self.local_contract_checker = local_contract_checker

    def check(self) -> DailyAzureEnvironmentRebuildResult:
        failures = self.local_contract_checker(self.repository_root)
        return DailyAzureEnvironmentRebuildResult(
            ok=not failures,
            category="success" if not failures else "local_contract_invalid",
            mode="check",
            local_orchestration_ready=not failures,
            recommended_next_step=(
                "Run --live --json only after reviewing this offline result."
                if not failures
                else FAILURE_NEXT_STEP
            ),
        )

    def live(
        self, runner: DailyAzureStageRunner | None = None
    ) -> DailyAzureEnvironmentRebuildResult:
        progress: dict[str, bool] = {}
        mutation: list[bool | None] = [False]
        try:
            failures = self.local_contract_checker(self.repository_root)
        except Exception:
            return self._failure("local_contract_invalid")
        if failures:
            return self._failure("local_contract_invalid")
        progress["local_orchestration_ready"] = True

        if runner is None:
            if self.runner_factory is None:
                return self._failure("runner_unavailable", progress)
            try:
                runner = self.runner_factory()
            except Exception:
                return self._failure("runner_unavailable", progress)
        try:
            return self._live(runner, progress, mutation)
        except Exception:
            if mutation[0] is False:
                mutation[0] = None
            return self._failure("unexpected_error", progress, mutation[0])

    def _live(
        self,
        runner: DailyAzureStageRunner,
        progress: dict[str, bool],
        mutation: list[bool | None],
    ) -> DailyAzureEnvironmentRebuildResult:
        context = self._initial_context()

        def apply(result: StageResult) -> bool:
            nonlocal context
            mutation[0] = _combine_mutation_state(mutation[0], result.mutation_made)
            if not result.ok:
                return False
            context = _apply_updates(context, result.updates)
            return True

        account = runner.verify_account(context)
        if not apply(account):
            return self._failure(account.category, progress, mutation[0])
        group = runner.ensure_resource_group(context)
        if not apply(group):
            return self._failure(group.category, progress, mutation[0])
        progress["resource_group_ready"] = True

        foundry = runner.verify_foundry(context)
        if foundry.state == "absent":
            plan = runner.plan_foundry(context)
            if not safe_automatic_plan(
                plan,
                expected_boundary="foundry",
                require_create=True,
            ):
                return self._failure("unsafe_foundry_plan", progress, mutation[0])
            deployed = runner.deploy_foundry(context)
            if not apply(deployed):
                return self._failure(deployed.category, progress, mutation[0])
            foundry = runner.verify_foundry(context)
        if not apply(foundry):
            return self._failure(foundry.category, progress, mutation[0])
        progress["foundry_infrastructure_verified"] = True

        agent = runner.provision_agent(context)
        if not apply(agent) or not context.immutable_agent_version:
            return self._failure(agent.category, progress, mutation[0])
        try:
            write_runtime_session_file(self.repository_root / SESSION_FILE, context)
        except OSError:
            return self._failure("runtime_session_write_failed", progress, mutation[0])
        routing = runner.configure_agent_routing(context)
        if not apply(routing):
            return self._failure(routing.category, progress, mutation[0])
        verified_agent = runner.verify_agent(context)
        if not apply(verified_agent):
            return self._failure(verified_agent.category, progress, mutation[0])
        progress["prompt_agent_verified"] = True
        progress["immutable_routing_verified"] = True

        web_config = runner.verify_web_app_configuration(context)
        if web_config.state == "absent":
            plan = runner.plan_web_app(context)
            if not safe_automatic_plan(
                plan,
                expected_boundary="web_app",
                require_create=True,
            ):
                return self._failure("unsafe_web_app_plan", progress, mutation[0])
            deployed = runner.deploy_web_app(context)
            if not apply(deployed):
                return self._failure(deployed.category, progress, mutation[0])
            web_config = runner.verify_web_app_configuration(context)
        if not apply(web_config):
            return self._failure(web_config.category, progress, mutation[0])
        progress["web_app_configuration_verified"] = True

        package = runner.build_package(context)
        if not apply(package):
            return self._failure(package.category, progress, mutation[0])
        progress["application_package_created"] = True
        code = runner.deploy_code(context)
        progress["application_deployment_attempted"] = code.attempted
        progress["application_deployment_reused"] = code.reused
        if not apply(code):
            return self._failure(code.category, progress, mutation[0])
        progress["application_deployment_accepted"] = code.accepted
        deployment_proven = bool(
            code.attempted and code.accepted and not code.reused
        )
        if not deployment_proven:
            return self._failure("application_provenance_invalid", progress, mutation[0])
        readiness = runner.verify_readiness(context)
        if not apply(readiness):
            return self._failure(readiness.category, progress, mutation[0])
        if not readiness.artifact_current:
            return self._failure(
                "application_artifact_mismatch",
                progress,
                mutation[0],
            )
        progress["hosted_readiness_verified"] = True
        progress["application_artifact_current"] = True

        rbac = runner.verify_rbac(context)
        if rbac.state == "absent":
            return self._failure(
                "manual_rbac_action_required",
                progress,
                mutation[0],
            )
        if not apply(rbac):
            return self._failure(rbac.category, progress, mutation[0])
        progress["consumer_rbac_verified"] = True

        if self.config.discover_hosted_foundry_webjob:
            discovery = runner.discover_webjob(context)
            if not apply(discovery):
                return self._failure(discovery.category, progress, mutation[0])
            progress["webjob_discovered"] = True

        return DailyAzureEnvironmentRebuildResult(
            ok=True,
            category="success",
            mode="live",
            daily_environment_ready=True,
            azure_mutation_made=mutation[0],
            recommended_next_step=RECOMMENDED_NEXT_STEP,
            **progress,
        )

    def _initial_context(self) -> DailyAzureRuntimeContext:
        project_endpoint = (
            f"https://{self.config.foundry_account_name}.services.ai.azure.com/"
            f"api/projects/{self.config.foundry_project_name}"
        )
        stable_endpoint = (
            f"{project_endpoint}/agents/{self.config.agent_name}/"
            "endpoint/protocols/openai"
        )
        return DailyAzureRuntimeContext(
            resource_group=self.config.resource_group,
            location=self.config.location,
            foundry_account_name=self.config.foundry_account_name,
            foundry_project_name=self.config.foundry_project_name,
            project_endpoint=project_endpoint,
            model_deployment_name=self.config.model_deployment_name,
            agent_name=self.config.agent_name,
            immutable_agent_version=None,
            stable_agent_endpoint=stable_endpoint,
            web_app_name=self.config.web_app_name,
            hosted_origin=f"https://{self.config.web_app_name}.azurewebsites.net",
        )

    def _failure(
        self,
        category: str,
        progress: dict[str, bool] | None = None,
        mutation_made: bool | None = False,
    ) -> DailyAzureEnvironmentRebuildResult:
        allowed = {field.name for field in fields(DailyAzureEnvironmentRebuildResult)}
        safe_progress = {
            key: value for key, value in (progress or {}).items() if key in allowed
        }
        return DailyAzureEnvironmentRebuildResult(
            ok=False,
            category=category,
            mode="live",
            azure_mutation_made=mutation_made,
            **safe_progress,
        )


def _combine_mutation_state(
    current: bool | None,
    incoming: bool | None,
) -> bool | None:
    if current is True or incoming is True:
        return True
    if current is None or incoming is None:
        return None
    return False


def _apply_updates(
    context: DailyAzureRuntimeContext,
    updates: RuntimeUpdates,
) -> DailyAzureRuntimeContext:
    values = {
        name: value
        for name, value in (
            ("foundry_account_name", updates.foundry_account_name),
            ("project_endpoint", updates.project_endpoint),
            ("immutable_agent_version", updates.immutable_agent_version),
            ("stable_agent_endpoint", updates.stable_agent_endpoint),
            ("hosted_origin", updates.hosted_origin),
        )
        if value is not None
    }
    return replace(context, **values) if values else context


@dataclass(frozen=True)
class _CommandResult:
    return_code: int
    stdout: str
    stderr: str


class _SubprocessRunner:
    def run(self, args: list[str]) -> _CommandResult:
        try:
            completed = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return _CommandResult(127, "", "")
        return _CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


class RepositoryDailyAzureStageRunner:
    """Thin live adapter over the repository's existing resource boundaries."""

    def __init__(
        self,
        config: DailyAzureConfig,
        *,
        repository_root: Path = REPOSITORY_ROOT,
        command_runner: _SubprocessRunner | None = None,
    ) -> None:
        from src.app.services.web_app_package import (
            create_package_authorization_session,
        )

        self.config = config
        self.repository_root = repository_root
        self.command_runner = command_runner or _SubprocessRunner()
        self._package = None
        self._package_authorization_session = create_package_authorization_session()
        self._expected_application_artifact_digest: str | None = None
        self._foundry_parameters: Path | None = None

    def verify_account(self, context: DailyAzureRuntimeContext) -> StageResult:
        outcome = self.command_runner.run(
            [
                "az",
                "account",
                "show",
                "--query",
                "{subscription:name,state:state,isDefault:isDefault}",
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
        payload = _json_object(outcome.stdout) if outcome.return_code == 0 else None
        if (
            payload is None
            or payload.get("subscription") != self.config.subscription_name
            or payload.get("state") != "Enabled"
            or payload.get("isDefault") is not True
        ):
            return StageResult.failure(
                "account_mismatch"
                if outcome.return_code == 0
                else "authentication_or_authorization_failed"
            )
        return StageResult.success(reused=True)

    def ensure_resource_group(self, context: DailyAzureRuntimeContext) -> StageResult:
        exists = self.command_runner.run(
            [
                "az",
                "group",
                "exists",
                "--name",
                context.resource_group,
                "--output",
                "tsv",
                "--only-show-errors",
            ]
        )
        if exists.return_code != 0:
            return StageResult.failure("resource_group_read_failed")
        if exists.stdout.strip().casefold() == "false":
            created = self.command_runner.run(
                [
                    "az",
                    "group",
                    "create",
                    "--name",
                    context.resource_group,
                    "--location",
                    context.location,
                    "--tags",
                    "purpose=fictional-daily-validation",
                    "--query",
                    "{location:location,provisioningState:properties.provisioningState}",
                    "--output",
                    "json",
                    "--only-show-errors",
                ]
            )
            payload = _json_object(created.stdout) if created.return_code == 0 else None
            if payload is None or not _location_matches(payload.get("location"), context.location):
                return StageResult.failure(
                    "resource_group_creation_failed",
                    mutation_made=None,
                    attempted=True,
                )
            state = payload.get("provisioningState")
            if state not in {None, "Succeeded"}:
                return StageResult.failure(
                    "resource_group_creation_failed",
                    mutation_made=None,
                    attempted=True,
                )
            return StageResult.success(mutation_made=True)
        if exists.stdout.strip().casefold() != "true":
            return StageResult.failure("resource_group_response_invalid")
        shown = self.command_runner.run(
            [
                "az",
                "group",
                "show",
                "--name",
                context.resource_group,
                "--query",
                "{location:location,provisioningState:properties.provisioningState}",
                "--output",
                "json",
                "--only-show-errors",
            ]
        )
        payload = _json_object(shown.stdout) if shown.return_code == 0 else None
        if payload is None or not _location_matches(payload.get("location"), context.location):
            return StageResult.failure("resource_group_location_mismatch")
        if payload.get("provisioningState") not in {None, "Succeeded"}:
            return StageResult.failure("resource_group_not_ready")
        return StageResult.success(reused=True)

    def verify_foundry(self, context: DailyAzureRuntimeContext) -> StageResult:
        from scripts.verify_foundry_infra import VerificationRequest, verify

        result = verify(
            VerificationRequest(
                context.resource_group,
                context.project_endpoint,
                context.model_deployment_name,
                expected_model_capacity=self.config.model_capacity,
                expected_purpose_tag="fictional-daily-validation",
            ),
            self.command_runner,
        )
        if result.get("category") == "resource_not_found":
            return StageResult.absent("foundry_absent")
        if not result.get("ok"):
            return StageResult.failure(str(result.get("category", "foundry_verification_failed")))
        if (
            result.get("model_name") != self.config.model_name
            or result.get("model_version") != self.config.model_version
            or result.get("model_format") != "OpenAI"
            or result.get("model_sku") != self.config.model_sku
            or result.get("model_capacity") != self.config.model_capacity
        ):
            return StageResult.failure("foundry_model_drift")
        return StageResult.success(reused=True)

    def plan_foundry(self, context: DailyAzureRuntimeContext) -> PlanResult:
        from scripts.deploy_foundry_infra import DeploymentRequest, execute

        parameters = self._parameters_file()
        if parameters is None:
            return PlanResult(malformed=True)
        result = execute(
            DeploymentRequest(
                "what-if",
                "foundry-only",
                parameters,
                context.resource_group,
                context.location,
            ),
            self.command_runner,
            verify_resource_group=False,
        )
        return _plan_from_mapping(result)

    def deploy_foundry(self, context: DailyAzureRuntimeContext) -> StageResult:
        from scripts.deploy_foundry_infra import DeploymentRequest, execute

        parameters = self._parameters_file()
        if parameters is None:
            return StageResult.failure("parameter_file_invalid")
        result = execute(
            DeploymentRequest(
                "live",
                "foundry-only",
                parameters,
                context.resource_group,
                context.location,
            ),
            self.command_runner,
            ensure_resource_group=False,
        )
        endpoint = result.get("project_endpoint")
        if not result.get("ok") or endpoint != context.project_endpoint:
            return StageResult.failure(
                str(result.get("category", "foundry_deployment_failed")),
                mutation_made=None,
                attempted=True,
            )
        return StageResult.success(mutation_made=True)

    def provision_agent(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.foundry_agent_deployment import (
            FoundryAgentDeployment,
            FoundryAgentDeploymentRequest,
        )
        from src.app.services.nurse_intake_agent_instructions import (
            build_nurse_intake_agent_instructions,
        )

        result = FoundryAgentDeployment().provision(
            FoundryAgentDeploymentRequest(
                project_endpoint=context.project_endpoint,
                agent_name=context.agent_name,
                model_deployment_name=context.model_deployment_name,
                instructions=build_nurse_intake_agent_instructions(),
            )
        )
        version = result.resolved_agent_version
        if not result.ok or not version or result.resolved_agent_name != context.agent_name:
            return StageResult.failure(
                result.category,
                mutation_made=getattr(result, "azure_mutation_made", False),
                attempted=getattr(result, "azure_call_made", False),
            )
        return StageResult.success(
            reused=result.agent_reused,
            mutation_made=result.agent_created or result.agent_updated,
            updates=RuntimeUpdates(immutable_agent_version=version),
        )

    def configure_agent_routing(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.foundry_agent_endpoint_routing import (
            FoundryAgentEndpointRouting,
            FoundryAgentEndpointRoutingRequest,
        )

        if context.immutable_agent_version is None:
            return StageResult.failure("missing_configuration")
        result = FoundryAgentEndpointRouting().configure(
            FoundryAgentEndpointRoutingRequest(
                project_endpoint=context.project_endpoint,
                stable_agent_endpoint=context.stable_agent_endpoint,
                agent_name=context.agent_name,
                agent_version=context.immutable_agent_version,
            )
        )
        if not result.ok or result.agent_invoked or not result.responses_protocol_present:
            return StageResult.failure(
                result.category,
                mutation_made=result.azure_mutation_made,
                attempted=result.azure_call_made,
            )
        return StageResult.success(
            reused=result.routing_reused,
            mutation_made=result.routing_updated,
        )

    def verify_agent(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.foundry_agent_verification import (
            FoundryAgentVerification,
            FoundryAgentVerificationRequest,
        )
        from src.app.services.nurse_intake_agent_instructions import (
            build_nurse_intake_agent_instructions,
        )

        if context.immutable_agent_version is None:
            return StageResult.failure("missing_configuration")
        result = FoundryAgentVerification().verify(
            FoundryAgentVerificationRequest(
                project_endpoint=context.project_endpoint,
                stable_agent_endpoint=context.stable_agent_endpoint,
                agent_name=context.agent_name,
                agent_version=context.immutable_agent_version,
                model_deployment_name=context.model_deployment_name,
                instructions=build_nurse_intake_agent_instructions(),
            )
        )
        if (
            not result.ok
            or not result.immutable_version_verified
            or not result.agent_definition_matches
            or not result.responses_protocol_present
            or result.configured_version_traffic_percentage != 100
            or result.agent_invoked
            or result.azure_mutation_made
        ):
            return StageResult.failure(result.category)
        return StageResult.success(reused=True)

    def verify_web_app_configuration(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.web_app_configuration_verification import (
            verify_web_app_configuration,
        )

        result = verify_web_app_configuration(
            context.resource_group,
            context.web_app_name,
            _hosted_settings(context),
            verify_hosted_foundry_verifier=True,
            runner=self.command_runner,
        )
        if result.category == "web_app_not_found":
            return StageResult.absent("web_app_absent")
        if not result.ok or not result.hosted_verifier_configuration_verified:
            return StageResult.failure(result.category)
        return StageResult.success(reused=True)

    def plan_web_app(self, context: DailyAzureRuntimeContext) -> PlanResult:
        from src.app.services.web_app_infra_deployment import (
            deploy_web_app_infrastructure,
        )

        result = deploy_web_app_infrastructure(
            self._web_app_request("what-if", context), runner=self.command_runner
        )
        return _plan_from_object(result)

    def deploy_web_app(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.web_app_infra_deployment import (
            deploy_web_app_infrastructure,
        )

        result = deploy_web_app_infrastructure(
            self._web_app_request("live", context), runner=self.command_runner
        )
        if not result.ok or not result.deployment_attempted:
            return StageResult.failure(
                result.category,
                mutation_made=None if result.deployment_attempted else False,
                attempted=result.deployment_attempted,
            )
        return StageResult.success(mutation_made=True)

    def build_package(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.web_app_package import (
            PackageSafetyError,
            authorized_application_artifact_digest,
            build_web_app_package,
            plan_web_app_package,
        )

        try:
            plan_web_app_package(self.repository_root)
            self._package = build_web_app_package(
                self.repository_root,
                authorization_session=self._package_authorization_session,
            )
            self._expected_application_artifact_digest = (
                authorized_application_artifact_digest(
                    self._package,
                    self.repository_root,
                    self._package_authorization_session,
                )
            )
        except PackageSafetyError as error:
            return StageResult.failure(error.category)
        return StageResult.success()

    def deploy_code(self, context: DailyAzureRuntimeContext) -> StageResult:
        from scripts.deploy_web_app_code import DeploymentRequest, execute

        if self._package is None:
            return StageResult.failure("package_missing")
        result = execute(
            DeploymentRequest("live", context.resource_group, context.web_app_name),
            runner=self.command_runner,
            source_root=self.repository_root,
            prebuilt_package=self._package,
            authorization_session=self._package_authorization_session,
        )
        if not result.get("ok") or not result.get("deployment_accepted"):
            attempted = result.get("azure_command_attempted") is True
            return StageResult.failure(
                str(result.get("category", "deployment_failed")),
                mutation_made=None if attempted else False,
                attempted=attempted,
            )
        return StageResult.success(
            mutation_made=True,
            attempted=True,
            accepted=True,
        )

    def verify_readiness(self, context: DailyAzureRuntimeContext) -> StageResult:
        if self._expected_application_artifact_digest is None:
            return StageResult.failure("package_missing")
        result = self._readiness_result(context)
        if (
            not result.ok
            or not result.safe_hosted_posture_verified
            or not result.application_artifact_matches
        ):
            return StageResult.failure(result.category)
        return StageResult.success(reused=True, artifact_current=True)

    def _readiness_result(self, context: DailyAzureRuntimeContext):
        from src.app.services.web_app_readiness_verification import (
            UrllibWebAppReadinessTransport,
            verify_web_app_readiness,
        )

        return verify_web_app_readiness(
            context.hosted_origin,
            transport_factory=UrllibWebAppReadinessTransport,
            expected_application_artifact_digest=(
                self._expected_application_artifact_digest
            ),
        )

    def verify_rbac(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.foundry_agent_consumer_rbac_verification import (
            FoundryAgentConsumerRbacVerificationRequest,
            verify_foundry_agent_consumer_rbac,
        )

        result = verify_foundry_agent_consumer_rbac(
            FoundryAgentConsumerRbacVerificationRequest(
                "live",
                context.resource_group,
                context.web_app_name,
                context.foundry_account_name,
                context.foundry_project_name,
            ),
            runner=self.command_runner,
        )
        if (
            result.category == "assignment_missing"
            and result.web_app_identity_present
            and result.foundry_project_scope_resolved
        ):
            return StageResult.absent("rbac_absent")
        if not result.ok:
            return StageResult.failure(result.category)
        return StageResult.success(reused=True)

    def discover_webjob(self, context: DailyAzureRuntimeContext) -> StageResult:
        from src.app.services.hosted_foundry_agent_webjob_execution import (
            HostedFoundryAgentWebJobExecutionRequest,
            execute_hosted_foundry_agent_webjob,
        )

        result = execute_hosted_foundry_agent_webjob(
            HostedFoundryAgentWebJobExecutionRequest(
                "live-discover",
                context.resource_group,
                context.web_app_name,
                self.repository_root,
            ),
            runner=self.command_runner,
        )
        if (
            not result.ok
            or not result.remote_webjob_discovered
            or result.trigger_request_accepted
            or result.invocation_attempted
        ):
            return StageResult.failure(result.category)
        return StageResult.success(reused=True)

    def _parameters_file(self) -> Path | None:
        if self._foundry_parameters is not None:
            return self._foundry_parameters
        path = self.repository_root / ".artifacts/daily-azure-rebuild/foundry-only.bicepparam"
        if _path_has_symlink(path):
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        content = (
            "using '../../infra/foundry-only.bicep'\n\n"
            f"param location = '{self.config.location}'\n"
            f"param projectName = '{self.config.project_name}'\n"
            f"param environmentName = '{self.config.environment_name}'\n"
            f"param foundryAccountName = '{self.config.foundry_account_name}'\n"
            f"param foundryProjectName = '{self.config.foundry_project_name}'\n"
            "param foundryProjectDisplayName = 'Fictional Intake Daily Validation'\n"
            "param foundryProjectDescription = 'Disposable fictional validation project.'\n"
            f"param modelDeploymentName = '{self.config.model_deployment_name}'\n"
            f"param modelName = '{self.config.model_name}'\n"
            f"param modelVersion = '{self.config.model_version}'\n"
            "param modelPublisherFormat = 'OpenAI'\n"
            f"param modelSkuName = '{self.config.model_sku}'\n"
            f"param modelCapacity = {self.config.model_capacity}\n"
            "param tags = { purpose: 'fictional-daily-validation' }\n"
        )
        try:
            _atomic_text_write(path, content)
        except OSError:
            return None
        self._foundry_parameters = path
        return path

    def _web_app_request(self, mode: str, context: DailyAzureRuntimeContext):
        from src.app.services.web_app_infra_deployment import (
            WebAppInfrastructureDeploymentRequest,
        )

        return WebAppInfrastructureDeploymentRequest(
            mode=mode,
            resource_group=context.resource_group,
            location=context.location,
            environment_name=self.config.environment_name,
            project_name=self.config.project_name,
            web_app_name=context.web_app_name,
            cosmos_database_name="nurse-intake",
            cosmos_container_name="cases",
            template_file=self.repository_root / "infra/main.bicep",
            enable_hosted_foundry_verifier=True,
            hosted_verifier_project_endpoint=context.project_endpoint,
            hosted_verifier_stable_agent_endpoint=context.stable_agent_endpoint,
            hosted_verifier_agent_name=context.agent_name,
            hosted_verifier_agent_version=context.immutable_agent_version,
            hosted_verifier_model_deployment_name=context.model_deployment_name,
        )


def _hosted_settings(context: DailyAzureRuntimeContext) -> dict[str, str]:
    return {
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": context.project_endpoint,
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": context.stable_agent_endpoint,
        "AZURE_AI_FOUNDRY_AGENT_NAME": context.agent_name,
        "AZURE_AI_FOUNDRY_AGENT_VERSION": context.immutable_agent_version or "",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": context.model_deployment_name,
    }


def _json_object(value: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _location_matches(value: object, expected: str) -> bool:
    return isinstance(value, str) and value.casefold().replace(" ", "") == expected.casefold()


def _plan_from_mapping(value: dict[str, object]) -> PlanResult:
    names = (
        "create_count",
        "modify_count",
        "no_change_count",
        "delete_count",
        "ignore_count",
        "deploy_count",
        "unsupported_count",
    )
    if not value.get("ok") or not all(_valid_count(value.get(name)) for name in names):
        return PlanResult(malformed=True)
    evidence = _change_evidence(value.get("change_evidence"))
    exact_topology_match = value.get("exact_topology_match")
    if evidence is None or not isinstance(exact_topology_match, bool):
        return PlanResult(malformed=True)
    return PlanResult(
        create_count=_count(value.get("create_count")),
        modify_count=_count(value.get("modify_count")),
        no_change_count=_count(value.get("no_change_count")),
        delete_count=_count(value.get("delete_count")),
        ignore_count=_count(value.get("ignore_count")),
        deploy_count=_count(value.get("deploy_count")),
        unsupported_count=_count(value.get("unsupported_count")),
        change_evidence=evidence,
        exact_topology_match=exact_topology_match,
    )


def _plan_from_object(value: object) -> PlanResult:
    names = (
        "create_count",
        "modify_count",
        "no_change_count",
        "delete_count",
        "ignore_count",
        "deploy_count",
        "unsupported_count",
    )
    if not getattr(value, "ok", False) or not all(
        _valid_count(getattr(value, name, None)) for name in names
    ):
        return PlanResult(malformed=True)
    evidence = _change_evidence(getattr(value, "change_evidence", None))
    exact_topology_match = getattr(value, "exact_topology_match", None)
    if evidence is None or not isinstance(exact_topology_match, bool):
        return PlanResult(malformed=True)
    return PlanResult(
        create_count=_count(getattr(value, "create_count", None)),
        modify_count=_count(getattr(value, "modify_count", None)),
        no_change_count=_count(getattr(value, "no_change_count", None)),
        delete_count=_count(getattr(value, "delete_count", None)),
        ignore_count=_count(getattr(value, "ignore_count", None)),
        deploy_count=_count(getattr(value, "deploy_count", None)),
        unsupported_count=_count(getattr(value, "unsupported_count", None)),
        change_evidence=evidence,
        exact_topology_match=exact_topology_match,
    )


def _change_evidence(value: object) -> tuple[ChangeEvidence, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    parsed: list[ChangeEvidence] = []
    for item in value:
        if isinstance(item, SanitizedWhatIfChange):
            parsed.append(
                ChangeEvidence(
                    item.action,
                    item.logical_category,
                    item.boundary,
                    item.approved_boundary,
                    item.expected_identity_match,
                    item.expected_parent_match,
                    item.expected_scope_match,
                    item.expected_multiplicity_match,
                )
            )
            continue
        if not isinstance(item, dict):
            return None
        action = item.get("action")
        category = item.get("logical_category")
        boundary = item.get("boundary")
        approved = item.get("approved_boundary")
        identity_match = item.get("expected_identity_match")
        parent_match = item.get("expected_parent_match")
        scope_match = item.get("expected_scope_match")
        multiplicity_match = item.get("expected_multiplicity_match")
        if (
            not isinstance(action, str)
            or not isinstance(category, str)
            or not isinstance(boundary, str)
            or not isinstance(approved, bool)
            or not isinstance(identity_match, bool)
            or not isinstance(parent_match, bool)
            or not isinstance(scope_match, bool)
            or not isinstance(multiplicity_match, bool)
        ):
            return None
        parsed.append(
            ChangeEvidence(
                action,
                category,
                boundary,
                approved,
                identity_match,
                parent_match,
                scope_match,
                multiplicity_match,
            )
        )
    return tuple(parsed)


def _count(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _valid_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _atomic_text_write(path: Path, content: str) -> None:
    if _path_has_symlink(path):
        raise OSError("Unsafe artifact path.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        os.chmod(path, 0o600)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _path_has_symlink(path: Path) -> bool:
    for current in (path, *path.parents):
        if current.is_symlink():
            return True
    return False
