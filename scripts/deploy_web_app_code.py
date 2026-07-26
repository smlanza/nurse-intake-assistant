import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import time
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
from src.app.services.bounded_subprocess import (
    BoundedCommandResult as CommandResult,
    TIMEOUT_RETURN_CODE,
    run_bounded_subprocess,
)


AZURE_DEPLOYMENT_OPERATION_TIMEOUT_MS = 240_000
DEPLOYMENT_COMMAND_TIMEOUT_SECONDS = 300.0
DEPLOYMENT_COMMAND_CLEANUP_TIMEOUT_SECONDS = 5.0
DEPLOYMENT_STATUS_COMMAND_TIMEOUT_SECONDS = 10.0
DEPLOYMENT_STATUS_MAX_ATTEMPTS = 37
DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS = 360.0
DEPLOYMENT_STATUS_BACKOFF_SECONDS = 10.0
DEPLOYMENT_ATTEMPT_CLOCK_SKEW_SECONDS = 120
_KUDU_DEPLOYMENT_IN_PROGRESS_STATUSES = {0, 1, 2}
_KUDU_DEPLOYMENT_FAILED_STATUS = 3
_KUDU_DEPLOYMENT_SUCCESS_STATUS = 4
_EXPECTED_DEPLOYER = "OneDeploy"


class CommandRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


class SubprocessCommandRunner:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEPLOYMENT_COMMAND_TIMEOUT_SECONDS,
        cleanup_timeout_seconds: float = (
            DEPLOYMENT_COMMAND_CLEANUP_TIMEOUT_SECONDS
        ),
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds

    def run(self, args: list[str]) -> CommandResult:
        timeout_seconds = (
            DEPLOYMENT_STATUS_COMMAND_TIMEOUT_SECONDS
            if args[:5]
            == ["az", "webapp", "log", "deployment", "list"]
            else self.timeout_seconds
        )
        return run_bounded_subprocess(
            args,
            timeout_seconds=timeout_seconds,
            cleanup_timeout_seconds=self.cleanup_timeout_seconds,
        )


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
        "azure_mutation_made": False,
        "deployment_accepted": False,
        "deployment_command_timed_out": False,
        "deployment_status_checked": False,
        "deployment_record_found": False,
        "deployment_record_complete": False,
        "deployment_record_successful": False,
        "hosted_application_verified": False,
        "recommended_next_step": "Review the sanitized failure category before retrying.",
    }


def _authorization_failure(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in ("authentication", "authorization", "az login"))


def _deployment_status_command(request: DeploymentRequest) -> list[str]:
    return [
        "az",
        "webapp",
        "log",
        "deployment",
        "list",
        "--resource-group",
        request.resource_group or "",
        "--name",
        request.web_app_name or "",
        "--query",
        (
            "[].{id:id,status:status,complete:complete,deployer:deployer,"
            "siteName:site_name,receivedTime:received_time,"
            "startTime:start_time,endTime:end_time}"
        ),
        "--output",
        "json",
        "--only-show-errors",
    ]


def _deployment_records(outcome: CommandResult) -> list[dict[str, object]] | None:
    if outcome.return_code != 0:
        return None
    try:
        payload = json.loads(outcome.stdout)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, list) or not all(
        isinstance(record, dict) for record in payload
    ):
        return None
    return payload


def _deployment_record_ids(
    records: list[dict[str, object]],
) -> frozenset[str] | None:
    identifiers: list[str] = []
    for record in records:
        identifier = record.get("id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier != identifier.strip()
            or len(identifier) > 256
        ):
            return None
        identifiers.append(identifier)
    if len(set(identifiers)) != len(identifiers):
        return None
    return frozenset(identifiers)


def _azure_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _current_deployment_record_state(
    record: dict[str, object],
    *,
    request: DeploymentRequest,
    attempt_started_at: datetime,
    checked_at: datetime,
) -> str:
    identifier = record.get("id")
    status = record.get("status")
    complete = record.get("complete")
    received_at = _azure_datetime(record.get("receivedTime"))
    started_at = _azure_datetime(record.get("startTime"))
    ended_at = _azure_datetime(record.get("endTime"))
    if (
        not isinstance(identifier, str)
        or not identifier
        or type(status) is not int
        or status
        not in {
            *_KUDU_DEPLOYMENT_IN_PROGRESS_STATUSES,
            _KUDU_DEPLOYMENT_FAILED_STATUS,
            _KUDU_DEPLOYMENT_SUCCESS_STATUS,
        }
        or type(complete) is not bool
        or record.get("deployer") != _EXPECTED_DEPLOYER
        or record.get("siteName") != request.web_app_name
        or received_at is None
        or started_at is None
    ):
        return "malformed"
    earliest = attempt_started_at - timedelta(
        seconds=DEPLOYMENT_ATTEMPT_CLOCK_SKEW_SECONDS
    )
    latest = checked_at + timedelta(
        seconds=DEPLOYMENT_ATTEMPT_CLOCK_SKEW_SECONDS
    )
    if not (
        earliest <= received_at <= latest
        and earliest <= started_at <= latest
    ):
        return "stale"
    if not complete:
        return (
            "pending"
            if status in _KUDU_DEPLOYMENT_IN_PROGRESS_STATUSES
            else "malformed"
        )
    if ended_at is None or not started_at <= ended_at <= latest:
        return "malformed"
    if status == _KUDU_DEPLOYMENT_SUCCESS_STATUS:
        return "success"
    if status == _KUDU_DEPLOYMENT_FAILED_STATUS:
        return "failed"
    return "malformed"


def _reconcile_ambiguous_deployment(
    request: DeploymentRequest,
    *,
    runner: CommandRunner,
    baseline_ids: frozenset[str],
    attempt_started_at: datetime,
    result: dict[str, object],
) -> str:
    reconciliation_started = time.monotonic()
    for attempt in range(DEPLOYMENT_STATUS_MAX_ATTEMPTS):
        outcome = runner.run(_deployment_status_command(request))
        result["deployment_status_checked"] = True
        if outcome.return_code != 0:
            return (
                "authentication_or_authorization_failed"
                if _authorization_failure(outcome.stderr)
                else "deployment_status_unverified"
            )
        records = _deployment_records(outcome)
        if records is None:
            return "deployment_status_malformed"
        identifiers = _deployment_record_ids(records)
        if identifiers is None:
            return "deployment_status_malformed"
        current = [
            record
            for record in records
            if record.get("id") not in baseline_ids
        ]
        if len(current) > 1:
            return "deployment_status_unverified"
        if len(current) == 1:
            state = _current_deployment_record_state(
                current[0],
                request=request,
                attempt_started_at=attempt_started_at,
                checked_at=datetime.now(timezone.utc),
            )
            if state == "malformed":
                return "deployment_status_malformed"
            if state == "stale":
                return "deployment_status_unverified"
            result["deployment_record_found"] = True
            if state == "success":
                result["deployment_record_complete"] = True
                result["deployment_record_successful"] = True
                result["azure_mutation_made"] = True
                return "success"
            if state == "failed":
                result["deployment_record_complete"] = True
                result["azure_mutation_made"] = True
                return "deployment_failed"
        if attempt + 1 >= DEPLOYMENT_STATUS_MAX_ATTEMPTS:
            break
        elapsed = time.monotonic() - reconciliation_started
        if (
            elapsed + DEPLOYMENT_STATUS_BACKOFF_SECONDS
            > DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS
        ):
            break
        time.sleep(DEPLOYMENT_STATUS_BACKOFF_SECONDS)
    result["azure_mutation_made"] = None
    return "deployment_status_unverified"


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
    try:
        baseline_outcome = command_runner.run(
            _deployment_status_command(request)
        )
        result["deployment_status_checked"] = True
        if baseline_outcome.return_code != 0:
            result["ok"] = False
            result["category"] = (
                "authentication_or_authorization_failed"
                if _authorization_failure(baseline_outcome.stderr)
                else "deployment_status_unverified"
            )
            return result
        baseline_records = _deployment_records(baseline_outcome)
        baseline_ids = (
            _deployment_record_ids(baseline_records)
            if baseline_records is not None
            else None
        )
        if baseline_ids is None:
            result["ok"] = False
            result["category"] = "deployment_status_malformed"
            return result

        result["azure_command_attempted"] = True
        attempt_started_at = datetime.now(timezone.utc)
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
                "--track-status",
                "false",
                "--timeout",
                str(AZURE_DEPLOYMENT_OPERATION_TIMEOUT_MS),
                "--output",
                "none",
            ]
        )
    finally:
        if deployment_artifact is not None:
            discard_immutable_deployment_artifact(deployment_artifact)
    timed_out = bool(
        getattr(outcome, "timed_out", False)
        or outcome.return_code == TIMEOUT_RETURN_CODE
    )
    result["deployment_command_timed_out"] = timed_out
    if outcome.return_code == 0:
        result["azure_mutation_made"] = True
        result["deployment_accepted"] = True
        result["recommended_next_step"] = (
            "Deployment was accepted but not verified; check /health, "
            "/version, and /demo/status separately."
        )
        return result
    if outcome.return_code == 127:
        result["ok"] = False
        result["category"] = "cli_unavailable"
        return result
    if _authorization_failure(outcome.stderr):
        result["ok"] = False
        result["category"] = "authentication_or_authorization_failed"
        return result

    result["azure_mutation_made"] = None
    category = _reconcile_ambiguous_deployment(
        request,
        runner=command_runner,
        baseline_ids=baseline_ids,
        attempt_started_at=attempt_started_at,
        result=result,
    )
    result["category"] = category
    result["ok"] = category == "success"
    result["deployment_accepted"] = category == "success"
    if category == "success":
        result["recommended_next_step"] = (
            "OneDeploy completion was reconciled after an ambiguous local "
            "command result; verify the exact hosted artifact."
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
