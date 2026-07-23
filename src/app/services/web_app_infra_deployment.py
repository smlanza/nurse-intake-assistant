from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path
import re
from typing import Literal, Protocol

from src.app.services.web_app_hosting_contract import (
    ALWAYS_ON_REQUIRED,
    BASELINE_APP_SETTINGS,
    HOSTED_VERIFIER_BICEP_PARAMETERS,
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
DeploymentPurpose = Literal[
    "initial_create",
    "existing_web_app_reconciliation",
]
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
    purpose: str = "initial_create"


@dataclass(frozen=True)
class WebAppInfrastructureDeploymentResult:
    ok: bool
    category: DeploymentCategory
    mode: str
    purpose: str
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
            "purpose": self.purpose,
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
    suffix = (
        "web-app-reconciliation"
        if request.purpose == "existing_web_app_reconciliation"
        else "web-app-infra"
    )
    return f"{request.project_name}-{request.environment_name}-{suffix}"


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
        purpose=(
            request.purpose
            if request.purpose
            in {"initial_create", "existing_web_app_reconciliation"}
            else "invalid"
        ),
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
    expected_template_name = {
        "initial_create": "main.bicep",
        "existing_web_app_reconciliation": "web-app.bicep",
    }.get(request.purpose)
    return (
        request.mode in {"check", "what-if", "live"}
        and expected_template_name is not None
        and request.template_file.name == expected_template_name
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


def _positions_outside_strings(text: str) -> tuple[bool, ...]:
    outside: list[bool] = []
    in_string = False
    index = 0
    while index < len(text):
        current = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        outside.append(not in_string)
        if in_string and current == "'":
            if following == "'":
                outside.append(False)
                index += 2
                continue
            in_string = False
        elif not in_string and current == "'":
            in_string = True
        index += 1
    return tuple(outside)


def _active_resource_declarations(
    active_module: str,
) -> tuple[tuple[str, str, str], ...] | None:
    outside_strings = _positions_outside_strings(active_module)
    declarations: list[tuple[str, str, str]] = []
    pattern = re.compile(
        r"(?m)^\s*resource\s+([A-Za-z][A-Za-z0-9_]*)\s+"
        r"'([^']+)'\s*(?:existing\s*)?="
    )
    for match in pattern.finditer(active_module):
        if not outside_strings[match.start()]:
            continue
        cursor = match.end()
        while cursor < len(active_module) and active_module[cursor].isspace():
            cursor += 1
        if re.match(r"if\b", active_module[cursor:]):
            cursor += 2
            while cursor < len(active_module) and active_module[cursor].isspace():
                cursor += 1
            if cursor >= len(active_module) or active_module[cursor] != "(":
                return None
            condition = _delimited_body(active_module, cursor, "(", ")")
            if condition is None:
                return None
            _condition_body, cursor = condition
            while cursor < len(active_module) and active_module[cursor].isspace():
                cursor += 1
        if cursor >= len(active_module) or active_module[cursor] != "{":
            return None
        extracted = _delimited_body(active_module, cursor, "{", "}")
        if extracted is None:
            return None
        body, _end = extracted
        declarations.append((match.group(1), match.group(2), body))
    return tuple(declarations)


def _active_web_app_site_config(module: str) -> str | None:
    active = _strip_bicep_comments(module)
    web_app = _active_web_app_resource_body(active)
    if web_app is None:
        return None
    properties = _body_after_pattern(
        web_app,
        r"(?m)^\s*properties\s*:\s*\{",
        "{",
        "}",
    )
    if properties is None:
        return None
    return _body_after_pattern(
        properties,
        r"(?m)^\s*siteConfig\s*:\s*\{",
        "{",
        "}",
    )


def _active_web_app_resource_body(active_module: str) -> str | None:
    return _body_after_pattern(
        active_module,
        r"(?m)^\s*resource\s+webApp\s+"
        r"'Microsoft\.Web/sites@2024-04-01'\s*=\s*\{",
        "{",
        "}",
    )


def _top_level_visible(body: str) -> str:
    visible: list[str] = []
    depth = 0
    in_string = False
    index = 0
    while index < len(body):
        current = body[index]
        following = body[index + 1] if index + 1 < len(body) else ""
        if in_string:
            visible.append(current if depth == 0 else "\n" if current == "\n" else " ")
            if current == "'":
                if following == "'":
                    visible.append(following if depth == 0 else " ")
                    index += 2
                    continue
                in_string = False
            index += 1
            continue
        if current == "'":
            in_string = True
            visible.append(current if depth == 0 else " ")
        elif current in "{[(":
            visible.append(" ")
            depth += 1
        elif current in "}])":
            depth = max(depth - 1, 0)
            visible.append(" ")
        else:
            visible.append(current if depth == 0 else "\n" if current == "\n" else " ")
        index += 1
    return "".join(visible)


def _top_level_property_names(body: str) -> tuple[str, ...]:
    return tuple(
        re.findall(
            r"(?m)^\s*([A-Za-z][A-Za-z0-9_]*)\s*:",
            _top_level_visible(body),
        )
    )


def _top_level_scalar_values(body: str, name: str) -> list[str]:
    return re.findall(
        rf"(?m)^\s*{re.escape(name)}\s*:\s*(\S(?:.*\S)?)\s*$",
        _top_level_visible(body),
    )


def _top_level_property_expression(body: str, name: str) -> str | None:
    visible = _top_level_visible(body)
    declarations = tuple(
        re.finditer(
            r"(?m)^\s*([A-Za-z][A-Za-z0-9_]*)\s*:",
            visible,
        )
    )
    matching = tuple(
        index
        for index, declaration in enumerate(declarations)
        if declaration.group(1) == name
    )
    if len(matching) != 1:
        return None
    declaration_index = matching[0]
    start = declarations[declaration_index].end()
    end = (
        declarations[declaration_index + 1].start()
        if declaration_index + 1 < len(declarations)
        else len(body)
    )
    return body[start:end].strip()


def _exact_top_level_properties(
    body: str,
    expected: tuple[str, ...],
) -> bool:
    visible = _top_level_visible(body)
    declarations_only = all(
        re.fullmatch(
            r"\s*[A-Za-z][A-Za-z0-9_]*\s*:(?:\s*\S.*)?\s*",
            line,
        )
        is not None
        for line in visible.splitlines()
        if line.strip()
    )
    actual = _top_level_property_names(body)
    return bool(
        declarations_only
        and len(actual) == len(expected)
        and set(actual) == set(expected)
    )


def _exact_top_level_scalar(body: str, name: str, expected: str) -> bool:
    return _top_level_scalar_values(body, name) == [expected]


def _complete_active_web_app_resource_contract_valid(module: str) -> bool:
    active = _strip_bicep_comments(module)
    declarations = _active_resource_declarations(active)
    if declarations is None:
        return False
    if [
        (symbol, resource_type)
        for symbol, resource_type, _body in declarations
        if resource_type.split("@", 1)[0].casefold().startswith(
            "microsoft.web/sites"
        )
    ] != [("webApp", "Microsoft.Web/sites@2024-04-01")]:
        return False
    if any(
        symbol != "webApp"
        and _top_level_property_expression(body, "parent") == "webApp"
        for symbol, _resource_type, body in declarations
    ):
        return False
    web_app = _active_web_app_resource_body(active)
    if web_app is None or not _exact_top_level_properties(
        web_app,
        ("name", "location", "kind", "identity", "properties", "tags", "dependsOn"),
    ):
        return False
    identity = _body_after_pattern(
        web_app,
        r"(?m)^\s*identity\s*:\s*\{",
        "{",
        "}",
    )
    properties = _body_after_pattern(
        web_app,
        r"(?m)^\s*properties\s*:\s*\{",
        "{",
        "}",
    )
    depends_on = _body_after_pattern(
        web_app,
        r"(?m)^\s*dependsOn\s*:\s*\[",
        "[",
        "]",
    )
    if (
        identity is None
        or properties is None
        or depends_on is None
        or not _exact_top_level_properties(identity, ("type",))
        or not _exact_top_level_properties(
            properties,
            ("serverFarmId", "httpsOnly", "siteConfig"),
        )
    ):
        return False
    site_config = _body_after_pattern(
        properties,
        r"(?m)^\s*siteConfig\s*:\s*\{",
        "{",
        "}",
    )
    if site_config is None or not _exact_top_level_properties(
        site_config,
        (
            "linuxFxVersion",
            "appCommandLine",
            "alwaysOn",
            "ftpsState",
            "minTlsVersion",
            "scmMinTlsVersion",
            "healthCheckPath",
            "appSettings",
        ),
    ):
        return False
    exact_scalars = (
        (web_app, "name", "webAppName"),
        (web_app, "location", "location"),
        (web_app, "kind", "'app,linux'"),
        (web_app, "tags", "tags"),
        (identity, "type", "'SystemAssigned'"),
        (
            properties,
            "serverFarmId",
            "resolvedAppServicePlanResourceId",
        ),
        (properties, "httpsOnly", "true"),
        (site_config, "linuxFxVersion", "pythonLinuxFxVersion"),
        (site_config, "appCommandLine", "startupCommand"),
        (site_config, "alwaysOn", "true"),
        (site_config, "ftpsState", "'Disabled'"),
        (site_config, "minTlsVersion", "'1.2'"),
        (site_config, "scmMinTlsVersion", "'1.2'"),
        (site_config, "healthCheckPath", "'/health'"),
    )
    return bool(
        all(
            _exact_top_level_scalar(body, name, value)
            for body, name, value in exact_scalars
        )
        and "".join(depends_on.split())
        == "hostedFoundryVerifierConfigValidation"
    )


def _top_level_property_values(body: str, name: str) -> list[str]:
    return re.findall(
        rf"(?m)^\s*{re.escape(name)}\s*:\s*([A-Za-z]+)\s*$",
        _top_level_visible(body),
    )


def _site_config_always_on_valid(module: str) -> bool:
    site_config = _active_web_app_site_config(module)
    if site_config is None:
        return False
    expected = "true" if ALWAYS_ON_REQUIRED else "false"
    return _top_level_property_values(site_config, "alwaysOn") == [expected]


def _split_top_level_arguments(body: str) -> tuple[str, ...] | None:
    arguments: list[str] = []
    stack: list[str] = []
    matching = {")": "(", "]": "[", "}": "{"}
    in_string = False
    start = 0
    index = 0
    while index < len(body):
        current = body[index]
        following = body[index + 1] if index + 1 < len(body) else ""
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
        elif current in "([{":
            stack.append(current)
        elif current in ")]}":
            if not stack or stack.pop() != matching[current]:
                return None
        elif current == "," and not stack:
            arguments.append(body[start:index].strip())
            start = index + 1
        index += 1
    if in_string or stack:
        return None
    arguments.append(body[start:].strip())
    return tuple(arguments)


def _authoritative_app_settings_array(module: str) -> str | None:
    site_config = _active_web_app_site_config(module)
    if site_config is None:
        return None
    expression = _top_level_property_expression(site_config, "appSettings")
    if expression is None:
        return None
    concat_match = re.match(r"concat\s*\(", expression)
    if concat_match is None:
        return None
    opening_index = expression.find("(", 0, concat_match.end())
    extracted = _delimited_body(expression, opening_index, "(", ")")
    if extracted is None:
        return None
    argument_body, expression_end = extracted
    if expression[expression_end:].strip():
        return None
    arguments = _split_top_level_arguments(argument_body)
    if (
        arguments is None
        or len(arguments) != 2
        or arguments[1] != "hostedFoundryVerifierAppSettings"
    ):
        return None
    baseline = arguments[0]
    if not baseline.startswith("["):
        return None
    baseline_extracted = _delimited_body(baseline, 0, "[", "]")
    if baseline_extracted is None:
        return None
    baseline_body, baseline_end = baseline_extracted
    if baseline[baseline_end:].strip():
        return None
    return baseline_body


def _app_settings_entries(module: str) -> list[tuple[str, str]] | None:
    app_settings = _authoritative_app_settings_array(module)
    if app_settings is None:
        return None
    return _setting_entries(
        app_settings,
        r"'(?:[^']|'')*'|[A-Za-z][A-Za-z0-9]*",
    )


def _setting_entries(
    array_body: str,
    value_pattern: str,
) -> list[tuple[str, str]] | None:
    entries: list[tuple[str, str]] = []
    index = 0
    while index < len(array_body):
        while index < len(array_body) and (
            array_body[index].isspace() or array_body[index] == ","
        ):
            index += 1
        if index == len(array_body):
            break
        if array_body[index] != "{":
            return None
        extracted = _delimited_body(array_body, index, "{", "}")
        if extracted is None:
            return None
        entry_body, index = extracted
        fields = re.fullmatch(
            r"\s*name\s*:\s*'([^']+)'\s+value\s*:\s*"
            rf"({value_pattern})\s*",
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
    return actual_settings == {
        name: repr(value) for name, value in BASELINE_APP_SETTINGS.items()
    }


def _optional_hosted_verifier_contract_valid(module: str) -> bool:
    active = _strip_bicep_comments(module)
    visible = _top_level_visible(active)
    outside_strings = _positions_outside_strings(active)
    optional_matches = tuple(
        match
        for match in re.finditer(
            r"(?m)^\s*var\s+hostedFoundryVerifierAppSettings\s*=",
            visible,
        )
        if outside_strings[match.start()]
    )
    if len(optional_matches) != 1:
        return False
    cursor = optional_matches[0].end()
    condition = re.match(
        r"\s*validatedHostedFoundryVerifierConfiguration\.mode\s*"
        r"==\s*'enabled'\s*\?\s*",
        active[cursor:],
    )
    if condition is None:
        return False
    cursor += condition.end()
    if cursor >= len(active) or active[cursor] != "[":
        return False
    extracted = _delimited_body(active, cursor, "[", "]")
    if extracted is None:
        return False
    optional_body, cursor = extracted
    false_branch = re.match(r"\s*:\s*", active[cursor:])
    if false_branch is None:
        return False
    cursor += false_branch.end()
    if cursor >= len(active) or active[cursor] != "[":
        return False
    empty_branch = _delimited_body(active, cursor, "[", "]")
    if empty_branch is None:
        return False
    empty_body, cursor = empty_branch
    if empty_body.strip() or re.match(
        r"[ \t]*(?:\r?\n|$)",
        active[cursor:],
    ) is None:
        return False
    optional_entries = _setting_entries(
        optional_body,
        r"validatedHostedFoundryVerifierConfiguration\.[A-Za-z][A-Za-z0-9]*",
    )
    if optional_entries is None or dict(optional_entries) != {
        setting_name: f"validatedHostedFoundryVerifierConfiguration.{property_name}"
        for setting_name, property_name in HOSTED_VERIFIER_BICEP_PARAMETERS.items()
    } or len(optional_entries) != len(HOSTED_VERIFIER_BICEP_PARAMETERS):
        return False
    return True


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


def _app_service_plan_selection_contract_valid(
    module: str,
    *,
    exact_deployment_boundary: bool,
) -> bool:
    active = _strip_bicep_comments(module)
    declarations = _active_resource_declarations(active)
    if declarations is None:
        return False
    if exact_deployment_boundary:
        if [
            (symbol, resource_type)
            for symbol, resource_type, _body in declarations
        ] != [
            ("appServicePlan", "Microsoft.Web/serverfarms@2024-04-01"),
            ("existingAppServicePlan", "Microsoft.Web/serverfarms@2024-04-01"),
            ("webApp", "Microsoft.Web/sites@2024-04-01"),
        ]:
            return False
        outside_strings = _positions_outside_strings(active)
        modules = tuple(
            (match.group(1), match.group(2))
            for match in re.finditer(
                r"(?m)^\s*module\s+([A-Za-z][A-Za-z0-9_]*)\s+'([^']+)'\s*=",
                active,
            )
            if outside_strings[match.start()]
        )
        if modules != (
            (
                "hostedFoundryVerifierConfigValidation",
                "hosted-foundry-verifier-config-validation.bicep",
            ),
        ):
            return False
    required = (
        r"param\s+deployAppServicePlan\s+bool\s*=\s*true",
        r"resource\s+appServicePlan\s+"
        r"'Microsoft\.Web/serverfarms@2024-04-01'\s*=\s*"
        r"if\s*\(\s*deployAppServicePlan\s*\)",
        r"resource\s+existingAppServicePlan\s+"
        r"'Microsoft\.Web/serverfarms@2024-04-01'\s+existing\s*=\s*"
        r"\{\s*name\s*:\s*appServicePlanName\s*\}",
        r"var\s+resolvedAppServicePlanResourceId\s*=\s*"
        r"deployAppServicePlan\s*\?\s*appServicePlan!\.id\s*:\s*"
        r"existingAppServicePlan\.id",
    )
    return all(re.search(pattern, active, re.DOTALL) is not None for pattern in required)


def _local_contract_valid(
    template_file: Path,
    purpose: str = "initial_create",
) -> bool:
    try:
        if not template_file.is_file():
            return False
        if purpose == "initial_create":
            template = template_file.read_text()
            web_app_module = template_file.parent / "modules/web-app.bicep"
            validation_module_path = (
                template_file.parent
                / "modules/hosted-foundry-verifier-config-validation.bicep"
            )
        elif purpose == "existing_web_app_reconciliation":
            template = ""
            web_app_module = template_file
            validation_module_path = (
                template_file.parent
                / "hosted-foundry-verifier-config-validation.bicep"
            )
        else:
            return False
        if not web_app_module.is_file():
            return False
        module = web_app_module.read_text()
        if not validation_module_path.is_file():
            return False
        validation_module = validation_module_path.read_text()
    except OSError:
        return False

    if purpose == "initial_create":
        template_contract = (
            r"param\s+deployApp\s+bool\s*=\s*false",
            r"param\s+deployFoundry\s+bool\s*=\s*false",
            r"@minLength\(13\)\s*@maxLength\(13\)\s*param\s+resourceNameSuffix\s+string\?",
            r"var\s+suffix\s*=\s*resourceNameSuffix\s*\?\?\s*uniqueString\([^\r\n]+\)",
            r"module\s+webApp\s+'modules/web-app\.bicep'\s*=\s*if\s*\(deployApp\)",
        )
        if any(
            re.search(pattern, template) is None
            for pattern in template_contract
        ):
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
    elif purpose != "existing_web_app_reconciliation":
        return False
    return (
        _complete_active_web_app_resource_contract_valid(module)
        and _app_service_plan_selection_contract_valid(
            module,
            exact_deployment_boundary=(
                purpose == "existing_web_app_reconciliation"
            ),
        )
        and _site_config_always_on_valid(module)
        and _exact_hosted_settings_valid(module)
        and _optional_hosted_verifier_contract_valid(module)
        and _module_local_hosted_verifier_validation_valid(
            module,
            validation_module,
        )
    )


def web_app_infrastructure_local_contract_valid(
    template_file: Path,
    purpose: str = "initial_create",
) -> bool:
    """Expose the offline Bicep contract check for related operator boundaries."""

    return _local_contract_valid(template_file, purpose)


def validate_web_app_infrastructure_request(
    request: WebAppInfrastructureDeploymentRequest,
) -> WebAppInfrastructureDeploymentResult | None:
    if not _arguments_valid(request):
        return _result(request, "invalid_arguments")
    if not _local_contract_valid(request.template_file, request.purpose):
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
    hosted_configuration = (
        "hostedFoundryVerifierConfiguration="
        + json.dumps(
            _hosted_verifier_bicep_configuration(request),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    if request.purpose == "existing_web_app_reconciliation":
        parameters = [
            f"location={request.location}",
            f"appServicePlanName={_app_service_plan_name(request)}",
            f"webAppName={request.web_app_name}",
            "deployAppServicePlan=false",
            "pythonLinuxFxVersion=PYTHON|3.12",
            hosted_configuration,
        ]
    else:
        parameters = [
            f"environmentName={request.environment_name}",
            f"location={request.location}",
            f"projectName={request.project_name}",
            f"cosmosDatabaseName={request.cosmos_database_name}",
            f"cosmosContainerName={request.cosmos_container_name}",
            f"resourceNameSuffix={_resource_name_suffix(request)}",
            "deployApp=true",
            "deployFoundry=false",
            f"webAppName={request.web_app_name}",
            hosted_configuration,
        ]
    command.extend(["--parameters", *parameters])
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
    if request.purpose == "existing_web_app_reconciliation":
        return _parse_reconciliation_what_if_summary(stdout, request)
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
        allow_expected_ignored_resource_subsets=True,
        automatically_approved_actions=frozenset({"Create", "Modify", "NoChange"}),
    )
    if parsed is None:
        return None
    modifying = tuple(
        change for change in parsed.changes if change.action == "Modify"
    )
    modify_topology_approved = bool(
        not modifying
        or (
            len(modifying) == 1
            and parsed.count("Create") == 0
            and parsed.count("NoChange") > 0
            and modifying[0].resource_type == "Microsoft.Web/sites"
            and modifying[0].logical_category == "web_app"
            and modifying[0].approved_boundary
            and modifying[0].expected_identity_match
            and modifying[0].expected_parent_match
            and modifying[0].expected_scope_match
            and modifying[0].expected_multiplicity_match
        )
    )
    change_evidence = tuple(
        replace(change, approved_boundary=False)
        if change.action == "Modify" and not modify_topology_approved
        else change
        for change in parsed.changes
    )
    return WhatIfSummary(
        create_count=parsed.count("Create"),
        modify_count=parsed.count("Modify"),
        delete_count=parsed.count("Delete"),
        no_change_count=parsed.count("NoChange"),
        ignore_count=parsed.count("Ignore"),
        deploy_count=parsed.count("Deploy"),
        unsupported_count=parsed.count("Unsupported"),
        change_evidence=change_evidence,
        exact_topology_match=bool(
            parsed.exact_topology_match and modify_topology_approved
        ),
    )


def _parse_reconciliation_what_if_summary(
    stdout: str,
    request: WebAppInfrastructureDeploymentRequest,
) -> WhatIfSummary | None:
    web_app = ExpectedWhatIfResource(
        "Microsoft.Web/sites",
        "web_app",
        request.resource_group,
        (request.web_app_name,),
    )
    parsed = parse_sanitized_what_if(
        stdout,
        boundary="web_app_reconciliation",
        expected_resources=(web_app,),
        automatically_approved_actions=frozenset({"Modify"}),
    )
    if parsed is None:
        return None
    web_app_modifications = tuple(
        change
        for change in parsed.changes
        if change.action == "Modify"
        and change.resource_type == "Microsoft.Web/sites"
        and change.logical_category == "web_app"
    )
    exact_reconciliation = bool(
        parsed.exact_topology_match
        and len(web_app_modifications) == 1
        and len(parsed.changes) == 1
        and parsed.count("Create") == 0
        and parsed.count("Modify") == 1
        and parsed.count("NoChange") == 0
        and parsed.count("Ignore") == 0
        and parsed.count("Delete") == 0
        and parsed.count("Deploy") == 0
        and parsed.count("Unsupported") == 0
    )
    change_evidence = tuple(
        replace(change, approved_boundary=False)
        if not exact_reconciliation
        else change
        for change in parsed.changes
    )
    return WhatIfSummary(
        create_count=parsed.count("Create"),
        modify_count=parsed.count("Modify"),
        delete_count=parsed.count("Delete"),
        no_change_count=parsed.count("NoChange"),
        ignore_count=parsed.count("Ignore"),
        deploy_count=parsed.count("Deploy"),
        unsupported_count=parsed.count("Unsupported"),
        change_evidence=change_evidence,
        exact_topology_match=exact_reconciliation,
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
    plan_name = _app_service_plan_name(request)
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


def _app_service_plan_name(
    request: WebAppInfrastructureDeploymentRequest,
) -> str:
    project_environment = f"{request.project_name}-{request.environment_name}"
    return (
        f"{project_environment}-plan-{_resource_name_suffix(request)}"
        .casefold()[:40]
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
