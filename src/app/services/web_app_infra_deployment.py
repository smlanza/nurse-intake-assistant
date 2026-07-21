from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Literal, Protocol

from src.app.services.web_app_hosting_contract import (
    HOSTED_VERIFIER_BICEP_PARAMETERS,
    REMOTE_BUILD_SETTING,
    REMOTE_BUILD_VALUE,
    SAFE_HOSTED_SETTINGS,
    hosted_verifier_foundry_identity,
    hosted_verifier_settings_valid,
)
from src.app.services.azure_what_if_evidence import (
    ExpectedWhatIfResource,
    SanitizedWhatIfChange,
    parse_sanitized_what_if,
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
    enable_hosted_foundry_verifier: bool = False
    hosted_verifier_project_endpoint: str | None = None
    hosted_verifier_stable_agent_endpoint: str | None = None
    hosted_verifier_agent_name: str | None = None
    hosted_verifier_agent_version: str | None = None
    hosted_verifier_model_deployment_name: str | None = None


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
    hosted_verifier_configuration_supplied: bool
    create_count: int | None
    modify_count: int | None
    delete_count: int | None
    no_change_count: int | None
    ignore_count: int | None
    deploy_count: int | None
    unsupported_count: int | None
    delete_detected: bool
    what_if_summary_available: bool
    exact_topology_match: bool
    recommended_next_step: str
    change_evidence: tuple[SanitizedWhatIfChange, ...]

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
            "hosted_verifier_configuration_supplied": (
                self.hosted_verifier_configuration_supplied
            ),
            "create_count": self.create_count,
            "modify_count": self.modify_count,
            "delete_count": self.delete_count,
            "no_change_count": self.no_change_count,
            "ignore_count": self.ignore_count,
            "deploy_count": self.deploy_count,
            "unsupported_count": self.unsupported_count,
            "delete_detected": self.delete_detected,
            "what_if_summary_available": self.what_if_summary_available,
            "exact_topology_match": self.exact_topology_match,
            "recommended_next_step": self.recommended_next_step,
            "change_evidence": [
                change.to_json_dict() for change in self.change_evidence
            ],
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
    change_evidence: tuple[SanitizedWhatIfChange, ...]
    exact_topology_match: bool


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
        hosted_verifier_configuration_supplied=(
            local_validation_passed and request.enable_hosted_foundry_verifier
        ),
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
        exact_topology_match=bool(
            what_if_summary and what_if_summary.exact_topology_match
        ),
        recommended_next_step=recommended_next_step,
        change_evidence=(what_if_summary.change_evidence if what_if_summary else ()),
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
        and _hosted_verifier_arguments_valid(request)
    )


def _hosted_verifier_settings(
    request: WebAppInfrastructureDeploymentRequest,
) -> dict[str, object]:
    return {
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": (
            request.hosted_verifier_project_endpoint
        ),
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": (
            request.hosted_verifier_stable_agent_endpoint
        ),
        "AZURE_AI_FOUNDRY_AGENT_NAME": request.hosted_verifier_agent_name,
        "AZURE_AI_FOUNDRY_AGENT_VERSION": request.hosted_verifier_agent_version,
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": (
            request.hosted_verifier_model_deployment_name
        ),
    }


def _hosted_verifier_arguments_valid(
    request: WebAppInfrastructureDeploymentRequest,
) -> bool:
    if not isinstance(request.enable_hosted_foundry_verifier, bool):
        return False
    values = _hosted_verifier_settings(request)
    if request.enable_hosted_foundry_verifier:
        return hosted_verifier_settings_valid(values)
    return all(value is None for value in values.values())


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
        r"\bappSettings\s*:\s*(?:concat\s*\(\s*)?\[",
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
            r"\s*name\s*:\s*'([^']+)'\s+value\s*:\s*"
            r"('(?:[^']|'')*'|[A-Za-z][A-Za-z0-9]*)\s*",
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
    safe_settings = {
        name: actual_settings.pop(name, None) for name in SAFE_HOSTED_SETTINGS
    }
    return (
        not actual_settings
        and safe_settings
        == {name: repr(value) for name, value in SAFE_HOSTED_SETTINGS.items()}
        and remote_build_value == repr(REMOTE_BUILD_VALUE)
    )


def _optional_hosted_verifier_contract_valid(module: str) -> bool:
    active = _strip_bicep_comments(module)
    if not re.search(
        r"var\s+hostedFoundryVerifierAppSettings\s*=\s*"
        r"validatedHostedFoundryVerifierConfiguration\.mode\s*==\s*'enabled'\s*\?\s*\[",
        active,
    ):
        return False
    if not re.search(
        r"appSettings\s*:\s*concat\s*\(\s*\[.*?\]\s*,\s*"
        r"hostedFoundryVerifierAppSettings\s*\)",
        active,
        re.DOTALL,
    ):
        return False
    for setting_name, property_name in HOSTED_VERIFIER_BICEP_PARAMETERS.items():
        if re.search(
            rf"name\s*:\s*'{re.escape(setting_name)}'\s+"
            rf"value\s*:\s*validatedHostedFoundryVerifierConfiguration\.{property_name}",
            active,
        ) is None:
            return False
    expected_names = {
        *SAFE_HOSTED_SETTINGS,
        REMOTE_BUILD_SETTING,
        *HOSTED_VERIFIER_BICEP_PARAMETERS,
    }
    return all(
        len(re.findall(rf"\bname\s*:\s*'{re.escape(name)}'", active)) == 1
        for name in expected_names
    )


def _module_local_hosted_verifier_validation_valid(
    module: str,
    validation_module: str,
) -> bool:
    active = _strip_bicep_comments(module)
    validation = _strip_bicep_comments(validation_module)
    if re.search(r"\bresource\s+[A-Za-z][A-Za-z0-9_]*\s+", validation):
        return False
    required_module_contract = (
        r"param\s+hostedFoundryVerifierConfiguration\s+"
        r"hostedFoundryVerifierConfigurationType\s*=\s*"
        r"\{\s*mode\s*:\s*'disabled'\s*\}",
        r"module\s+hostedFoundryVerifierConfigValidation\s+"
        r"'hosted-foundry-verifier-config-validation\.bicep'\s*=\s*"
        r"if\s*\(hostedFoundryVerifierConfiguration\.mode\s*==\s*'enabled'\)",
        r"hostedFoundryVerifierConfiguration\s*:\s*"
        r"validatedHostedFoundryVerifierConfiguration",
        r"dependsOn\s*:\s*\[\s*hostedFoundryVerifierConfigValidation\s*\]",
    )
    if any(
        re.search(pattern, active, re.DOTALL) is None
        for pattern in required_module_contract
    ):
        return False
    required_validation_contract = (
        r"@discriminator\('mode'\)",
        r"mode\s*:\s*'disabled'",
        r"mode\s*:\s*'enabled'",
        r"param\s+hostedFoundryVerifierConfiguration\s+"
        r"hostedFoundryVerifierConfigurationType",
    )
    if any(
        re.search(pattern, validation, re.DOTALL) is None
        for pattern in required_validation_contract
    ):
        return False
    for property_name in HOSTED_VERIFIER_BICEP_PARAMETERS.values():
        value = rf"hostedFoundryVerifierConfiguration\.{property_name}"
        if re.search(
            rf"{value}\s*==\s*trim\(\s*{value}\s*\)\s*\?\s*{value}\s*:\s*''",
            active,
        ) is None:
            return False
        if re.search(
            rf"@minLength\(1\)\s+{property_name}\s*:\s*string",
            validation,
        ) is None:
            return False
        if re.search(
            rf"value\s*:\s*hostedFoundryVerifierConfiguration\.{property_name}",
            active,
        ) is not None:
            return False
    return True


def _local_contract_valid(template_file: Path) -> bool:
    try:
        if not template_file.is_file():
            return False
        template = template_file.read_text()
        web_app_module = template_file.parent / "modules/web-app.bicep"
        if not web_app_module.is_file():
            return False
        module = web_app_module.read_text()
        validation_module_path = (
            template_file.parent
            / "modules/hosted-foundry-verifier-config-validation.bicep"
        )
        if not validation_module_path.is_file():
            return False
        validation_module = validation_module_path.read_text()
    except OSError:
        return False

    template_contract = (
        r"param\s+deployApp\s+bool\s*=\s*false",
        r"param\s+deployFoundry\s+bool\s*=\s*false",
        r"@minLength\(13\)\s*@maxLength\(13\)\s*param\s+resourceNameSuffix\s+string\?",
        r"var\s+suffix\s*=\s*resourceNameSuffix\s*\?\?\s*uniqueString\([^\r\n]+\)",
        r"module\s+webApp\s+'modules/web-app\.bicep'\s*=\s*if\s*\(deployApp\)",
    )
    if any(re.search(pattern, template) is None for pattern in template_contract):
        return False
    tagged_configuration_contract = (
        r"@discriminator\('mode'\)",
        r"mode\s*:\s*'disabled'",
        r"mode\s*:\s*'enabled'",
        r"param\s+hostedFoundryVerifierConfiguration\s+"
        r"hostedFoundryVerifierConfigurationType\s*=\s*\{\s*mode\s*:\s*'disabled'\s*\}",
        r"hostedFoundryVerifierConfiguration\s*:\s*"
        r"validatedHostedFoundryVerifierConfiguration",
    )
    if any(
        re.search(pattern, template, re.DOTALL) is None
        for pattern in tagged_configuration_contract
    ):
        return False
    for property_name in HOSTED_VERIFIER_BICEP_PARAMETERS.values():
        value = rf"hostedFoundryVerifierConfiguration\.{property_name}"
        if re.search(
            rf"{value}\s*==\s*trim\(\s*{value}\s*\)\s*\?\s*{value}\s*:\s*''",
            template,
        ) is None:
            return False
    return (
        _exact_hosted_settings_valid(module)
        and _optional_hosted_verifier_contract_valid(module)
        and _module_local_hosted_verifier_validation_valid(
            module,
            validation_module,
        )
    )


def web_app_infrastructure_local_contract_valid(template_file: Path) -> bool:
    """Expose the offline Bicep contract check for related operator boundaries."""

    return _local_contract_valid(template_file)


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
        command.extend(
            [
                "--no-pretty-print",
                "--result-format",
                "ResourceIdOnly",
                "--output",
                "json",
            ]
        )
    command.extend(
        [
            "--parameters",
            f"environmentName={request.environment_name}",
            f"location={request.location}",
            f"projectName={request.project_name}",
            f"cosmosDatabaseName={request.cosmos_database_name}",
            f"cosmosContainerName={request.cosmos_container_name}",
            f"resourceNameSuffix={_resource_name_suffix(request)}",
            "deployApp=true",
            "deployFoundry=false",
            f"webAppName={request.web_app_name}",
            "hostedFoundryVerifierConfiguration="
            + json.dumps(
                _hosted_verifier_bicep_configuration(request),
                separators=(",", ":"),
                sort_keys=True,
            ),
        ]
    )
    return command


def _hosted_verifier_bicep_configuration(
    request: WebAppInfrastructureDeploymentRequest,
) -> dict[str, str]:
    if not request.enable_hosted_foundry_verifier:
        return {"mode": "disabled"}
    settings = _hosted_verifier_settings(request)
    return {
        "mode": "enabled",
        **{
            property_name: str(settings[setting_name])
            for setting_name, property_name in HOSTED_VERIFIER_BICEP_PARAMETERS.items()
        },
    }


def _parse_what_if_summary(
    stdout: str,
    request: WebAppInfrastructureDeploymentRequest,
) -> WhatIfSummary | None:
    expected = _expected_web_app_resources(stdout, request)
    expected_ignored = _expected_web_app_foundry_references(request)
    additional_types = (
        {
            "Microsoft.CognitiveServices/accounts": "foundry_account_reference",
            "Microsoft.CognitiveServices/accounts/projects": (
                "foundry_project_reference"
            ),
        }
        if expected_ignored
        else {}
    )
    parsed = parse_sanitized_what_if(
        stdout,
        boundary="web_app",
        expected_resources=expected,
        sanitized_additional_resource_types=additional_types,
        expected_ignored_resources=expected_ignored or (),
        allow_expected_ignored_resources_absent=True,
        automatically_approved_actions=frozenset({"Create", "NoChange"}),
    )
    if parsed is None:
        return None
    return WhatIfSummary(
        create_count=parsed.count("Create"),
        modify_count=parsed.count("Modify"),
        delete_count=parsed.count("Delete"),
        no_change_count=parsed.count("NoChange"),
        ignore_count=parsed.count("Ignore"),
        deploy_count=parsed.count("Deploy"),
        unsupported_count=parsed.count("Unsupported"),
        change_evidence=parsed.changes,
        exact_topology_match=parsed.exact_topology_match,
    )


def _expected_web_app_foundry_references(
    request: WebAppInfrastructureDeploymentRequest,
) -> tuple[ExpectedWhatIfResource, ...] | None:
    if not request.enable_hosted_foundry_verifier:
        return ()
    identity = hosted_verifier_foundry_identity(_hosted_verifier_settings(request))
    if identity is None:
        return None
    account_name, project_name = identity
    return (
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts",
            "foundry_account_reference",
            request.resource_group,
            (account_name,),
        ),
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts/projects",
            "foundry_project_reference",
            request.resource_group,
            (account_name, project_name),
        ),
    )


def _expected_web_app_resources(
    _stdout: str,
    request: WebAppInfrastructureDeploymentRequest,
) -> tuple[ExpectedWhatIfResource, ...]:
    suffix = _resource_name_suffix(request)
    project_environment = f"{request.project_name}-{request.environment_name}"
    cosmos_account = f"{project_environment}-{suffix}".casefold()
    plan_name = f"{project_environment}-plan-{suffix}".casefold()[:40]
    expected = (
        (
            "Microsoft.DocumentDB/databaseAccounts",
            "cosmos_account",
            (cosmos_account,),
        ),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases",
            "cosmos_database",
            (cosmos_account, request.cosmos_database_name),
        ),
        (
            "Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers",
            "cosmos_container",
            (
                cosmos_account,
                request.cosmos_database_name,
                request.cosmos_container_name,
            ),
        ),
        ("Microsoft.Storage/storageAccounts", "storage_account", (f"st{suffix}",)),
        (
            "Microsoft.OperationalInsights/workspaces",
            "log_analytics",
            (f"{project_environment}-logs-{suffix}",),
        ),
        (
            "Microsoft.Insights/components",
            "application_insights",
            (f"{project_environment}-appi-{suffix}",),
        ),
        ("Microsoft.Web/serverfarms", "app_service_plan", (plan_name,)),
        ("Microsoft.Web/sites", "web_app", (request.web_app_name,)),
    )
    return tuple(
        ExpectedWhatIfResource(
            resource_type,
            category,
            request.resource_group,
            names,
        )
        for resource_type, category, names in expected
    )


def _resource_name_suffix(
    request: WebAppInfrastructureDeploymentRequest,
) -> str:
    identity = "\x00".join(
        (
            request.resource_group.casefold(),
            request.project_name.casefold(),
            request.environment_name.casefold(),
        )
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:13]


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
        summary = _parse_what_if_summary(outcome.stdout, request)
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
