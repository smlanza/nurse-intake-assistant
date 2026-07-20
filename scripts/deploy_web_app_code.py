import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Protocol


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.web_app_package import (
    PACKAGE_FILENAME,
    PackageSafetyError,
    WebAppPackage,
    build_web_app_package,
    consume_web_app_package_authorization,
    create_package_authorization_session,
    discard_immutable_deployment_artifact,
    materialize_immutable_deployment_artifact,
    PackageAuthorizationSession,
    plan_web_app_package,
    validate_web_app_package,
    verify_immutable_deployment_artifact,
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
class DeploymentRequest:
    mode: str
    resource_group: str | None = None
    web_app_name: str | None = None


def _base(request: DeploymentRequest, category: str, ok: bool = False) -> dict[str, object]:
    return {
        "ok": ok,
        "operation": "deploy_web_app_code",
        "mode": request.mode,
        "category": category,
        "package_created": False,
        "package_filename": PACKAGE_FILENAME,
        "package_file_count": 0,
        "package_sha256_present": False,
        "azure_command_attempted": False,
        "deployment_accepted": False,
        "hosted_application_verified": False,
        "recommended_next_step": "Review the sanitized failure category before retrying.",
    }


def _authorization_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in ("authentication", "authorization", "az login"))


def execute(
    request: DeploymentRequest,
    *,
    runner: CommandRunner | None = None,
    source_root: Path | None = None,
    prebuilt_package: WebAppPackage | None = None,
    authorization_session: PackageAuthorizationSession | None = None,
) -> dict[str, object]:
    source_root = source_root or ROOT
    deployment_artifact = None
    if request.mode == "live" and (
        not request.resource_group or not request.web_app_name
    ):
        return _base(request, "missing_configuration")

    try:
        if request.mode == "check":
            plan = plan_web_app_package(source_root)
            result = _base(request, "success", True)
            result["package_file_count"] = len(plan.member_names)
            result["recommended_next_step"] = "Run --package to create and inspect the deterministic ZIP."
            return result
        if request.mode not in {"package", "live"}:
            return _base(request, "unsupported_mode")
        session = authorization_session or create_package_authorization_session()
        package = (
            validate_web_app_package(prebuilt_package, source_root, session)
            if prebuilt_package is not None
            else build_web_app_package(
                source_root,
                authorization_session=session,
            )
        )
        if request.mode == "live":
            deployment_artifact = materialize_immutable_deployment_artifact(
                package,
                source_root,
                session,
            )
            consume_web_app_package_authorization(package, source_root, session)
            verify_immutable_deployment_artifact(deployment_artifact)
    except PackageSafetyError as error:
        if deployment_artifact is not None:
            discard_immutable_deployment_artifact(deployment_artifact)
        return _base(request, error.category)

    result = _base(request, "success", True)
    result.update(
        {
            "package_created": prebuilt_package is None,
            "package_file_count": package.file_count,
            "package_sha256_present": True,
        }
    )
    if request.mode == "package":
        result["recommended_next_step"] = (
            "Review the package metadata before any explicit live deployment."
        )
        return result

    command_runner = runner or SubprocessCommandRunner()
    result["azure_command_attempted"] = True
    try:
        outcome = command_runner.run(
            [
                "az",
                "webapp",
                "deploy",
                "--resource-group",
                request.resource_group or "",
                "--name",
                request.web_app_name or "",
                "--src-path",
                str(deployment_artifact.path),
                "--type",
                "zip",
                "--clean",
                "true",
                "--restart",
                "true",
                "--output",
                "none",
            ]
        )
    finally:
        if deployment_artifact is not None:
            discard_immutable_deployment_artifact(deployment_artifact)
    if outcome.return_code != 0:
        result["ok"] = False
        if outcome.return_code == 127:
            result["category"] = "cli_unavailable"
        elif _authorization_failure(outcome.stderr):
            result["category"] = "authentication_or_authorization_failed"
        else:
            result["category"] = "deployment_failed"
        return result

    result["deployment_accepted"] = True
    result["recommended_next_step"] = (
        "Deployment was accepted but not verified; check /health, /version, and /demo/status separately."
    )
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate, package, or explicitly deploy code to an existing Azure Web App."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--package", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--resource-group")
    parser.add_argument("--web-app")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.live:
        if not args.json:
            parser.error("--live requires --json")
        if not args.resource_group or not args.web_app:
            parser.error("--live requires --resource-group and --web-app")
    elif args.resource_group or args.web_app:
        parser.error("--resource-group and --web-app are valid only with --live")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "package" if args.package else "live"
    result = execute(DeploymentRequest(mode, args.resource_group, args.web_app))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
