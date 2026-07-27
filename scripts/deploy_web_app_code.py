import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
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
DEPLOYMENT_BASELINE_MAX_ATTEMPTS = 31
DEPLOYMENT_BASELINE_MAX_ELAPSED_SECONDS = 300.0
DEPLOYMENT_BASELINE_BACKOFF_SECONDS = 10.0
DEPLOYMENT_STATUS_MAX_ATTEMPTS = 61
DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS = 600.0
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
        return self.run_with_timeout(args)

    def run_with_timeout(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        configured_timeout = (
            DEPLOYMENT_STATUS_COMMAND_TIMEOUT_SECONDS
            if args[:5]
            == ["az", "webapp", "log", "deployment", "list"]
            else self.timeout_seconds
        )
        effective_timeout = (
            configured_timeout
            if timeout_seconds is None
            else min(configured_timeout, timeout_seconds)
        )
        return run_bounded_subprocess(
            args,
            timeout_seconds=effective_timeout,
            cleanup_timeout_seconds=self.cleanup_timeout_seconds,
        )


@dataclass(frozen=True)
class DeploymentRequest:
    mode: str
    resource_group: str | None = None
    web_app_name: str | None = None


@dataclass(frozen=True)
class DeploymentReconciliation:
    category: str
    retry_permitted: bool = False


@dataclass(frozen=True)
class DeploymentBaselineResult:
    category: str
    ids: frozenset[str] | None
    checked: bool
    attempt_count: int


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
        "deployment_retry_attempted": False,
        "deployment_baseline_checked": False,
        "deployment_baseline_ready": False,
        "deployment_baseline_attempt_count": 0,
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


def _deployment_baseline_failure_is_transient(
    outcome: CommandResult,
) -> bool:
    if (
        outcome.return_code == 0
        or outcome.return_code == 127
        or _authorization_failure(outcome.stderr)
    ):
        return False
    lowered = outcome.stderr.lower()
    if any(
        marker in lowered
        for marker in (
            "unrecognized argument",
            "invalid argument",
            "invalid resource",
            "resourcegroupnotfound",
            "resourcenotfound",
            "bad request",
        )
    ):
        return False
    if _command_timed_out(outcome):
        return True

    def has_status_code(status: int) -> bool:
        return any(
            marker in lowered
            for marker in (
                f"http {status}",
                f"http status {status}",
                f"status code {status}",
                f"status code: {status}",
                f"returned {status}",
            )
        )

    if (
        has_status_code(404)
        and ("scm" in lowered or "kudu" in lowered)
        and ("not found" in lowered or "notfound" in lowered)
    ):
        return True
    if has_status_code(409) and "conflict" in lowered:
        return True
    if has_status_code(429) and (
        "too many requests" in lowered or "rate limit" in lowered
    ):
        return True
    if any(has_status_code(status) for status in range(500, 600)):
        return True
    if any(
        marker in lowered
        for marker in (
            "internal server error",
            "bad gateway",
            "service unavailable",
            "gateway timeout",
            "connection reset",
            "connection refused",
            "connection timed out",
            "read timed out",
            "temporarily unavailable",
        )
    ):
        return True
    return False


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


def _deployment_command(
    request: DeploymentRequest,
    deployment_path: Path,
) -> list[str]:
    return [
        "az",
        "webapp",
        "deploy",
        "--resource-group",
        request.resource_group or "",
        "--name",
        request.web_app_name or "",
        "--src-path",
        str(deployment_path),
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
        "--query",
        "id",
        "--output",
        "tsv",
    ]


def _deployment_submission_identifier(outcome: CommandResult) -> str | None:
    if outcome.return_code != 0:
        return None
    identifier = outcome.stdout.strip()
    if (
        not identifier
        or len(identifier) > 256
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", identifier) is None
    ):
        return None
    return identifier


def _run_with_timeout(
    runner: CommandRunner,
    args: list[str],
    *,
    timeout_seconds: float,
) -> CommandResult:
    bounded_run = getattr(runner, "run_with_timeout", None)
    if callable(bounded_run):
        return bounded_run(args, timeout_seconds=timeout_seconds)
    return runner.run(args)


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


def _acquire_deployment_baseline(
    request: DeploymentRequest,
    *,
    runner: CommandRunner,
) -> DeploymentBaselineResult:
    started_at = time.monotonic()
    attempt_count = 0
    for attempt in range(DEPLOYMENT_BASELINE_MAX_ATTEMPTS):
        outcome = runner.run(_deployment_status_command(request))
        attempt_count += 1
        if outcome.return_code == 0:
            records = _deployment_records(outcome)
            identifiers = (
                _deployment_record_ids(records)
                if records is not None
                else None
            )
            if identifiers is None:
                return DeploymentBaselineResult(
                    "deployment_status_malformed",
                    None,
                    True,
                    attempt_count,
                )
            return DeploymentBaselineResult(
                "success",
                identifiers,
                True,
                attempt_count,
            )
        if _authorization_failure(outcome.stderr):
            return DeploymentBaselineResult(
                "authentication_or_authorization_failed",
                None,
                True,
                attempt_count,
            )
        if outcome.return_code == 127:
            return DeploymentBaselineResult(
                "cli_unavailable",
                None,
                True,
                attempt_count,
            )
        if not _deployment_baseline_failure_is_transient(outcome):
            return DeploymentBaselineResult(
                "deployment_baseline_failed",
                None,
                True,
                attempt_count,
            )
        if attempt + 1 >= DEPLOYMENT_BASELINE_MAX_ATTEMPTS:
            break
        elapsed = time.monotonic() - started_at
        if (
            elapsed + DEPLOYMENT_BASELINE_BACKOFF_SECONDS
            > DEPLOYMENT_BASELINE_MAX_ELAPSED_SECONDS
        ):
            break
        time.sleep(DEPLOYMENT_BASELINE_BACKOFF_SECONDS)
    return DeploymentBaselineResult(
        "deployment_baseline_unavailable",
        None,
        attempt_count > 0,
        attempt_count,
    )


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
    expected_deployment_id: str | None,
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
    if (
        expected_deployment_id is not None
        and identifier != expected_deployment_id
    ):
        return "unrelated"
    earliest = attempt_started_at
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
    deadline: float,
    expected_deployment_id: str | None = None,
) -> DeploymentReconciliation:
    baseline_unchanged = True
    possible_current_record_observed = False
    valid_status_observations = 0
    for attempt in range(DEPLOYMENT_STATUS_MAX_ATTEMPTS):
        now = time.monotonic()
        if now >= deadline:
            break
        remaining = deadline - now
        outcome = _run_with_timeout(
            runner,
            _deployment_status_command(request),
            timeout_seconds=min(
                DEPLOYMENT_STATUS_COMMAND_TIMEOUT_SECONDS,
                remaining,
            ),
        )
        returned_at = time.monotonic()
        result["deployment_status_checked"] = True
        if returned_at >= deadline:
            result["azure_mutation_made"] = None
            return DeploymentReconciliation(
                "deployment_status_unverified"
            )
        if outcome.return_code != 0:
            return DeploymentReconciliation(
                (
                    "authentication_or_authorization_failed"
                    if _authorization_failure(outcome.stderr)
                    else "deployment_status_unverified"
                )
            )
        records = _deployment_records(outcome)
        if records is None:
            return DeploymentReconciliation("deployment_status_malformed")
        identifiers = _deployment_record_ids(records)
        if identifiers is None:
            return DeploymentReconciliation("deployment_status_malformed")
        valid_status_observations += 1
        if not baseline_ids.issubset(identifiers):
            baseline_unchanged = False
        current = [
            record
            for record in records
            if record.get("id") not in baseline_ids
        ]
        if current:
            possible_current_record_observed = True
        if (
            current
            and expected_deployment_id is None
            and not baseline_unchanged
        ):
            return DeploymentReconciliation("deployment_status_unverified")
        if len(current) > 1:
            return DeploymentReconciliation("deployment_status_unverified")
        if len(current) == 1:
            state = _current_deployment_record_state(
                current[0],
                request=request,
                attempt_started_at=attempt_started_at,
                checked_at=datetime.now(timezone.utc),
                expected_deployment_id=expected_deployment_id,
            )
            if state == "malformed":
                return DeploymentReconciliation(
                    "deployment_status_malformed"
                )
            if state == "stale":
                return DeploymentReconciliation(
                    "deployment_status_unverified"
                )
            if state == "unrelated":
                return DeploymentReconciliation(
                    "deployment_status_unverified"
                )
            result["deployment_record_found"] = True
            if state == "success":
                result["deployment_record_complete"] = True
                result["deployment_record_successful"] = True
                result["azure_mutation_made"] = True
                return DeploymentReconciliation("success")
            if state == "failed":
                result["deployment_record_complete"] = True
                result["azure_mutation_made"] = True
                return DeploymentReconciliation("deployment_failed")
        if attempt + 1 >= DEPLOYMENT_STATUS_MAX_ATTEMPTS:
            break
        now = time.monotonic()
        if now >= deadline:
            break
        time.sleep(
            min(
                DEPLOYMENT_STATUS_BACKOFF_SECONDS,
                deadline - now,
            )
        )
    result["azure_mutation_made"] = None
    return DeploymentReconciliation(
        "deployment_status_unverified",
        retry_permitted=(
            valid_status_observations > 0
            and baseline_unchanged
            and not possible_current_record_observed
        ),
    )


def _command_timed_out(outcome: CommandResult) -> bool:
    return bool(
        getattr(outcome, "timed_out", False)
        or outcome.return_code == TIMEOUT_RETURN_CODE
    )


def _apply_reconciliation(
    result: dict[str, object],
    reconciliation: DeploymentReconciliation,
) -> dict[str, object]:
    result["category"] = reconciliation.category
    result["ok"] = reconciliation.category == "success"
    if reconciliation.category == "success":
        result["deployment_accepted"] = True
        result["recommended_next_step"] = (
            "OneDeploy completion was reconciled after an ambiguous local "
            "command result; verify the exact hosted artifact."
        )
    return result


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
        baseline = _acquire_deployment_baseline(
            request,
            runner=command_runner,
        )
        result["deployment_baseline_checked"] = baseline.checked
        result["deployment_baseline_attempt_count"] = (
            baseline.attempt_count
        )
        result["deployment_status_checked"] = baseline.checked
        if baseline.ids is None:
            result["ok"] = False
            result["category"] = baseline.category
            return result
        baseline_ids = baseline.ids
        result["deployment_baseline_ready"] = True

        result["azure_command_attempted"] = True
        attempt_started_at = datetime.now(timezone.utc)
        deployment_command = _deployment_command(
            request,
            deployment_artifact.path,
        )
        reconciliation_deadline = (
            time.monotonic() + DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS
        )
        outcome = command_runner.run(deployment_command)
        result["deployment_command_timed_out"] = _command_timed_out(outcome)
        if outcome.return_code == 127:
            result["ok"] = False
            result["category"] = "cli_unavailable"
            return result
        if _authorization_failure(outcome.stderr):
            result["ok"] = False
            result["category"] = "authentication_or_authorization_failed"
            return result

        result["azure_mutation_made"] = None
        expected_deployment_id = _deployment_submission_identifier(outcome)
        reconciliation = _reconcile_ambiguous_deployment(
            request,
            runner=command_runner,
            baseline_ids=baseline_ids,
            attempt_started_at=attempt_started_at,
            result=result,
            deadline=reconciliation_deadline,
            expected_deployment_id=expected_deployment_id,
        )
        return _apply_reconciliation(result, reconciliation)
    finally:
        if deployment_artifact is not None:
            discard_immutable_deployment_artifact(deployment_artifact)


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
