from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Literal, Protocol

from src.app.services.web_app_hosting_contract import (
    REMOTE_BUILD_SETTING,
    REMOTE_BUILD_VALUE,
    SAFE_HOSTED_SETTINGS,
)


DeploymentMode = Literal["check", "what-if", "live"]
DeploymentCategory = Literal[
    "success",
    "invalid_arguments",
    "local_contract_invalid",
    "azure_cli_unavailable",
    "azure_operation_failed",
    "what_if_parse_failed",
    "unexpected_error",
]

FAILURE_MESSAGES: dict[DeploymentCategory, str] = {
    "success": "",
    "invalid_arguments": "Web App infrastructure arguments are invalid.",
    "local_contract_invalid": "The local Web App infrastructure contract is invalid.",
    "azure_cli_unavailable": "Azure CLI is unavailable.",
    "azure_operation_failed": "The Azure infrastructure operation failed.",
    "what_if_parse_failed": "The Azure infrastructure preview could not be summarized safely.",
    "unexpected_error": "The Web App infrastructure operation did not complete.",
}
SUCCESS_MESSAGES = {
    "check": "Local Web App infrastructure contract validation succeeded.",
    "what-if": "Azure Web App infrastructure preview completed.",
    "live": "Azure accepted the Web App infrastructure deployment request.",
}

FAILURE_NEXT_STEP = "Review the sanitized category and local inputs before retrying."


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class WebAppInfrastructureDeploymentRequest:
    mode: str
    resource_group: str
    location: str
    environment_name: str
    project_name: str
    web_app_name: str
    cosmos_database_name: str
    cosmos_container_name: str
    template_file: Path


@dataclass(frozen=True)
class WebAppInfrastructureDeploymentResult:
    ok: bool
    category: DeploymentCategory
    mode: str
    message: str
    resource_group: str | None
    web_app_name: str | None
    deployment_name: str | None
    local_validation_passed: bool
    azure_operation_attempted: bool
    what_if_attempted: bool
    deployment_attempted: bool
    deploy_app: bool
    deploy_foundry: bool
    create_count: int | None
    modify_count: int | None
    delete_count: int | None
    no_change_count: int | None
    ignore_count: int | None
    deploy_count: int | None
    unsupported_count: int | None
    delete_detected: bool
    what_if_summary_available: bool
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "mode": self.mode,
            "message": self.message,
            "resource_group": self.resource_group,
            "web_app_name": self.web_app_name,
            "deployment_name": self.deployment_name,
            "local_validation_passed": self.local_validation_passed,
            "azure_operation_attempted": self.azure_operation_attempted,
            "what_if_attempted": self.what_if_attempted,
            "deployment_attempted": self.deployment_attempted,
            "deploy_app": self.deploy_app,
            "deploy_foundry": self.deploy_foundry,
            "create_count": self.create_count,
            "modify_count": self.modify_count,
            "delete_count": self.delete_count,
            "no_change_count": self.no_change_count,
            "ignore_count": self.ignore_count,
            "deploy_count": self.deploy_count,
            "unsupported_count": self.unsupported_count,
            "delete_detected": self.delete_detected,
            "what_if_summary_available": self.what_if_summary_available,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class WhatIfSummary:
    create_count: int
    modify_count: int
    delete_count: int
    no_change_count: int
    ignore_count: int
    deploy_count: int
    unsupported_count: int


def _safe_result_identifier(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not _safe_argument(value, maximum=90)
        or re.fullmatch(r"[A-Za-z0-9_.()\-]+", value) is None
        or value.endswith(".")
    ):
        return None
    return value


def _deployment_name(request: WebAppInfrastructureDeploymentRequest) -> str | None:
    if not _safe_bicep_name(request.project_name, minimum=3, maximum=20):
        return None
    if not _safe_bicep_name(request.environment_name, minimum=3, maximum=10):
        return None
    return f"{request.project_name}-{request.environment_name}-web-app-infra"


def _result(
    request: WebAppInfrastructureDeploymentRequest,
    category: DeploymentCategory,
    *,
    ok: bool = False,
    local_validation_passed: bool = False,
    azure_operation_attempted: bool = False,
    what_if_attempted: bool = False,
    deployment_attempted: bool = False,
    what_if_summary: WhatIfSummary | None = None,
    recommended_next_step: str = FAILURE_NEXT_STEP,
) -> WebAppInfrastructureDeploymentResult:
    mode = request.mode if request.mode in {"check", "what-if", "live"} else "invalid"
    message = (
        SUCCESS_MESSAGES[mode]
        if category == "success" and mode in SUCCESS_MESSAGES
        else FAILURE_MESSAGES[category]
    )
    return WebAppInfrastructureDeploymentResult(
        ok=ok,
        category=category,
        mode=mode,
        message=message,
        resource_group=_safe_result_identifier(request.resource_group),
        web_app_name=(
            request.web_app_name
            if _safe_bicep_name(request.web_app_name, minimum=2, maximum=60)
            else None
        ),
        deployment_name=_deployment_name(request),
        local_validation_passed=local_validation_passed,
        azure_operation_attempted=azure_operation_attempted,
        what_if_attempted=what_if_attempted,
        deployment_attempted=deployment_attempted,
        deploy_app=True,
        deploy_foundry=False,
        create_count=(what_if_summary.create_count if what_if_summary else None),
        modify_count=(what_if_summary.modify_count if what_if_summary else None),
        delete_count=(what_if_summary.delete_count if what_if_summary else None),
        no_change_count=(what_if_summary.no_change_count if what_if_summary else None),
        ignore_count=(what_if_summary.ignore_count if what_if_summary else None),
        deploy_count=(what_if_summary.deploy_count if what_if_summary else None),
        unsupported_count=(
            what_if_summary.unsupported_count if what_if_summary else None
        ),
        delete_detected=(
            what_if_summary is not None and what_if_summary.delete_count > 0
        ),
        what_if_summary_available=what_if_summary is not None,
        recommended_next_step=recommended_next_step,
    )


def _safe_argument(value: object, *, maximum: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum
        and not value.startswith("-")
        and not any(character in value for character in "\x00\r\n\t")
    )


def _safe_bicep_name(value: object, *, minimum: int, maximum: int) -> bool:
    return (
        _safe_argument(value, maximum=maximum)
        and isinstance(value, str)
        and len(value) >= minimum
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", value)
        is not None
    )


def _arguments_valid(request: WebAppInfrastructureDeploymentRequest) -> bool:
    return (
        request.mode in {"check", "what-if", "live"}
        and _safe_argument(request.resource_group, maximum=90)
        and re.fullmatch(r"[A-Za-z0-9_.()\-]+", request.resource_group) is not None
        and not request.resource_group.endswith(".")
        and _safe_argument(request.location, maximum=90)
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9 ._-]*[A-Za-z0-9])?", request.location)
        is not None
        and _safe_bicep_name(request.environment_name, minimum=3, maximum=10)
        and _safe_bicep_name(request.project_name, minimum=3, maximum=20)
        and _safe_bicep_name(request.web_app_name, minimum=2, maximum=60)
        and _safe_argument(request.cosmos_database_name, maximum=255)
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9 ._-]*[A-Za-z0-9])?", request.cosmos_database_name)
        is not None
        and _safe_argument(request.cosmos_container_name, maximum=255)
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9 ._-]*[A-Za-z0-9])?", request.cosmos_container_name)
        is not None
    )


def _strip_bicep_comments(text: str) -> str:
    output: list[str] = []
    index = 0
    in_string = False
    in_line_comment = False
    block_comment_depth = 0
    while index < len(text):
        current = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_line_comment:
            if current == "\n":
                in_line_comment = False
                output.append(current)
            else:
                output.append(" ")
            index += 1
            continue
        if block_comment_depth:
            if current == "/" and following == "*":
                block_comment_depth += 1
                output.extend((" ", " "))
                index += 2
            elif current == "*" and following == "/":
                block_comment_depth -= 1
                output.extend((" ", " "))
                index += 2
            else:
                output.append("\n" if current == "\n" else " ")
                index += 1
            continue
        if in_string:
            output.append(current)
            if current == "'":
                if following == "'":
                    output.append(following)
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if current == "'":
            in_string = True
            output.append(current)
            index += 1
        elif current == "/" and following == "/":
            in_line_comment = True
            output.extend((" ", " "))
            index += 2
        elif current == "/" and following == "*":
            block_comment_depth = 1
            output.extend((" ", " "))
            index += 2
        else:
            output.append(current)
            index += 1
    return "".join(output)


def _delimited_body(
    text: str,
    opening_index: int,
    opening: str,
    closing: str,
) -> tuple[str, int] | None:
    if opening_index >= len(text) or text[opening_index] != opening:
        return None
    depth = 0
    in_string = False
    index = opening_index
    while index < len(text):
        current = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            if current == "'":
                if following == "'":
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if current == "'":
            in_string = True
        elif current == opening:
            depth += 1
        elif current == closing:
            depth -= 1
            if depth == 0:
                return text[opening_index + 1 : index], index + 1
        index += 1
    return None


def _body_after_pattern(
    text: str,
    pattern: str,
    opening: str,
    closing: str,
) -> str | None:
    match = re.search(pattern, text)
    if match is None:
        return None
    opening_index = text.find(opening, match.start(), match.end())
    if opening_index < 0:
        return None
    extracted = _delimited_body(text, opening_index, opening, closing)
    return extracted[0] if extracted else None


def _app_settings_entries(module: str) -> list[tuple[str, str]] | None:
    active = _strip_bicep_comments(module)
    web_app = _body_after_pattern(
        active,
        r"resource\s+webApp\s+'Microsoft\.Web/sites@[^']+'\s*=\s*\{",
        "{",
        "}",
    )
    if web_app is None:
        return None
    site_config = _body_after_pattern(
        web_app,
        r"\bsiteConfig\s*:\s*\{",
        "{",
        "}",
    )
    if site_config is None:
        return None
    app_settings = _body_after_pattern(
        site_config,
        r"\bappSettings\s*:\s*\[",
        "[",
        "]",
    )
    if app_settings is None:
        return None

    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(app_settings):
        while index < len(app_settings) and (
            app_settings[index].isspace() or app_settings[index] == ","
        ):
            index += 1
        if index == len(app_settings):
            break
        if app_settings[index] != "{":
            return None
        extracted = _delimited_body(app_settings, index, "{", "}")
        if extracted is None:
            return None
        entry_body, index = extracted
        fields = re.fullmatch(
            r"\s*name\s*:\s*'([^']+)'\s+value\s*:\s*'([^']*)'\s*",
            entry_body,
        )
        if fields is None:
            return None
        entries.append((fields.group(1), fields.group(2)))
    return entries


def _exact_hosted_settings_valid(module: str) -> bool:
    entries = _app_settings_entries(module)
    if entries is None:
        return False
    names = [name for name, _value in entries]
    if len(names) != len(set(names)):
        return False
    actual_settings = dict(entries)
    remote_build_value = actual_settings.pop(REMOTE_BUILD_SETTING, None)
    return (
        actual_settings == SAFE_HOSTED_SETTINGS
        and remote_build_value == REMOTE_BUILD_VALUE
    )


def _local_contract_valid(template_file: Path) -> bool:
    try:
        if not template_file.is_file():
            return False
        template = template_file.read_text()
        web_app_module = template_file.parent / "modules/web-app.bicep"
        if not web_app_module.is_file():
            return False
        module = web_app_module.read_text()
    except OSError:
        return False

    template_contract = (
        r"param\s+deployApp\s+bool\s*=\s*false",
        r"param\s+deployFoundry\s+bool\s*=\s*false",
        r"module\s+webApp\s+'modules/web-app\.bicep'\s*=\s*if\s*\(deployApp\)",
    )
    if any(re.search(pattern, template) is None for pattern in template_contract):
        return False
    return _exact_hosted_settings_valid(module)


def validate_web_app_infrastructure_request(
    request: WebAppInfrastructureDeploymentRequest,
) -> WebAppInfrastructureDeploymentResult | None:
    if not _arguments_valid(request):
        return _result(request, "invalid_arguments")
    if not _local_contract_valid(request.template_file):
        return _result(request, "local_contract_invalid")
    return None


def _azure_command(request: WebAppInfrastructureDeploymentRequest) -> list[str]:
    operation = "what-if" if request.mode == "what-if" else "create"
    command = [
        "az",
        "deployment",
        "group",
        operation,
        "--resource-group",
        request.resource_group,
    ]
    if request.mode == "live":
        command.extend(["--name", _deployment_name(request) or ""])
    command.extend(["--template-file", str(request.template_file)])
    if request.mode == "what-if":
        command.extend(["--output", "json"])
    command.extend(
        [
            "--parameters",
            f"environmentName={request.environment_name}",
            f"location={request.location}",
            f"projectName={request.project_name}",
            f"cosmosDatabaseName={request.cosmos_database_name}",
            f"cosmosContainerName={request.cosmos_container_name}",
            "deployApp=true",
            "deployFoundry=false",
            f"webAppName={request.web_app_name}",
        ]
    )
    return command


def _parse_what_if_summary(stdout: str) -> WhatIfSummary | None:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("changes"), list):
        return None

    counts = {
        "create": 0,
        "modify": 0,
        "delete": 0,
        "nochange": 0,
        "ignore": 0,
        "deploy": 0,
        "unsupported": 0,
    }
    for change in payload["changes"]:
        if not isinstance(change, dict):
            return None
        change_type = change.get("changeType")
        if not isinstance(change_type, str) or not change_type.strip():
            return None
        normalized = change_type.strip().casefold()
        counts[normalized if normalized in counts else "unsupported"] += 1
    return WhatIfSummary(
        create_count=counts["create"],
        modify_count=counts["modify"],
        delete_count=counts["delete"],
        no_change_count=counts["nochange"],
        ignore_count=counts["ignore"],
        deploy_count=counts["deploy"],
        unsupported_count=counts["unsupported"],
    )


def deploy_web_app_infrastructure(
    request: WebAppInfrastructureDeploymentRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> WebAppInfrastructureDeploymentResult:
    invalid = validate_web_app_infrastructure_request(request)
    if invalid is not None:
        return invalid
    if request.mode == "check":
        return _result(
            request,
            "success",
            ok=True,
            local_validation_passed=True,
            recommended_next_step=(
                "Review the contract, then explicitly run --what-if against an existing resource group."
            ),
        )
    if runner is None:
        return _result(
            request,
            "unexpected_error",
            local_validation_passed=True,
        )

    what_if_attempted = request.mode == "what-if"
    deployment_attempted = request.mode == "live"
    try:
        outcome = runner.run(_azure_command(request))
    except Exception:
        return _result(
            request,
            "unexpected_error",
            local_validation_passed=True,
            azure_operation_attempted=True,
            what_if_attempted=what_if_attempted,
            deployment_attempted=deployment_attempted,
        )

    common = {
        "local_validation_passed": True,
        "azure_operation_attempted": True,
        "what_if_attempted": what_if_attempted,
        "deployment_attempted": deployment_attempted,
    }
    if outcome.return_code == 127:
        return _result(request, "azure_cli_unavailable", **common)
    if outcome.return_code != 0:
        return _result(request, "azure_operation_failed", **common)
    if request.mode == "what-if":
        summary = _parse_what_if_summary(outcome.stdout)
        if summary is None:
            return _result(request, "what_if_parse_failed", **common)
        if summary.delete_count:
            next_step = (
                "Review proposed deletions manually before any separate explicit --live deployment."
            )
        else:
            next_step = (
                "Review the sanitized preview before any separate explicit --live deployment."
            )
        return _result(
            request,
            "success",
            ok=True,
            what_if_summary=summary,
            recommended_next_step=next_step,
            **common,
        )
    return _result(
        request,
        "success",
        ok=True,
        recommended_next_step=(
            "Run scripts/verify_web_app_configuration.py separately against the deployed Web App."
        ),
        **common,
    )
