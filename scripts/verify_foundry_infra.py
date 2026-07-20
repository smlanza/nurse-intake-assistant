import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse


ACCOUNT_QUERY = (
    "{name:name,kind:kind,provisioningState:properties.provisioningState,"
    "allowProjectManagement:properties.allowProjectManagement,"
    "disableLocalAuth:properties.disableLocalAuth,tags:tags}"
)
PROJECT_QUERY = "{name:name,provisioningState:properties.provisioningState}"
DEPLOYMENT_QUERY = (
    "{name:name,provisioningState:properties.provisioningState,"
    "model:properties.model,sku:sku}"
)


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
                args,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return CommandResult(127, "", "")
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class VerificationRequest:
    resource_group: str
    project_endpoint: str
    model_deployment_name: str
    expected_model_capacity: int | None = None
    expected_purpose_tag: str | None = None


def parse_project_endpoint(endpoint: str) -> tuple[str, str]:
    try:
        parsed = urlparse(endpoint)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid project endpoint") from exc
    suffix = ".services.ai.azure.com"
    host = parsed.hostname or ""
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
        or not host.endswith(suffix)
    ):
        raise ValueError("invalid project endpoint")
    account_name = host[: -len(suffix)]
    path_match = re.fullmatch(r"/api/projects/([A-Za-z0-9][A-Za-z0-9_.-]*)", parsed.path)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", account_name) or path_match is None:
        raise ValueError("invalid project endpoint")
    return account_name, path_match.group(1)


def _result(category: str, *, endpoint_valid: bool = False) -> dict[str, object]:
    return {
        "ok": False,
        "operation": "verify_foundry_infrastructure",
        "category": category,
        "account_verified": False,
        "project_verified": False,
        "model_deployment_verified": False,
        "project_endpoint_valid": endpoint_valid,
        "account_kind": None,
        "account_provisioning_state": None,
        "project_provisioning_state": None,
        "model_deployment_provisioning_state": None,
        "model_name": None,
        "model_version": None,
        "model_format": None,
        "model_sku": None,
        "model_capacity": None,
        "recommended_next_step": "Review the sanitized failure category before retrying.",
    }


def _authorization_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(
        marker in lowered
        for marker in ("az login", "authentication", "authorization", "forbidden", "credential")
    )


def _command_failure(result: CommandResult, ordinary_category: str) -> str | None:
    if result.return_code == 0:
        return None
    if result.return_code == 127:
        return "cli_unavailable"
    if _authorization_failure(result.stderr):
        return "authentication_or_authorization_failed"
    lowered = result.stderr.casefold()
    if any(
        marker in lowered
        for marker in ("resourcenotfound", "resource not found", "could not be found")
    ):
        return "resource_not_found"
    return ordinary_category


def _json_object(value: str) -> dict[str, object] | None:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _state_succeeded_if_available(payload: dict[str, object]) -> bool:
    state = payload.get("provisioningState")
    return state is None or state == "Succeeded"


def verify(
    request: VerificationRequest, runner: CommandRunner | None = None
) -> dict[str, object]:
    try:
        account_name, project_name = parse_project_endpoint(request.project_endpoint)
    except ValueError:
        return _result("invalid_project_endpoint")

    runner = runner or SubprocessCommandRunner()
    result = _result("unexpected_error", endpoint_valid=True)

    try:
        account_response = runner.run(
            [
                "az", "cognitiveservices", "account", "show",
                "--resource-group", request.resource_group,
                "--name", account_name,
                "--query", ACCOUNT_QUERY,
                "--output", "json",
                "--only-show-errors",
            ]
        )
        failure = _command_failure(account_response, "account_verification_failed")
        if failure:
            return _result(failure, endpoint_valid=True)
        account = _json_object(account_response.stdout)
        if (
            account is None
            or account.get("name") != account_name
            or account.get("kind") != "AIServices"
            or account.get("allowProjectManagement") is not True
            or account.get("disableLocalAuth") is not True
            or not _state_succeeded_if_available(account)
            or (
                request.expected_purpose_tag is not None
                and (
                    not isinstance(account.get("tags"), dict)
                    or account["tags"].get("purpose")
                    != request.expected_purpose_tag
                )
            )
        ):
            return _result("account_contract_invalid", endpoint_valid=True)
        result["account_verified"] = True
        result["account_kind"] = account["kind"]
        result["account_provisioning_state"] = account.get("provisioningState")

        project_response = runner.run(
            [
                "az", "cognitiveservices", "account", "project", "show",
                "--resource-group", request.resource_group,
                "--name", account_name,
                "--project-name", project_name,
                "--query", PROJECT_QUERY,
                "--output", "json",
                "--only-show-errors",
            ]
        )
        failure = _command_failure(project_response, "project_verification_failed")
        if failure:
            result["category"] = failure
            return result
        project = _json_object(project_response.stdout)
        valid_project_names = {
            project_name,
            f"{account_name}/{project_name}",
        }
        if (
            project is None
            or project.get("name") not in valid_project_names
            or not _state_succeeded_if_available(project)
        ):
            result["category"] = "project_contract_invalid"
            return result
        result["project_verified"] = True
        result["project_provisioning_state"] = project.get("provisioningState")

        deployment_response = runner.run(
            [
                "az", "cognitiveservices", "account", "deployment", "show",
                "--resource-group", request.resource_group,
                "--name", account_name,
                "--deployment-name", request.model_deployment_name,
                "--query", DEPLOYMENT_QUERY,
                "--output", "json",
                "--only-show-errors",
            ]
        )
        failure = _command_failure(
            deployment_response, "model_deployment_verification_failed"
        )
        if failure:
            result["category"] = failure
            return result
        deployment = _json_object(deployment_response.stdout)
        if (
            deployment is None
            or deployment.get("name") != request.model_deployment_name
            or not _state_succeeded_if_available(deployment)
        ):
            result["category"] = "model_deployment_contract_invalid"
            return result
        model = deployment.get("model")
        sku = deployment.get("sku")
        if not isinstance(model, dict) or not isinstance(sku, dict):
            result["category"] = "model_deployment_contract_invalid"
            return result
        capacity = sku.get("capacity")
        if not isinstance(capacity, int) or isinstance(capacity, bool) or capacity < 1:
            result["category"] = "model_capacity_mismatch"
            return result
        if (
            request.expected_model_capacity is not None
            and capacity != request.expected_model_capacity
        ):
            result["category"] = "model_capacity_mismatch"
            return result
        result.update(
            {
                "ok": True,
                "category": "success",
                "model_deployment_verified": True,
                "model_deployment_provisioning_state": deployment.get(
                    "provisioningState"
                ),
                "model_name": model.get("name"),
                "model_version": model.get("version"),
                "model_format": model.get("format"),
                "model_sku": sku.get("name"),
                "model_capacity": capacity,
                "recommended_next_step": "Infrastructure verification succeeded. Review the result before creating the prompt agent.",
            }
        )
        return result
    except Exception:
        return _result("unexpected_error", endpoint_valid=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only verification of Microsoft Foundry infrastructure."
    )
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--model-deployment-name", required=True)
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = verify(
        VerificationRequest(
            args.resource_group,
            args.project_endpoint,
            args.model_deployment_name,
        )
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
