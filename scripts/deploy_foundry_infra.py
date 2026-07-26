import argparse
import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from src.app.services.azure_what_if_evidence import (
    ExpectedWhatIfResource,
    parse_sanitized_what_if,
)


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    "foundry-only": ROOT / "infra" / "foundry-only.bicep",
    "full-stack": ROOT / "infra" / "main.bicep",
}
FOUNDRY_MODULE = ROOT / "infra" / "modules" / "foundry.bicep"
SECRET_MARKERS = ("secret", "password", "token", "key", "connectionstring")
REQUIRED_MODEL_PARAMETERS = {
    "modeldeploymentname",
    "modelname",
    "modelversion",
    "modelpublisherformat",
    "modelskuname",
    "modelcapacity",
}
_FOUNDRY_CONFLICT_WRAPPER_CODES = {
    "InvalidTemplateDeployment",
    "DeploymentFailed",
    "PreflightValidationCheckFailed",
}
_MAX_FOUNDRY_CONFLICT_TEXT_LENGTH = 16_384
_MAX_FOUNDRY_CONFLICT_TEXT_LINES = 64
_MAX_FOUNDRY_CONFLICT_CODE_OCCURRENCES = 4
_SOFT_DELETED_RESOURCE_PREFIX = "An existing resource with ID "
_SOFT_DELETED_RESOURCE_SUFFIX = " has been soft-deleted."


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    def run(self, args: list[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                args, shell=False, capture_output=True, text=True, check=False
            )
        except OSError:
            return CommandResult(127, "", "")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class DeploymentRequest:
    action: str
    template_mode: str
    parameters: Path
    resource_group: str
    location: str


_FOUNDRY_RESOURCE_TYPES = {
    "Microsoft.CognitiveServices/accounts": "foundry_account",
    "Microsoft.CognitiveServices/accounts/projects": "foundry_project",
    "Microsoft.CognitiveServices/accounts/deployments": "model_deployment",
}


def _base(
    request: DeploymentRequest, category: str, ok: bool = False
) -> dict[str, object]:
    return {
        "ok": ok,
        "mode": request.action,
        "operation": "deploy_foundry_infrastructure",
        "template_mode": request.template_mode,
        "category": category,
        "resource_group_ready": False,
        "foundry_resource_created": False,
        "foundry_project_created": False,
        "model_deployment_created": False,
        "foundry_resource_name": None,
        "foundry_project_name": None,
        "project_endpoint": None,
        "model_deployment_name": None,
        "recommended_next_step": "Review configuration and retry safely.",
        "change_evidence": [],
        "exact_topology_match": False,
    }


def _authorization_failure(stderr: str) -> bool:
    value = stderr.lower()
    return "authorization" in value or "authentication" in value or "login" in value


def _exact_foundry_account_target(
    target: object,
    request: DeploymentRequest,
    account_name: str,
) -> bool:
    if not isinstance(target, str) or target != target.strip():
        return False
    target_parts = target.split("/")
    if (
        len(target_parts) != 9
        or target_parts[0] != ""
        or target_parts[1].casefold() != "subscriptions"
        or target_parts[3].casefold() != "resourcegroups"
        or target_parts[4].casefold() != request.resource_group.casefold()
        or target_parts[5].casefold() != "providers"
        or target_parts[6].casefold() != "microsoft.cognitiveservices"
        or target_parts[7].casefold() != "accounts"
        or target_parts[8].casefold() != account_name.casefold()
    ):
        return False
    try:
        return str(UUID(target_parts[2])) == target_parts[2].casefold()
    except (AttributeError, TypeError, ValueError):
        return False


def _bounded_conflict_text(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_FOUNDRY_CONFLICT_TEXT_LENGTH
    ):
        return None
    lines = value.splitlines()
    if not lines or len(lines) > _MAX_FOUNDRY_CONFLICT_TEXT_LINES:
        return None
    return " ".join(line.strip() for line in lines)


def _soft_deleted_target_from_text(
    value: object,
    *,
    require_cli_codes: bool,
) -> str | None:
    normalized = _bounded_conflict_text(value)
    if normalized is None:
        return None
    if require_cli_codes:
        wrapper_count = normalized.count("InvalidTemplateDeployment")
        leaf_count = normalized.count("FlagMustBeSetForRestore")
        if (
            not 1 <= wrapper_count <= _MAX_FOUNDRY_CONFLICT_CODE_OCCURRENCES
            or not 1 <= leaf_count <= _MAX_FOUNDRY_CONFLICT_CODE_OCCURRENCES
        ):
            return None
        marker = (
            "FlagMustBeSetForRestore - "
            + _SOFT_DELETED_RESOURCE_PREFIX
        )
    else:
        marker = _SOFT_DELETED_RESOURCE_PREFIX
    if normalized.count(marker) != 1:
        return None
    remainder = normalized.split(marker, 1)[1]
    if not remainder or remainder[0] not in {"'", '"'}:
        return None
    quote = remainder[0]
    end = remainder.find(quote, 1)
    if end < 2 or end > 513:
        return None
    target = remainder[1:end]
    if not remainder[end + 1 :].startswith(_SOFT_DELETED_RESOURCE_SUFFIX):
        return None
    if normalized.count(_SOFT_DELETED_RESOURCE_PREFIX) != 1:
        return None
    if normalized.count(_SOFT_DELETED_RESOURCE_SUFFIX) != 1:
        return None
    if normalized.casefold().count("/subscriptions/") != 1:
        return None
    return target


def _structured_conflict_errors(outcome: CommandResult) -> list[dict[str, object]]:
    structured_errors: list[dict[str, object]] = []
    for raw in (outcome.stdout, outcome.stderr):
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        error = payload.get("error")
        if not isinstance(error, dict):
            continue
        if set(payload) == {"error"}:
            structured_errors.append(error)
        elif (
            set(payload) == {"status", "error"}
            and payload.get("status") == "Failed"
        ):
            structured_errors.append(error)
    return structured_errors


def _foundry_account_name_conflict(
    outcome: CommandResult,
    request: DeploymentRequest,
) -> tuple[str, str] | None:
    account_name = _parameter_string(
        request.parameters,
        "foundryAccountName",
    )
    if account_name is None:
        return None
    structured_errors = _structured_conflict_errors(outcome)
    if len(structured_errors) == 1:
        error = structured_errors[0]
        for _ in range(4):
            code = error.get("code")
            if code in {"CustomDomainInUse", "FlagMustBeSetForRestore"}:
                break
            details = error.get("details")
            if (
                code not in _FOUNDRY_CONFLICT_WRAPPER_CODES
                or not isinstance(details, list)
                or len(details) != 1
                or not isinstance(details[0], dict)
            ):
                return None
            error = details[0]
        else:
            return None
        if error.get("details") not in (None, []):
            return None
        code = error.get("code")
        if code == "CustomDomainInUse":
            if _exact_foundry_account_target(
                error.get("target"),
                request,
                account_name,
            ):
                return "custom_domain_in_use", "custom_domain_in_use"
            return None
        if code != "FlagMustBeSetForRestore":
            return None
        target = error.get("target")
        normalized_message = _bounded_conflict_text(error.get("message"))
        message_target = _soft_deleted_target_from_text(
            error.get("message"),
            require_cli_codes=False,
        )
        if (
            normalized_message is not None
            and "/subscriptions/" in normalized_message.casefold()
            and message_target is None
        ):
            return None
        if isinstance(target, str) and target.startswith("/subscriptions/"):
            if not _exact_foundry_account_target(
                target,
                request,
                account_name,
            ):
                return None
            if (
                message_target is not None
                and message_target.casefold() != target.casefold()
            ):
                return None
            return "FlagMustBeSetForRestore", "soft_deleted_account_name"
        if message_target is not None and _exact_foundry_account_target(
            message_target,
            request,
            account_name,
        ):
            return "FlagMustBeSetForRestore", "soft_deleted_account_name"
        return None
    if structured_errors:
        return None
    target = _soft_deleted_target_from_text(
        outcome.stderr,
        require_cli_codes=True,
    )
    if target is not None and _exact_foundry_account_target(
        target,
        request,
        account_name,
    ):
        return "FlagMustBeSetForRestore", "soft_deleted_account_name"
    return None


def _what_if_failure(
    outcome: CommandResult,
    request: DeploymentRequest,
) -> tuple[str, dict[str, object] | None]:
    if _authorization_failure(outcome.stderr):
        return "authentication_or_authorization_failed", None
    conflict = _foundry_account_name_conflict(outcome, request)
    if conflict is not None:
        return (
            "foundry_account_name_unavailable",
            {
                "azure_error_class": conflict[0],
                "failure_kind": conflict[1],
                "same_configuration_retry_safe": False,
            },
        )
    return "what_if_failed", None


def _validate_files(request: DeploymentRequest) -> tuple[Path | None, str | None]:
    template = TEMPLATES.get(request.template_mode)
    if template is None or not template.is_file() or not FOUNDRY_MODULE.is_file():
        return None, "missing_configuration"
    if not request.parameters.is_file():
        return None, "missing_configuration"
    try:
        parameter_text = request.parameters.read_text()
    except OSError:
        return None, "parameter_file_invalid"
    using_match = re.search(
        r"(?m)^\s*using\s+['\"]([^'\"]+)['\"]\s*$", parameter_text
    )
    if using_match is None:
        return None, "parameter_file_invalid"
    try:
        using_target = (request.parameters.parent / using_match.group(1)).resolve(
            strict=True
        )
        expected_target = template.resolve(strict=True)
    except OSError:
        return None, "parameter_file_invalid"
    if using_target != expected_target:
        return None, "parameter_file_invalid"
    names = [
        line.split("=", 1)[0].removeprefix("param ").strip().lower()
        for line in parameter_text.splitlines()
        if line.strip().startswith("param ") and "=" in line
    ]
    if any(marker in name for name in names for marker in SECRET_MARKERS):
        return None, "parameter_file_invalid"
    if not REQUIRED_MODEL_PARAMETERS.issubset(names):
        return None, "parameter_file_invalid"
    if request.template_mode == "full-stack" and not any(
        line.strip().lower().replace(" ", "") == "paramdeployfoundry=true"
        for line in parameter_text.splitlines()
    ):
        return None, "parameter_file_invalid"
    return template, None


def execute(
    request: DeploymentRequest,
    runner: CommandRunner | None = None,
    *,
    ensure_resource_group: bool = True,
    verify_resource_group: bool = True,
) -> dict[str, object]:
    runner = runner or SubprocessCommandRunner()
    template, error = _validate_files(request)
    if error or template is None:
        return _base(request, error or "missing_configuration")

    if request.action == "check":
        if shutil.which("az") is None and isinstance(runner, SubprocessCommandRunner):
            return _base(request, "cli_unavailable")
        for command, category in (
            (["az", "version", "--output", "json"], "cli_unavailable"),
            (["az", "bicep", "version"], "cli_unavailable"),
            (["az", "bicep", "build", "--file", str(template), "--stdout"], "template_invalid"),
            (
                [
                    "az",
                    "bicep",
                    "build-params",
                    "--file",
                    str(request.parameters),
                    "--stdout",
                ],
                "parameter_file_invalid",
            ),
        ):
            if runner.run(command).return_code != 0:
                return _base(request, category)
        result = _base(request, "success", True)
        result["recommended_next_step"] = "Run --what-if against an existing resource group, or --live --json."
        return result

    if request.action == "what-if":
        if verify_resource_group:
            exists = runner.run(
                [
                    "az",
                    "group",
                    "exists",
                    "--name",
                    request.resource_group,
                    "--output",
                    "tsv",
                ]
            )
            if exists.return_code != 0:
                category = (
                    "authentication_or_authorization_failed"
                    if _authorization_failure(exists.stderr)
                    else "what_if_failed"
                )
                return _base(request, category)
            if exists.stdout.strip().lower() != "true":
                result = _base(request, "resource_group_missing")
                result["recommended_next_step"] = "Create the resource group explicitly or use --live --json."
                return result
        command = [
            "az", "deployment", "group", "what-if", "--resource-group", request.resource_group,
            "--parameters", str(request.parameters),
            "--no-pretty-print", "--output", "json",
        ]
        outcome = runner.run(command)
        if outcome.return_code != 0:
            category, diagnostic = _what_if_failure(outcome, request)
            result = _base(request, category)
            if diagnostic is not None:
                result["what_if_failure_diagnostic"] = diagnostic
                result["recommended_next_step"] = (
                    "Choose a different globally unique Foundry account name in the "
                    "ignored local configuration, then rerun the fresh preview."
                )
            return result
        summary = parse_sanitized_what_if(
            outcome.stdout,
            boundary="foundry",
            expected_resources=_expected_foundry_resources(request),
            sanitized_additional_resource_types={
                "Microsoft.Resources/deployments": "nested_deployment"
            },
        )
        if summary is None:
            return _base(request, "what_if_parse_failed")
        result = _base(request, "success", True)
        result["resource_group_ready"] = True
        result.update(
            {
                "create_count": summary.count("Create"),
                "modify_count": summary.count("Modify"),
                "no_change_count": summary.count("NoChange"),
                "delete_count": summary.count("Delete"),
                "ignore_count": summary.count("Ignore"),
                "deploy_count": summary.count("Deploy"),
                "unsupported_count": summary.count("Unsupported"),
                "change_evidence": summary.to_json_list(),
                "exact_topology_match": summary.exact_topology_match,
                "delete_review_required": summary.count("Delete") > 0,
                "manual_review_required": any(
                    summary.count(action) > 0
                    for action in ("Delete", "Deploy", "Unsupported")
                ) or not summary.all_changes_allowlisted,
            }
        )
        result["recommended_next_step"] = (
            "Manual review is required before any live request."
            if result["manual_review_required"]
            else "Review the sanitized preview, then run --live --json when ready."
        )
        return result

    if ensure_resource_group:
        group = runner.run(
            [
                "az",
                "group",
                "create",
                "--name",
                request.resource_group,
                "--location",
                request.location,
                "--output",
                "json",
            ]
        )
        if group.return_code != 0:
            category = "authentication_or_authorization_failed" if _authorization_failure(group.stderr) else "resource_group_creation_failed"
            return _base(request, category)
    deployment = runner.run([
        "az", "deployment", "group", "create", "--resource-group", request.resource_group,
        "--parameters", str(request.parameters),
        "--query", "properties.outputs", "--output", "json",
    ])
    if deployment.return_code != 0:
        conflict = _foundry_account_name_conflict(deployment, request)
        category = (
            "authentication_or_authorization_failed"
            if _authorization_failure(deployment.stderr)
            else "foundry_account_name_unavailable"
            if conflict is not None
            else "deployment_failed"
        )
        result = _base(request, category)
        result["resource_group_ready"] = True
        if conflict is not None:
            result["deployment_failure_diagnostic"] = {
                "azure_error_class": conflict[0],
                "failure_kind": conflict[1],
                "account_name_conflict_proven": True,
            }
        return result
    try:
        outputs = json.loads(deployment.stdout)
        values = {name: outputs[name]["value"] for name in (
            "foundryResourceName", "foundryProjectName", "foundryProjectEndpoint", "modelDeploymentName"
        )}
        if not all(isinstance(value, str) and value for value in values.values()):
            raise ValueError
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        result = _base(request, "deployment_output_invalid")
        result["resource_group_ready"] = True
        return result
    expected_values = {
        "foundryResourceName": _parameter_string(
            request.parameters,
            "foundryAccountName",
        ),
        "foundryProjectName": _parameter_string(
            request.parameters,
            "foundryProjectName",
        ),
        "modelDeploymentName": _parameter_string(
            request.parameters,
            "modelDeploymentName",
        ),
    }
    expected_endpoint = (
        f"https://{expected_values['foundryResourceName']}.services.ai.azure.com/"
        f"api/projects/{expected_values['foundryProjectName']}"
    )
    if (
        any(value is None for value in expected_values.values())
        or any(values[name] != value for name, value in expected_values.items())
        or values["foundryProjectEndpoint"] != expected_endpoint
    ):
        result = _base(request, "foundry_deployment_identity_mismatch")
        result["resource_group_ready"] = True
        return result
    result = _base(request, "success", True)
    result.update({
        "resource_group_ready": True,
        "foundry_resource_created": True,
        "foundry_project_created": True,
        "model_deployment_created": True,
        "foundry_resource_name": values["foundryResourceName"],
        "foundry_project_name": values["foundryProjectName"],
        "project_endpoint": values["foundryProjectEndpoint"],
        "model_deployment_name": values["modelDeploymentName"],
        "recommended_next_step": "Update .env.foundry-agent.local and run deploy_foundry_agent.py --check.",
    })
    return result


def _expected_foundry_resources(
    request: DeploymentRequest,
) -> tuple[ExpectedWhatIfResource, ...]:
    values = {
        name: _parameter_string(request.parameters, name)
        for name in (
            "foundryAccountName",
            "foundryProjectName",
            "modelDeploymentName",
        )
    }
    account = values["foundryAccountName"]
    project = values["foundryProjectName"]
    deployment = values["modelDeploymentName"]
    if not account or not project or not deployment:
        return ()
    return (
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts",
            "foundry_account",
            request.resource_group,
            (account,),
        ),
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts/projects",
            "foundry_project",
            request.resource_group,
            (account, project),
        ),
        ExpectedWhatIfResource(
            "Microsoft.CognitiveServices/accounts/deployments",
            "model_deployment",
            request.resource_group,
            (account, deployment),
        ),
    )


def _parameter_string(path: Path, name: str) -> str | None:
    try:
        text = path.read_text()
    except OSError:
        return None
    match = re.search(
        rf"(?m)^\s*param\s+{re.escape(name)}\s*=\s*'([^'\r\n]+)'\s*$",
        text,
    )
    if match is None:
        return None
    value = match.group(1)
    return value if value == value.strip() else None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate or deploy allowlisted Microsoft Foundry infrastructure.")
    parser.add_argument("--mode", choices=sorted(TEMPLATES), default="foundry-only")
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--location", required=True)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--what-if", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    action = "check" if args.check else "what-if" if args.what_if else "live"
    result = execute(DeploymentRequest(action, args.mode, args.parameters, args.resource_group, args.location))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
