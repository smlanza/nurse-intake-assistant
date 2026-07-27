import json
import inspect
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys

import pytest

import scripts.deploy_web_app_code as script
from src.app.services import bounded_subprocess
from src.app.services.web_app_package import (
    WebAppPackage,
    build_web_app_package,
    create_package_authorization_session,
)


class FakeRunner:
    def __init__(self, result: script.CommandResult | None = None) -> None:
        self.result = result or script.CommandResult(0, "sensitive stdout", "")
        self.calls: list[list[str]] = []
        self.deployment_bytes: bytes | None = None
        self.deployment_mode: int | None = None
        self.deployment_mode: int | None = None

    def run(self, args: list[str]) -> script.CommandResult:
        assert isinstance(args, list)
        self.calls.append(args)
        if "--src-path" in args:
            path = Path(args[args.index("--src-path") + 1])
            self.deployment_bytes = path.read_bytes()
            self.deployment_mode = os.stat(path).st_mode & 0o777
        return self.result


def _deployment_record(
    deployment_id: str,
    *,
    status: int = 4,
    complete: bool = True,
    received_time: datetime | None = None,
    deployer: str = "OneDeploy",
    site_name: str = "fictional-web-app",
) -> dict[str, object]:
    received = received_time or (
        datetime.now(timezone.utc) + timedelta(seconds=1)
    )
    return {
        "id": deployment_id,
        "status": status,
        "complete": complete,
        "deployer": deployer,
        "siteName": site_name,
        "receivedTime": received.isoformat().replace("+00:00", "Z"),
        "startTime": received.isoformat().replace("+00:00", "Z"),
        "endTime": (
            (received + timedelta(seconds=1)).isoformat().replace(
                "+00:00",
                "Z",
            )
            if complete
            else None
        ),
    }


class DeploymentBoundaryRunner:
    def __init__(
        self,
        deployment_result: script.CommandResult,
        *,
        deployment_results: list[script.CommandResult] | None = None,
        baseline_results: list[script.CommandResult] | None = None,
        baseline: list[dict[str, object]] | None = None,
        status_results: list[script.CommandResult] | None = None,
        auto_terminal_success: bool = True,
    ) -> None:
        self.deployment_result = deployment_result
        self.deployment_results = list(deployment_results or [])
        self.baseline_results = list(baseline_results or [])
        self.baseline = baseline or []
        self.status_results = list(status_results or [])
        self.auto_terminal_success = auto_terminal_success
        self.auto_terminal_record: dict[str, object] | None = None
        self.calls: list[list[str]] = []
        self.deployment_bytes: bytes | None = None
        self._status_reads = 0

    def run(self, args: list[str]) -> script.CommandResult:
        self.calls.append(args)
        if args[:5] == [
            "az",
            "webapp",
            "log",
            "deployment",
            "list",
        ]:
            self._status_reads += 1
            if self.baseline_results:
                result = self.baseline_results.pop(0)
                if result.return_code == 0:
                    try:
                        payload = json.loads(result.stdout)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, list):
                        self.baseline = payload
                return result
            if self._status_reads == 1:
                return script.CommandResult(
                    0,
                    json.dumps(self.baseline),
                    "",
                )
            if self.status_results:
                return self.status_results.pop(0)
            if self.auto_terminal_record is not None:
                return script.CommandResult(
                    0,
                    json.dumps([*self.baseline, self.auto_terminal_record]),
                    "",
                )
            return script.CommandResult(0, "[]", "")
        if args[:3] == ["az", "webapp", "deploy"]:
            path = Path(args[args.index("--src-path") + 1])
            self.deployment_bytes = path.read_bytes()
            self.deployment_mode = os.stat(path).st_mode & 0o777
            if self.deployment_results:
                result = self.deployment_results.pop(0)
            else:
                result = self.deployment_result
            if result.return_code == 0 and self.auto_terminal_success:
                deployment_id = result.stdout.strip() or "current-deployment"
                self.auto_terminal_record = _deployment_record(deployment_id)
            return result
        raise AssertionError(f"Unexpected command: {args}")


class FakeReconciliationClock:
    def __init__(self) -> None:
        self.elapsed_seconds = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.elapsed_seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.elapsed_seconds += seconds


@pytest.fixture
def source_tree(tmp_path: Path) -> Path:
    for relative_path, content in {
        "requirements.txt": "fastapi\nuvicorn[standard]\n",
        "src/__init__.py": "",
        "src/app/main.py": "app_name = 'deploy-cli-fixture'\n",
        "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py": (
            "from src.app.operations import verify_hosted_foundry_agent\n"
        ),
    }.items():
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return tmp_path


def test_check_and_package_modes_make_no_azure_command(source_tree: Path) -> None:
    for mode in ("check", "package"):
        runner = FakeRunner()
        result = script.execute(
            script.DeploymentRequest(mode=mode),
            runner=runner,
            source_root=source_tree,
        )
        assert result["ok"] is True
        assert result["azure_command_attempted"] is False
        assert result["deployment_accepted"] is False
        assert result["deployment_baseline_checked"] is False
        assert result["deployment_baseline_ready"] is False
        assert result["deployment_baseline_attempt_count"] == 0
        assert result["hosted_application_verified"] is False
        assert runner.calls == []


def test_live_requires_explicit_resource_group_web_app_and_json() -> None:
    with pytest.raises(SystemExit):
        script.main(["--live", "--json"])
    with pytest.raises(SystemExit):
        script.main(["--live", "--resource-group", "rg", "--web-app", "app"])


def test_live_uses_one_narrow_discrete_azure_deployment_command(
    source_tree: Path,
) -> None:
    runner = DeploymentBoundaryRunner(script.CommandResult(0, "", ""))
    result = script.execute(
        script.DeploymentRequest(
            mode="live",
            resource_group="fictional-rg",
            web_app_name="fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert len(runner.calls) == 3
    assert runner.calls[0][:5] == [
        "az",
        "webapp",
        "log",
        "deployment",
        "list",
    ]
    call = runner.calls[1]
    deployment_path = Path(call[call.index("--src-path") + 1])
    assert call[: call.index("--src-path") + 1] == [
        "az",
        "webapp",
        "deploy",
        "--resource-group",
        "fictional-rg",
        "--name",
        "fictional-web-app",
        "--src-path",
    ]
    assert call[call.index("--src-path") + 2 :] == [
        "--type",
        "zip",
        "--clean",
        "true",
        "--restart",
        "true",
        "--track-status",
        "false",
        "--timeout",
        str(script.AZURE_DEPLOYMENT_OPERATION_TIMEOUT_MS),
        "--query",
        "id",
        "--output",
        "tsv",
    ]
    assert deployment_path.name == "nurse-intake-web-app.zip"
    assert deployment_path.parent.parent.name == "deployments"
    assert runner.deployment_bytes
    assert runner.deployment_mode == 0o400
    assert deployment_path.exists() is False
    assert result["ok"] is True
    assert result["azure_command_attempted"] is True
    assert result["deployment_accepted"] is True
    assert result["deployment_baseline_checked"] is True
    assert result["deployment_baseline_ready"] is True
    assert result["deployment_baseline_attempt_count"] == 1
    assert result["deployment_retry_attempted"] is False
    assert result["hosted_application_verified"] is False
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_empty_baseline_is_ready_immediately_without_sleep(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script.time,
        "sleep",
        lambda _seconds: pytest.fail("baseline must not sleep"),
    )
    runner = DeploymentBoundaryRunner(script.CommandResult(0, "", ""))

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["deployment_baseline_checked"] is True
    assert result["deployment_baseline_ready"] is True
    assert result["deployment_baseline_attempt_count"] == 1
    assert sum(
        call[:5]
        == ["az", "webapp", "log", "deployment", "list"]
        for call in runner.calls
    ) == 2
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_existing_baseline_ids_remain_frozen_during_reconciliation(
    source_tree: Path,
) -> None:
    baseline = _deployment_record("baseline-deployment")
    current = _deployment_record("current-deployment")
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline=[baseline],
        status_results=[
            script.CommandResult(
                0,
                json.dumps([baseline, current]),
                "",
            ),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["deployment_baseline_ready"] is True
    assert result["deployment_baseline_attempt_count"] == 1
    assert result["deployment_record_found"] is True
    assert result["deployment_retry_attempted"] is False
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_transient_baseline_failure_then_empty_baseline_proceeds_once(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "", ""),
        baseline_results=[
            script.CommandResult(
                1,
                "",
                "SCM deployment history returned 503 Service Unavailable",
            ),
            script.CommandResult(0, "[]", ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["deployment_baseline_checked"] is True
    assert result["deployment_baseline_ready"] is True
    assert result["deployment_baseline_attempt_count"] == 2
    assert clock.sleeps == [script.DEPLOYMENT_BASELINE_BACKOFF_SECONDS]
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_several_transient_baseline_failures_then_valid_baseline_proceeds(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    transient = script.CommandResult(
        1,
        "",
        "SCM deployment history connection refused",
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "", ""),
        baseline_results=[
            transient,
            transient,
            transient,
            script.CommandResult(
                0,
                json.dumps([_deployment_record("existing")]),
                "",
            ),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["deployment_baseline_ready"] is True
    assert result["deployment_baseline_attempt_count"] == 4
    assert clock.sleeps == [
        script.DEPLOYMENT_BASELINE_BACKOFF_SECONDS
    ] * 3
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_transient_baseline_failures_exhaust_attempt_limit_without_deploy(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script, "DEPLOYMENT_BASELINE_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    transient = script.CommandResult(
        124,
        "",
        "",
        timed_out=True,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "", ""),
        baseline_results=[transient, transient, transient],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == "deployment_baseline_unavailable"
    assert result["deployment_baseline_checked"] is True
    assert result["deployment_baseline_ready"] is False
    assert result["deployment_baseline_attempt_count"] == 3
    assert result["azure_command_attempted"] is False
    assert result["deployment_accepted"] is False
    assert result["deployment_retry_attempted"] is False
    assert result["azure_mutation_made"] is False
    assert clock.sleeps == [
        script.DEPLOYMENT_BASELINE_BACKOFF_SECONDS
    ] * 2
    assert not any(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    )


def test_transient_baseline_failures_exhaust_elapsed_limit_without_final_sleep(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script, "DEPLOYMENT_BASELINE_MAX_ATTEMPTS", 10)
    monkeypatch.setattr(
        script,
        "DEPLOYMENT_BASELINE_MAX_ELAPSED_SECONDS",
        15.0,
    )
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    transient = script.CommandResult(
        1,
        "",
        "SCM deployment history returned 429 Too Many Requests",
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "", ""),
        baseline_results=[transient] * 10,
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_baseline_unavailable"
    assert result["deployment_baseline_attempt_count"] == 2
    assert result["azure_command_attempted"] is False
    assert clock.sleeps == [script.DEPLOYMENT_BASELINE_BACKOFF_SECONDS]
    assert clock.elapsed_seconds == pytest.approx(
        script.DEPLOYMENT_BASELINE_BACKOFF_SECONDS
    )
    assert not any(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    )


@pytest.mark.parametrize(
    ("baseline_outcome", "category"),
    (
        (
            script.CommandResult(1, "", "Authorization failed"),
            "authentication_or_authorization_failed",
        ),
        (
            script.CommandResult(127, "", "az executable not found"),
            "cli_unavailable",
        ),
        (
            script.CommandResult(2, "", "invalid resource name"),
            "deployment_baseline_failed",
        ),
    ),
    ids=("authorization", "cli-unavailable", "nontransient"),
)
def test_terminal_baseline_failure_never_retries_or_deploys(
    source_tree: Path,
    baseline_outcome: script.CommandResult,
    category: str,
) -> None:
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "", ""),
        baseline_results=[baseline_outcome],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == category
    assert result["deployment_baseline_checked"] is True
    assert result["deployment_baseline_ready"] is False
    assert result["deployment_baseline_attempt_count"] == 1
    assert result["azure_command_attempted"] is False
    assert result["deployment_retry_attempted"] is False
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    "stdout",
    (
        "{malformed",
        '{"id": "not-a-list"}',
        json.dumps([{"status": 4}]),
        json.dumps(
            [
                {"id": "duplicate"},
                {"id": "duplicate"},
            ]
        ),
    ),
    ids=(
        "malformed-json",
        "json-object",
        "malformed-id",
        "duplicate-id",
    ),
)
def test_malformed_baseline_fails_closed_without_retry_or_deploy(
    source_tree: Path,
    stdout: str,
) -> None:
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "", ""),
        baseline_results=[script.CommandResult(0, stdout, "")],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == "deployment_status_malformed"
    assert result["deployment_baseline_attempt_count"] == 1
    assert result["deployment_baseline_ready"] is False
    assert result["azure_command_attempted"] is False
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    "outcome",
    (
        script.CommandResult(124, "", "", timed_out=True),
        script.CommandResult(
            1,
            "",
            "SCM deployment endpoint returned 404 Not Found",
        ),
        script.CommandResult(
            1,
            "",
            "SCM deployment history returned 409 Conflict",
        ),
        script.CommandResult(
            1,
            "",
            "SCM deployment history returned 429 Too Many Requests",
        ),
        script.CommandResult(1, "", "HTTP 500 Internal Server Error"),
        script.CommandResult(1, "", "HTTP 502 Bad Gateway"),
        script.CommandResult(1, "", "HTTP 503 Service Unavailable"),
        script.CommandResult(1, "", "HTTP 504 Gateway Timeout"),
        script.CommandResult(1, "", "HTTP status 599"),
        script.CommandResult(1, "", "connection reset by peer"),
        script.CommandResult(1, "", "connection refused"),
        script.CommandResult(1, "", "read timed out"),
        script.CommandResult(1, "", "temporarily unavailable"),
    ),
    ids=(
        "timeout",
        "scm-404",
        "conflict-409",
        "rate-limit-429",
        "http-500",
        "http-502",
        "http-503",
        "http-504",
        "http-599",
        "connection-reset",
        "connection-refused",
        "read-timeout",
        "temporarily-unavailable",
    ),
)
def test_baseline_transient_classifier_accepts_only_enumerated_evidence(
    outcome: script.CommandResult,
) -> None:
    assert script._deployment_baseline_failure_is_transient(outcome) is True


@pytest.mark.parametrize(
    "outcome",
    (
        script.CommandResult(
            124,
            "",
            "Authorization failed",
            timed_out=True,
        ),
        script.CommandResult(127, "", "executable not found"),
        script.CommandResult(2, "", "unrecognized arguments"),
        script.CommandResult(2, "", "invalid resource name"),
        script.CommandResult(1, "", "ResourceGroupNotFound"),
        script.CommandResult(1, "", "404 Resource Not Found"),
        script.CommandResult(1, "", "deployment command failed"),
    ),
    ids=(
        "authorization-even-with-timeout",
        "cli-unavailable",
        "invalid-arguments",
        "invalid-resource",
        "resource-group-not-found",
        "generic-404",
        "generic-failure",
    ),
)
def test_baseline_transient_classifier_rejects_terminal_evidence(
    outcome: script.CommandResult,
) -> None:
    assert script._deployment_baseline_failure_is_transient(outcome) is False


def test_timeout_recovers_from_one_exact_current_successful_onedeploy_record(
    source_tree: Path,
) -> None:
    current = _deployment_record("current-deployment")
    older = _deployment_record("older-deployment")
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", ""),
        baseline=[older],
        status_results=[
            script.CommandResult(0, json.dumps([older, current]), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["deployment_accepted"] is True
    assert result["deployment_command_timed_out"] is True
    assert result["deployment_status_checked"] is True
    assert result["deployment_record_found"] is True
    assert result["deployment_record_complete"] is True
    assert result["deployment_record_successful"] is True
    assert result["azure_mutation_made"] is True
    assert result["deployment_retry_attempted"] is False
    assert len(runner.calls) == 3


def test_timeout_reconciles_same_current_deployment_pending_for_five_minutes(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    received = datetime.now(timezone.utc) + timedelta(seconds=1)
    pending = _deployment_record(
        "current-five-minute-deployment",
        status=2,
        complete=False,
        received_time=received,
    )
    successful = _deployment_record(
        "current-five-minute-deployment",
        received_time=received,
    )
    older = _deployment_record("older-deployment")
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline=[older],
        status_results=[
            *[
                script.CommandResult(0, json.dumps([older, pending]), "")
                for _ in range(30)
            ],
            script.CommandResult(0, json.dumps([older, successful]), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["category"] == "success"
    assert result["deployment_accepted"] is True
    assert result["deployment_record_found"] is True
    assert result["deployment_record_complete"] is True
    assert result["deployment_record_successful"] is True
    assert result["azure_mutation_made"] is True
    assert clock.elapsed_seconds == pytest.approx(300.0)
    assert len(clock.sleeps) == 30
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_reconciliation_accepts_terminal_success_after_old_window_before_ten_minutes(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    received = datetime.now(timezone.utc) + timedelta(seconds=1)
    pending = _deployment_record(
        "slow-current-deployment",
        status=2,
        complete=False,
        received_time=received,
    )
    successful = _deployment_record(
        "slow-current-deployment",
        received_time=received,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline_results=[
            script.CommandResult(0, "[]", ""),
        ],
        status_results=[
            *[
                script.CommandResult(0, json.dumps([pending]), "")
                for _ in range(40)
            ],
            script.CommandResult(0, json.dumps([successful]), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["category"] == "success"
    assert result["deployment_accepted"] is True
    assert result["deployment_record_successful"] is True
    assert result["deployment_retry_attempted"] is False
    assert clock.elapsed_seconds == pytest.approx(400.0)
    assert len(clock.sleeps) == 40
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_reconciliation_without_record_expires_at_ten_minute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
    )
    result = script._base(request, "success", True)

    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=runner,
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS,
    )

    assert reconciliation.category == "deployment_status_unverified"
    assert reconciliation.retry_permitted is True
    assert clock.elapsed_seconds == pytest.approx(600.0)
    assert clock.sleeps == [
        script.DEPLOYMENT_STATUS_BACKOFF_SECONDS
    ] * 60


def test_slow_status_query_consumes_reconciliation_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )

    class SlowStatusRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run(self, args: list[str]) -> script.CommandResult:
            assert args[:5] == [
                "az",
                "webapp",
                "log",
                "deployment",
                "list",
            ]
            self.calls += 1
            clock.elapsed_seconds += 595.0
            return script.CommandResult(0, "[]", "")

    runner = SlowStatusRunner()
    result = script._base(request, "success", True)

    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=runner,
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS,
    )

    assert reconciliation.category == "deployment_status_unverified"
    assert reconciliation.retry_permitted is True
    assert runner.calls == 1
    assert clock.elapsed_seconds == pytest.approx(600.0)
    assert clock.sleeps == [5.0]


def test_reconciliation_absolute_deadline_caps_slow_history_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    request = script.DeploymentRequest("live", "fictional-rg", "fictional-web-app")

    class DeadlineRunner:
        def __init__(self) -> None:
            self.starts: list[float] = []
            self.timeouts: list[float] = []

        def run_with_timeout(
            self,
            args: list[str],
            *,
            timeout_seconds: float,
        ) -> script.CommandResult:
            assert args[:5] == ["az", "webapp", "log", "deployment", "list"]
            self.starts.append(clock.elapsed_seconds)
            self.timeouts.append(timeout_seconds)
            clock.elapsed_seconds += min(2.0, timeout_seconds)
            return script.CommandResult(0, "[]", "")

    runner = DeadlineRunner()
    result = script._base(request, "success", True)

    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=runner,
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS,
        expected_deployment_id=None,
    )

    assert reconciliation.category == "deployment_status_unverified"
    assert clock.elapsed_seconds <= script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS
    assert runner.starts
    assert all(
        start < script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS
        for start in runner.starts
    )
    assert all(
        timeout <= script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS - start
        for start, timeout in zip(runner.starts, runner.timeouts, strict=True)
    )


@pytest.mark.parametrize("return_time", (10.0, 11.0))
def test_terminal_success_returned_at_or_after_deadline_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
    return_time: float,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(
        script.time,
        "sleep",
        lambda _seconds: pytest.fail("late terminal evidence must not sleep"),
    )
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )
    deployment_id = "late-current-command"
    record = _deployment_record(deployment_id)

    class LateTerminalRunner:
        def run_with_timeout(
            self,
            _args: list[str],
            *,
            timeout_seconds: float,
        ) -> script.CommandResult:
            assert clock.elapsed_seconds < 10.0
            assert timeout_seconds == pytest.approx(10.0)
            clock.elapsed_seconds = return_time
            return script.CommandResult(0, json.dumps([record]), "")

    result = script._base(request, "success", True)
    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=LateTerminalRunner(),
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=10.0,
        expected_deployment_id=deployment_id,
    )

    assert reconciliation.category == "deployment_status_unverified"
    assert result["deployment_record_found"] is False
    assert result["deployment_record_complete"] is False
    assert result["deployment_record_successful"] is False
    assert result["azure_mutation_made"] is None
    serialized = json.dumps(result)
    assert deployment_id not in serialized


def test_terminal_failure_returned_at_deadline_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )
    deployment_id = "late-failed-current-command"
    record = _deployment_record(deployment_id, status=3)

    class LateTerminalRunner:
        def run_with_timeout(
            self,
            _args: list[str],
            *,
            timeout_seconds: float,
        ) -> script.CommandResult:
            assert timeout_seconds == pytest.approx(10.0)
            clock.elapsed_seconds = 10.0
            return script.CommandResult(0, json.dumps([record]), "")

    result = script._base(request, "success", True)
    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=LateTerminalRunner(),
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=10.0,
        expected_deployment_id=deployment_id,
    )

    assert reconciliation.category == "deployment_status_unverified"
    assert result["deployment_record_found"] is False
    assert result["deployment_record_complete"] is False
    assert result["azure_mutation_made"] is None


def test_history_returned_at_deadline_is_not_parsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(
        script,
        "_deployment_records",
        lambda _outcome: pytest.fail("late history must not be parsed"),
    )
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )

    class DeadlineRunner:
        def run_with_timeout(
            self,
            _args: list[str],
            *,
            timeout_seconds: float,
        ) -> script.CommandResult:
            clock.elapsed_seconds += timeout_seconds
            return script.CommandResult(0, "sensitive late output", "")

    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=DeadlineRunner(),
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=script._base(request, "success", True),
        deadline=10.0,
        expected_deployment_id="current-command",
    )

    assert reconciliation.category == "deployment_status_unverified"


def test_terminal_success_returned_before_deadline_remains_acceptable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )
    deployment_id = "timely-current-command"
    record = _deployment_record(deployment_id)

    class TimelyTerminalRunner:
        def run_with_timeout(
            self,
            _args: list[str],
            *,
            timeout_seconds: float,
        ) -> script.CommandResult:
            assert timeout_seconds == pytest.approx(10.0)
            clock.elapsed_seconds = 9.999
            return script.CommandResult(0, json.dumps([record]), "")

    result = script._base(request, "success", True)
    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=TimelyTerminalRunner(),
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=10.0,
        expected_deployment_id=deployment_id,
    )

    assert reconciliation.category == "success"
    assert result["deployment_record_successful"] is True


def test_reconciliation_requires_an_explicit_absolute_deadline() -> None:
    deadline_parameter = inspect.signature(
        script._reconcile_ambiguous_deployment
    ).parameters["deadline"]

    assert deadline_parameter.default is inspect.Parameter.empty
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )
    with pytest.raises(TypeError):
        script._reconcile_ambiguous_deployment(
            request,
            runner=FakeRunner(),
            baseline_ids=frozenset(),
            attempt_started_at=datetime.now(timezone.utc),
            result=script._base(request, "success", True),
        )


@pytest.mark.parametrize(
    "submission_result",
    (
        script.CommandResult(0, "current-command", ""),
        script.CommandResult(124, "", "", timed_out=True),
    ),
    ids=("accepted-submission", "ambiguous-submission"),
)
def test_all_submission_outcomes_propagate_the_original_absolute_deadline(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    submission_result: script.CommandResult,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    runner = DeploymentBoundaryRunner(
        submission_result,
        auto_terminal_success=False,
    )
    original_run = runner.run

    def run(args: list[str]) -> script.CommandResult:
        outcome = original_run(args)
        if args[:3] == ["az", "webapp", "deploy"]:
            clock.elapsed_seconds += 2.0
        return outcome

    monkeypatch.setattr(runner, "run", run)
    observed_deadlines: list[float] = []

    def reconcile(
        _request,
        *,
        runner,
        baseline_ids,
        attempt_started_at,
        result,
        deadline,
        expected_deployment_id,
    ) -> script.DeploymentReconciliation:
        del (
            runner,
            baseline_ids,
            attempt_started_at,
            result,
            expected_deployment_id,
        )
        observed_deadlines.append(deadline)
        return script.DeploymentReconciliation(
            "deployment_status_unverified"
        )

    monkeypatch.setattr(
        script,
        "_reconcile_ambiguous_deployment",
        reconcile,
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert observed_deadlines == [
        script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS
    ]
    assert clock.elapsed_seconds == pytest.approx(2.0)


def test_reconciliation_does_not_read_at_exact_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    clock.elapsed_seconds = 600.0
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(
        script.time,
        "sleep",
        lambda _seconds: pytest.fail("deadline exhaustion must not sleep"),
    )
    request = script.DeploymentRequest("live", "fictional-rg", "fictional-web-app")

    class NoCallRunner:
        def run(self, _args: list[str]) -> script.CommandResult:
            pytest.fail("history read must not begin at the deadline")

    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=NoCallRunner(),
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=script._base(request, "success", True),
        deadline=600.0,
        expected_deployment_id=None,
    )

    assert reconciliation.category == "deployment_status_unverified"


def test_sleeping_to_deadline_does_not_permit_an_extra_history_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    request = script.DeploymentRequest("live", "fictional-rg", "fictional-web-app")

    class CountingRunner:
        def __init__(self) -> None:
            self.calls = 0

        def run_with_timeout(
            self,
            _args: list[str],
            *,
            timeout_seconds: float,
        ) -> script.CommandResult:
            self.calls += 1
            assert timeout_seconds == pytest.approx(10.0)
            return script.CommandResult(0, "[]", "")

    runner = CountingRunner()
    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=runner,
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=script._base(request, "success", True),
        deadline=10.0,
        expected_deployment_id=None,
    )

    assert reconciliation.category == "deployment_status_unverified"
    assert runner.calls == 1
    assert clock.elapsed_seconds == pytest.approx(10.0)
    assert clock.sleeps == [10.0]


def test_terminal_history_requires_exact_submission_identifier(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "DEPLOYMENT_STATUS_MAX_ATTEMPTS", 1)
    exact_id = "current-command-deployment"
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, exact_id, ""),
        status_results=[
            script.CommandResult(
                0,
                json.dumps([_deployment_record(exact_id)]),
                "",
            )
        ],
    )

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-web-app"),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is True
    assert result["deployment_accepted"] is True
    assert result["deployment_record_complete"] is True
    assert result["deployment_record_successful"] is True
    serialized = json.dumps(result)
    assert exact_id not in serialized
    assert "receivedTime" not in serialized
    assert "startTime" not in serialized
    assert "endTime" not in serialized


def test_zero_exit_without_terminal_history_does_not_prove_deployment(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "DEPLOYMENT_STATUS_MAX_ATTEMPTS", 1)
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "", ""),
        auto_terminal_success=False,
    )

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-web-app"),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_pre_request_record_inside_former_clock_skew_is_rejected(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "DEPLOYMENT_STATUS_MAX_ATTEMPTS", 1)
    exact_id = "pre-request-deployment"
    record = _deployment_record(
        exact_id,
        received_time=datetime.now(timezone.utc) - timedelta(seconds=30),
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, exact_id, ""),
        status_results=[script.CommandResult(0, json.dumps([record]), "")],
    )

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-web-app"),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False


def test_newest_same_site_success_without_exact_correlation_is_rejected(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "DEPLOYMENT_STATUS_MAX_ATTEMPTS", 1)
    runner = DeploymentBoundaryRunner(
        script.CommandResult(0, "expected-current-command", ""),
        status_results=[
            script.CommandResult(
                0,
                json.dumps([_deployment_record("newest-unrelated-success")]),
                "",
            )
        ],
    )

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-web-app"),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False


def test_reconciliation_stops_on_terminal_failure_after_old_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )
    received = datetime.now(timezone.utc) + timedelta(seconds=1)
    pending = _deployment_record(
        "slow-failed-deployment",
        status=2,
        complete=False,
        received_time=received,
    )
    failed = _deployment_record(
        "slow-failed-deployment",
        status=3,
        received_time=received,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline_results=[
            *[
                script.CommandResult(0, json.dumps([pending]), "")
                for _ in range(40)
            ],
            script.CommandResult(0, json.dumps([failed]), ""),
        ],
    )
    result = script._base(request, "success", True)

    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=runner,
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS,
    )

    assert reconciliation.category == "deployment_failed"
    assert reconciliation.retry_permitted is False
    assert result["deployment_record_complete"] is True
    assert result["deployment_record_successful"] is False
    assert clock.elapsed_seconds == pytest.approx(400.0)
    assert len(clock.sleeps) == 40


def test_reconciliation_never_accepts_unrelated_success_during_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    request = script.DeploymentRequest(
        "live",
        "fictional-rg",
        "fictional-web-app",
    )
    pending = _deployment_record(
        "current-pending",
        status=2,
        complete=False,
    )
    unrelated = _deployment_record(
        "unrelated-success",
        site_name="another-web-app",
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline_results=[
            script.CommandResult(0, json.dumps([pending]), ""),
            script.CommandResult(0, json.dumps([unrelated]), ""),
        ],
    )
    result = script._base(request, "success", True)

    reconciliation = script._reconcile_ambiguous_deployment(
        request,
        runner=runner,
        baseline_ids=frozenset(),
        attempt_started_at=datetime.now(timezone.utc),
        result=result,
        deadline=script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS,
    )

    assert reconciliation.category == "deployment_status_malformed"
    assert reconciliation.retry_permitted is False
    assert result["deployment_record_successful"] is False
    assert clock.sleeps == [
        script.DEPLOYMENT_STATUS_BACKOFF_SECONDS
    ]


@pytest.mark.parametrize(
    "initial_result",
    (
        script.CommandResult(124, "", "", timed_out=True),
        script.CommandResult(1, "", "ambiguous sanitized failure"),
    ),
    ids=("timeout", "ambiguous-nonzero"),
)
def test_ambiguous_submission_uses_one_deadline_and_never_redeploys(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_result: script.CommandResult,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    runner = DeploymentBoundaryRunner(
        initial_result,
        deployment_results=[
            initial_result,
            script.CommandResult(0, "", ""),
        ],
        baseline=[_deployment_record("older-deployment")],
        status_results=[
            script.CommandResult(
                0,
                json.dumps([_deployment_record("older-deployment")]),
                "",
            )
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False
    assert result["azure_command_attempted"] is True
    assert result["deployment_retry_attempted"] is False
    assert result["deployment_command_timed_out"] is initial_result.timed_out
    assert result["deployment_status_checked"] is True
    assert result["deployment_record_found"] is False
    assert result["azure_mutation_made"] is None
    assert clock.elapsed_seconds == pytest.approx(
        script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS
    )
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_timeout_pending_current_deployment_exhausts_bounded_deadline(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    pending = _deployment_record(
        "current-still-pending",
        status=2,
        complete=False,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        status_results=[
            script.CommandResult(0, json.dumps([pending]), "")
            for _ in range(script.DEPLOYMENT_STATUS_MAX_ATTEMPTS)
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False
    assert result["deployment_record_found"] is True
    assert result["deployment_record_complete"] is False
    assert result["deployment_record_successful"] is False
    assert result["azure_mutation_made"] is None
    assert result["deployment_retry_attempted"] is False
    assert clock.elapsed_seconds == pytest.approx(
        script.DEPLOYMENT_STATUS_MAX_ELAPSED_SECONDS
    )
    assert len(clock.sleeps) == (
        script.DEPLOYMENT_STATUS_MAX_ATTEMPTS - 1
    )
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


@pytest.mark.parametrize(
    "status_result",
    (
        script.CommandResult(124, "", "", timed_out=True),
        script.CommandResult(1, "", "private inaccessible details"),
        script.CommandResult(0, "{malformed", ""),
        script.CommandResult(
            0,
            json.dumps(
                [
                    _deployment_record(
                        "current-incomplete",
                        status=2,
                        complete=False,
                    )
                ]
            ),
            "",
        ),
    ),
    ids=(
        "status-timeout",
        "status-inaccessible",
        "status-malformed",
        "status-incomplete",
    ),
)
def test_timeout_reconciliation_failures_remain_bounded_and_unaccepted(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
    status_result: script.CommandResult,
) -> None:
    monkeypatch.setattr(
        script,
        "DEPLOYMENT_STATUS_MAX_ATTEMPTS",
        1,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        status_results=[status_result],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] in {
        "deployment_status_unverified",
        "deployment_status_malformed",
    }
    assert result["deployment_accepted"] is False
    assert result["azure_mutation_made"] is None
    assert len(runner.calls) == 3


def test_timeout_with_current_completed_failed_record_reports_failure(
    source_tree: Path,
) -> None:
    failed = _deployment_record(
        "current-deployment",
        status=3,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", ""),
        baseline=[],
        status_results=[
            script.CommandResult(0, json.dumps([failed]), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == "deployment_failed"
    assert result["deployment_accepted"] is False
    assert result["deployment_record_found"] is True
    assert result["deployment_record_complete"] is True
    assert result["deployment_record_successful"] is False
    assert result["azure_mutation_made"] is True
    assert result["deployment_retry_attempted"] is False
    assert len(runner.calls) == 3


def test_timeout_rejects_stale_successful_deployment_record(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script,
        "DEPLOYMENT_STATUS_MAX_ATTEMPTS",
        1,
        raising=False,
    )
    stale = _deployment_record(
        "older-deployment",
        received_time=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", ""),
        baseline=[stale],
        status_results=[
            script.CommandResult(0, json.dumps([stale]), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False
    assert result["deployment_record_found"] is False
    assert result["azure_mutation_made"] is None
    assert result["deployment_retry_attempted"] is False
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_timeout_rejects_multiple_plausible_current_deployments(
    source_tree: Path,
) -> None:
    records = [
        _deployment_record("current-a"),
        _deployment_record("current-b"),
    ]
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", ""),
        status_results=[
            script.CommandResult(0, json.dumps(records), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False
    assert result["deployment_record_found"] is False
    assert result["azure_mutation_made"] is None
    assert result["deployment_retry_attempted"] is False


@pytest.mark.parametrize(
    "records",
    (
        [{"status": 4, "complete": True}],
        [_deployment_record("current", status=99)],
        [
            {
                **_deployment_record("current"),
                "receivedTime": None,
                "startTime": None,
            }
        ],
        [
            {
                **_deployment_record("current"),
                "deployer": "unrelated-deployer",
            }
        ],
        [
            {
                **_deployment_record("current"),
                "siteName": "another-web-app",
            }
        ],
    ),
    ids=(
        "missing-id",
        "unknown-status",
        "missing-attempt-time",
        "wrong-deployer",
        "wrong-web-app",
    ),
)
def test_timeout_rejects_malformed_or_unattributable_deployment_records(
    source_tree: Path,
    records: list[dict[str, object]],
) -> None:
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", ""),
        status_results=[
            script.CommandResult(0, json.dumps(records), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] in {
        "deployment_status_malformed",
        "deployment_status_unverified",
    }
    assert result["deployment_accepted"] is False
    assert result["azure_mutation_made"] is None
    assert result["deployment_retry_attempted"] is False


def test_ambiguous_initial_status_authorization_failure_never_retries(
    source_tree: Path,
) -> None:
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        status_results=[
            script.CommandResult(1, "", "Authorization failed"),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["ok"] is False
    assert result["category"] == "authentication_or_authorization_failed"
    assert result["azure_command_attempted"] is True
    assert result["deployment_accepted"] is False
    assert result["deployment_retry_attempted"] is False
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_ambiguous_initial_does_not_retry_if_baseline_disappears(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "DEPLOYMENT_STATUS_MAX_ATTEMPTS", 1)
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline=[_deployment_record("baseline-deployment")],
        status_results=[script.CommandResult(0, "[]", "")],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_retry_attempted"] is False
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_uncorrelated_candidate_is_rejected_if_baseline_disappears(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script, "DEPLOYMENT_STATUS_MAX_ATTEMPTS", 1)
    baseline = _deployment_record("baseline-deployment")
    candidate = _deployment_record("uncorrelated-current-candidate")
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline=[baseline],
        status_results=[
            script.CommandResult(0, json.dumps([candidate]), ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-web-app"),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False
    assert result["deployment_record_successful"] is False
    assert result["deployment_retry_attempted"] is False


def test_ambiguous_initial_never_retries_after_pending_record_disappears(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script, "DEPLOYMENT_STATUS_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    pending = _deployment_record(
        "possible-current-deployment",
        status=2,
        complete=False,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        status_results=[
            script.CommandResult(0, json.dumps([pending]), ""),
            script.CommandResult(0, "[]", ""),
        ],
    )

    result = script.execute(
        script.DeploymentRequest(
            "live",
            "fictional-rg",
            "fictional-web-app",
        ),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_record_found"] is True
    assert result["deployment_retry_attempted"] is False
    assert sum(
        call[:3] == ["az", "webapp", "deploy"]
        for call in runner.calls
    ) == 1


def test_subprocess_runner_times_out_and_reaps_the_child_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[subprocess.Popen[str]] = []
    real_popen = subprocess.Popen

    def tracking_popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(
        bounded_subprocess.subprocess,
        "Popen",
        tracking_popen,
    )
    runner = script.SubprocessCommandRunner(
        timeout_seconds=0.05,
        cleanup_timeout_seconds=0.2,
    )

    result = runner.run(
        [sys.executable, "-c", "import time; time.sleep(60)"]
    )

    assert result.timed_out is True
    assert result.return_code == 124
    assert len(started) == 1
    assert started[0].poll() is not None


@pytest.mark.parametrize(
    ("stderr", "category"),
    [
        ("Please run az login. secret-token", "authentication_or_authorization_failed"),
        ("Raw deployment failure with sensitive detail", "deployment_failed"),
    ],
)
def test_live_failure_is_stable_and_does_not_serialize_cli_output(
    source_tree: Path,
    stderr: str,
    category: str,
) -> None:
    status_results = (
        []
        if category == "authentication_or_authorization_failed"
        else [
            script.CommandResult(
                0,
                json.dumps(
                    [
                        _deployment_record(
                            "current-failed",
                            status=3,
                            site_name="fictional-app",
                        )
                    ]
                ),
                "",
            )
        ]
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(1, "sensitive stdout", stderr),
        status_results=status_results,
    )

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-app"),
        runner=runner,
        source_root=source_tree,
    )

    serialized = json.dumps(result)
    assert result["ok"] is False
    assert result["category"] == category
    assert result["azure_command_attempted"] is True
    assert result["deployment_accepted"] is False
    assert "sensitive stdout" not in serialized
    assert stderr not in serialized
    assert "secret-token" not in serialized


def test_package_failure_never_attempts_deployment(source_tree: Path) -> None:
    (source_tree / "requirements.txt").unlink()
    runner = FakeRunner()

    result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-app"),
        runner=runner,
        source_root=source_tree,
    )

    assert result["category"] == "incomplete_package"
    assert result["package_created"] is False
    assert result["azure_command_attempted"] is False
    assert runner.calls == []


def test_forged_or_stale_prebuilt_package_is_rejected_before_azure(
    source_tree: Path,
) -> None:
    session = create_package_authorization_session()
    built = build_web_app_package(source_tree, authorization_session=session)
    runner = FakeRunner()
    with pytest.raises(TypeError):
        WebAppPackage(
            package_path=built.package_path,
            file_count=built.file_count,
            size_bytes=built.size_bytes,
            sha256=built.sha256,
        )

    (source_tree / "src/app/main.py").write_text("changed = True\n")
    stale_result = script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-app"),
        runner=runner,
        source_root=source_tree,
        prebuilt_package=built,
        authorization_session=session,
    )
    assert stale_result["category"] == "package_proof_invalid"
    assert runner.calls == []


def test_live_command_never_couples_forbidden_operations(source_tree: Path) -> None:
    runner = FakeRunner()
    script.execute(
        script.DeploymentRequest("live", "fictional-rg", "fictional-app"),
        runner=runner,
        source_root=source_tree,
    )

    flattened = " ".join(runner.calls[0]).lower()
    for forbidden in (
        "foundry",
        "role assignment",
        "group delete",
        "webapp delete",
        "appsettings",
        "agent",
        "invoke",
        "deployment group",
    ):
        assert forbidden not in flattened


def test_non_live_success_never_implies_acceptance_or_verification(
    source_tree: Path,
) -> None:
    result = script.execute(
        script.DeploymentRequest("package"),
        runner=FakeRunner(),
        source_root=source_tree,
    )

    assert result["package_created"] is True
    assert result["deployment_accepted"] is False
    assert result["hosted_application_verified"] is False
