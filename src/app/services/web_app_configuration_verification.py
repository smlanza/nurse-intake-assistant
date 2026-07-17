from dataclasses import dataclass
import json
from typing import Literal, Protocol

from src.app.services.web_app_hosting_contract import (
    REMOTE_BUILD_SETTING,
    SAFE_HOSTED_SETTINGS,
)

EXPECTED_LOCAL_CONTRACT = {
    "linux_fx_version": "PYTHON|3.12",
    "startup_command": (
        "python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000"
    ),
    "health_check_path": "/health",
    "remote_build_setting": "SCM_DO_BUILD_DURING_DEPLOYMENT",
}
EXPECTED_SAFE_APP_SETTINGS = SAFE_HOSTED_SETTINGS
EXPECTED_LINUX_FX_VERSION = EXPECTED_LOCAL_CONTRACT["linux_fx_version"]
EXPECTED_STARTUP_COMMAND = EXPECTED_LOCAL_CONTRACT["startup_command"]
EXPECTED_HEALTH_CHECK_PATH = EXPECTED_LOCAL_CONTRACT["health_check_path"]
SAFE_APP_SETTINGS = dict(EXPECTED_SAFE_APP_SETTINGS)

SITE_QUERY = (
    "{state:state,enabled:enabled,httpsOnly:httpsOnly,kind:kind,"
    "reserved:reserved,identityType:identity.type}"
)
SITE_CONFIG_QUERY = (
    "{linuxFxVersion:linuxFxVersion,appCommandLine:appCommandLine,"
    "ftpsState:ftpsState,minTlsVersion:minTlsVersion,"
    "scmMinTlsVersion:scmMinTlsVersion,healthCheckPath:healthCheckPath}"
)
_APP_SETTING_NAMES = (*SAFE_APP_SETTINGS, REMOTE_BUILD_SETTING)
APP_SETTINGS_QUERY = (
    "[?"
    + " || ".join(f"name=='{name}'" for name in _APP_SETTING_NAMES)
    + "].{name:name,value:value}"
)

ConfigurationCategory = Literal[
    "success",
    "missing_arguments",
    "web_app_not_found",
    "provisioning_incomplete",
    "runtime_contract_invalid",
    "startup_command_invalid",
    "remote_build_missing",
    "security_configuration_invalid",
    "managed_identity_missing",
    "safe_posture_invalid",
    "azure_cli_unavailable",
    "authentication_or_authorization_failed",
    "azure_request_failed",
    "response_parse_failed",
    "unexpected_error",
]
ConfigurationMode = Literal["check", "live"]

MESSAGES: dict[ConfigurationCategory, str] = {
    "success": "Web App configuration verification completed.",
    "missing_arguments": "Required Web App verification arguments are missing.",
    "web_app_not_found": "The requested Web App was not found.",
    "provisioning_incomplete": "Web App provisioning is not complete.",
    "runtime_contract_invalid": "The Linux runtime contract is invalid.",
    "startup_command_invalid": "The application startup command is invalid.",
    "remote_build_missing": "The remote-build setting is missing or disabled.",
    "security_configuration_invalid": "The Web App security configuration is invalid.",
    "managed_identity_missing": "A system-assigned managed identity is missing.",
    "safe_posture_invalid": "The hosted provider posture is not safe.",
    "azure_cli_unavailable": "Azure CLI is unavailable.",
    "authentication_or_authorization_failed": (
        "Azure authentication or authorization failed."
    ),
    "azure_request_failed": "The read-only Azure request failed.",
    "response_parse_failed": "The Azure response could not be parsed safely.",
    "unexpected_error": "Web App configuration verification did not complete.",
}

NEXT_STEPS: dict[ConfigurationCategory, str] = {
    "success": "Run the separate application code-deployment command.",
    "missing_arguments": "Supply both the resource group and Web App name.",
    "web_app_not_found": "Confirm the existing Web App name and resource group.",
    "provisioning_incomplete": "Wait for provisioning to succeed before verifying again.",
    "runtime_contract_invalid": "Review the Linux runtime against the Web App Bicep contract.",
    "startup_command_invalid": "Review the startup command against the Web App Bicep contract.",
    "remote_build_missing": "Enable the Bicep-owned remote-build setting before code deployment.",
    "security_configuration_invalid": "Review HTTPS, FTPS, TLS, and health-check configuration.",
    "managed_identity_missing": "Provision the Bicep-owned system-assigned identity before continuing.",
    "safe_posture_invalid": "Restore mock providers and suppressed notifications before continuing.",
    "azure_cli_unavailable": "Install Azure CLI before an explicit live verification.",
    "authentication_or_authorization_failed": (
        "Authenticate with least-privilege read access before verifying again."
    ),
    "azure_request_failed": "Review Azure access and retry only through explicit live mode.",
    "response_parse_failed": "Confirm Azure CLI returned the expected JSON shape.",
    "unexpected_error": "Review the sanitized category before explicitly verifying again.",
}
CHECK_NEXT_STEP = (
    "Run explicit --live --json Web App configuration verification after operator review."
)
LOCAL_CONTRACT_FAILURE_NEXT_STEP = (
    "Restore and review the application-owned local contract before live verification."
)


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class WebAppConfigurationVerificationResult:
    ok: bool
    mode: ConfigurationMode
    operation: str
    category: ConfigurationCategory
    message: str
    local_contract_validated: bool
    azure_request_attempted: bool
    web_app_present: bool
    provisioning_state_verified: bool
    linux_runtime_verified: bool
    startup_command_verified: bool
    remote_build_verified: bool
    https_only_verified: bool
    ftps_disabled_verified: bool
    minimum_tls_verified: bool
    health_check_verified: bool
    managed_identity_present: bool
    safe_provider_posture_verified: bool
    recommended_next_step: str

    @classmethod
    def check_success(cls) -> "WebAppConfigurationVerificationResult":
        return cls._create(
            "check",
            "success",
            ok=True,
            local_contract_validated=True,
            recommended_next_step=CHECK_NEXT_STEP,
        )

    @classmethod
    def live_success(cls) -> "WebAppConfigurationVerificationResult":
        return cls._create(
            "live",
            "success",
            ok=True,
            local_contract_validated=True,
            azure_request_attempted=True,
            web_app_present=True,
            provisioning_state_verified=True,
            linux_runtime_verified=True,
            startup_command_verified=True,
            remote_build_verified=True,
            https_only_verified=True,
            ftps_disabled_verified=True,
            minimum_tls_verified=True,
            health_check_verified=True,
            managed_identity_present=True,
            safe_provider_posture_verified=True,
        )

    @classmethod
    def local_contract_failure(
        cls,
        mode: ConfigurationMode,
    ) -> "WebAppConfigurationVerificationResult":
        return cls._create(
            mode,
            "unexpected_error",
            recommended_next_step=LOCAL_CONTRACT_FAILURE_NEXT_STEP,
        )

    @classmethod
    def failure(
        cls,
        category: ConfigurationCategory,
        **progress: bool,
    ) -> "WebAppConfigurationVerificationResult":
        return cls._create("live", category, **progress)

    @classmethod
    def _create(
        cls,
        mode: ConfigurationMode,
        category: ConfigurationCategory,
        *,
        ok: bool = False,
        local_contract_validated: bool = False,
        azure_request_attempted: bool = False,
        web_app_present: bool = False,
        provisioning_state_verified: bool = False,
        linux_runtime_verified: bool = False,
        startup_command_verified: bool = False,
        remote_build_verified: bool = False,
        https_only_verified: bool = False,
        ftps_disabled_verified: bool = False,
        minimum_tls_verified: bool = False,
        health_check_verified: bool = False,
        managed_identity_present: bool = False,
        safe_provider_posture_verified: bool = False,
        recommended_next_step: str | None = None,
    ) -> "WebAppConfigurationVerificationResult":
        return cls(
            ok=ok,
            mode=mode,
            operation="verify_web_app_configuration",
            category=category,
            message=MESSAGES[category],
            local_contract_validated=local_contract_validated,
            azure_request_attempted=azure_request_attempted,
            web_app_present=web_app_present,
            provisioning_state_verified=provisioning_state_verified,
            linux_runtime_verified=linux_runtime_verified,
            startup_command_verified=startup_command_verified,
            remote_build_verified=remote_build_verified,
            https_only_verified=https_only_verified,
            ftps_disabled_verified=ftps_disabled_verified,
            minimum_tls_verified=minimum_tls_verified,
            health_check_verified=health_check_verified,
            managed_identity_present=managed_identity_present,
            safe_provider_posture_verified=safe_provider_posture_verified,
            recommended_next_step=recommended_next_step or NEXT_STEPS[category],
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "operation": self.operation,
            "category": self.category,
            "message": self.message,
            "local_contract_validated": self.local_contract_validated,
            "azure_request_attempted": self.azure_request_attempted,
            "web_app_present": self.web_app_present,
            "provisioning_state_verified": self.provisioning_state_verified,
            "linux_runtime_verified": self.linux_runtime_verified,
            "startup_command_verified": self.startup_command_verified,
            "remote_build_verified": self.remote_build_verified,
            "https_only_verified": self.https_only_verified,
            "ftps_disabled_verified": self.ftps_disabled_verified,
            "minimum_tls_verified": self.minimum_tls_verified,
            "health_check_verified": self.health_check_verified,
            "managed_identity_present": self.managed_identity_present,
            "safe_provider_posture_verified": self.safe_provider_posture_verified,
            "recommended_next_step": self.recommended_next_step,
        }


def check_web_app_configuration_contract() -> WebAppConfigurationVerificationResult:
    if not _local_contract_valid():
        return WebAppConfigurationVerificationResult.local_contract_failure("check")
    return WebAppConfigurationVerificationResult.check_success()


def verify_web_app_configuration(
    resource_group: str | None,
    web_app_name: str | None,
    *,
    runner: AzureCliRunner,
) -> WebAppConfigurationVerificationResult:
    if not _nonempty(resource_group) or not _nonempty(web_app_name):
        return WebAppConfigurationVerificationResult.failure("missing_arguments")
    if not _local_contract_valid():
        return WebAppConfigurationVerificationResult.local_contract_failure("live")

    progress = {
        "local_contract_validated": True,
        "azure_request_attempted": False,
        "web_app_present": False,
        "provisioning_state_verified": False,
        "linux_runtime_verified": False,
        "startup_command_verified": False,
        "remote_build_verified": False,
        "https_only_verified": False,
        "ftps_disabled_verified": False,
        "minimum_tls_verified": False,
        "health_check_verified": False,
        "managed_identity_present": False,
        "safe_provider_posture_verified": False,
    }
    resource_group = resource_group.strip()
    web_app_name = web_app_name.strip()

    site, failure = _read_json(
        runner,
        [
            "az",
            "webapp",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            web_app_name,
            "--query",
            SITE_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
        allow_not_found=True,
    )
    progress["azure_request_attempted"] = True
    if failure:
        return WebAppConfigurationVerificationResult.failure(failure, **progress)
    if not isinstance(site, dict):
        return WebAppConfigurationVerificationResult.failure(
            "response_parse_failed", **progress
        )
    progress["web_app_present"] = True

    if site.get("state") != "Running" or site.get("enabled") is not True:
        return WebAppConfigurationVerificationResult.failure(
            "provisioning_incomplete", **progress
        )
    progress["provisioning_state_verified"] = True

    kind = site.get("kind")
    if (
        not isinstance(kind, str)
        or "linux" not in {part.strip().lower() for part in kind.split(",")}
        or site.get("reserved") is not True
    ):
        return WebAppConfigurationVerificationResult.failure(
            "runtime_contract_invalid", **progress
        )

    if site.get("httpsOnly") is not True:
        return WebAppConfigurationVerificationResult.failure(
            "security_configuration_invalid", **progress
        )
    progress["https_only_verified"] = True

    identity_type = site.get("identityType")
    if not isinstance(identity_type, str) or "SystemAssigned" not in {
        part.strip() for part in identity_type.split(",")
    }:
        return WebAppConfigurationVerificationResult.failure(
            "managed_identity_missing", **progress
        )
    progress["managed_identity_present"] = True

    config, failure = _read_json(
        runner,
        [
            "az",
            "webapp",
            "config",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            web_app_name,
            "--query",
            SITE_CONFIG_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
    )
    if failure:
        return WebAppConfigurationVerificationResult.failure(failure, **progress)
    if not isinstance(config, dict):
        return WebAppConfigurationVerificationResult.failure(
            "response_parse_failed", **progress
        )

    if config.get("linuxFxVersion") != EXPECTED_LINUX_FX_VERSION:
        return WebAppConfigurationVerificationResult.failure(
            "runtime_contract_invalid", **progress
        )
    progress["linux_runtime_verified"] = True

    if config.get("appCommandLine") != EXPECTED_STARTUP_COMMAND:
        return WebAppConfigurationVerificationResult.failure(
            "startup_command_invalid", **progress
        )
    progress["startup_command_verified"] = True

    if config.get("ftpsState") != "Disabled":
        return WebAppConfigurationVerificationResult.failure(
            "security_configuration_invalid", **progress
        )
    progress["ftps_disabled_verified"] = True

    if not (
        _tls_at_least_1_2(config.get("minTlsVersion"))
        and _tls_at_least_1_2(config.get("scmMinTlsVersion"))
    ):
        return WebAppConfigurationVerificationResult.failure(
            "security_configuration_invalid", **progress
        )
    progress["minimum_tls_verified"] = True

    if config.get("healthCheckPath") != EXPECTED_HEALTH_CHECK_PATH:
        return WebAppConfigurationVerificationResult.failure(
            "security_configuration_invalid", **progress
        )
    progress["health_check_verified"] = True

    settings_payload, failure = _read_json(
        runner,
        [
            "az",
            "webapp",
            "config",
            "appsettings",
            "list",
            "--resource-group",
            resource_group,
            "--name",
            web_app_name,
            "--query",
            APP_SETTINGS_QUERY,
            "--output",
            "json",
            "--only-show-errors",
        ],
    )
    if failure:
        return WebAppConfigurationVerificationResult.failure(failure, **progress)
    settings = _settings_dict(settings_payload)
    if settings is None:
        return WebAppConfigurationVerificationResult.failure(
            "response_parse_failed", **progress
        )

    if settings.get(REMOTE_BUILD_SETTING) != "true":
        return WebAppConfigurationVerificationResult.failure(
            "remote_build_missing", **progress
        )
    progress["remote_build_verified"] = True

    if any(settings.get(name) != value for name, value in SAFE_APP_SETTINGS.items()):
        return WebAppConfigurationVerificationResult.failure(
            "safe_posture_invalid", **progress
        )
    progress["safe_provider_posture_verified"] = True
    return WebAppConfigurationVerificationResult.live_success()


def _read_json(
    runner: AzureCliRunner,
    command: list[str],
    *,
    allow_not_found: bool = False,
) -> tuple[object | None, ConfigurationCategory | None]:
    try:
        result = runner.run(command)
    except Exception:
        return None, "unexpected_error"
    if result.return_code != 0:
        return None, _command_failure_category(result, allow_not_found=allow_not_found)
    try:
        return json.loads(result.stdout), None
    except (json.JSONDecodeError, TypeError):
        return None, "response_parse_failed"


def _command_failure_category(
    result: CommandResult,
    *,
    allow_not_found: bool,
) -> ConfigurationCategory:
    if result.return_code == 127:
        return "azure_cli_unavailable"
    lowered = result.stderr.lower()
    if any(
        marker in lowered
        for marker in (
            "az login",
            "authentication",
            "authorization",
            "unauthorized",
            "forbidden",
            "credential",
        )
    ):
        return "authentication_or_authorization_failed"
    if allow_not_found and any(
        marker in lowered
        for marker in ("resourcenotfound", "could not be found", "was not found")
    ):
        return "web_app_not_found"
    return "azure_request_failed"


def _settings_dict(payload: object) -> dict[str, str] | None:
    if not isinstance(payload, list):
        return None
    settings: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or not isinstance(value, str):
            return None
        settings[name] = value
    return settings


def _tls_at_least_1_2(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        major, minor = value.split(".", maxsplit=1)
        return (int(major), int(minor)) >= (1, 2)
    except (TypeError, ValueError):
        return False


def _nonempty(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _local_contract_valid() -> bool:
    return bool(
        EXPECTED_LINUX_FX_VERSION == EXPECTED_LOCAL_CONTRACT["linux_fx_version"]
        and EXPECTED_STARTUP_COMMAND == EXPECTED_LOCAL_CONTRACT["startup_command"]
        and EXPECTED_HEALTH_CHECK_PATH
        == EXPECTED_LOCAL_CONTRACT["health_check_path"]
        and SAFE_APP_SETTINGS == EXPECTED_SAFE_APP_SETTINGS
        and REMOTE_BUILD_SETTING == EXPECTED_LOCAL_CONTRACT["remote_build_setting"]
    )
