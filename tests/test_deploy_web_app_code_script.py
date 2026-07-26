import json
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
    received = received_time or datetime.now(timezone.utc)
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
        baseline: list[dict[str, object]] | None = None,
        status_results: list[script.CommandResult] | None = None,
    ) -> None:
        self.deployment_result = deployment_result
        self.baseline = baseline or []
        self.status_results = list(status_results or [])
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
            if self._status_reads == 1:
                return script.CommandResult(
                    0,
                    json.dumps(self.baseline),
                    "",
                )
            if self.status_results:
                return self.status_results.pop(0)
            return script.CommandResult(0, "[]", "")
        if args[:3] == ["az", "webapp", "deploy"]:
            path = Path(args[args.index("--src-path") + 1])
            self.deployment_bytes = path.read_bytes()
            self.deployment_mode = os.stat(path).st_mode & 0o777
            return self.deployment_result
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

    assert len(runner.calls) == 2
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
        "--output",
        "none",
    ]
    assert deployment_path.name == "nurse-intake-web-app.zip"
    assert deployment_path.parent.parent.name == "deployments"
    assert runner.deployment_bytes
    assert runner.deployment_mode == 0o400
    assert deployment_path.exists() is False
    assert result["ok"] is True
    assert result["azure_command_attempted"] is True
    assert result["deployment_accepted"] is True
    assert result["hosted_application_verified"] is False


def test_timeout_recovers_from_one_exact_current_successful_onedeploy_record(
    source_tree: Path,
) -> None:
    current = _deployment_record("current-deployment")
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", ""),
        baseline=[_deployment_record("older-deployment")],
        status_results=[
            script.CommandResult(0, json.dumps([current]), ""),
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
    assert len(runner.calls) == 3


def test_timeout_reconciles_same_current_deployment_pending_for_five_minutes(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeReconciliationClock()
    monkeypatch.setattr(script.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(script.time, "sleep", clock.sleep)
    received = datetime.now(timezone.utc)
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
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", "", timed_out=True),
        baseline=[_deployment_record("older-deployment")],
        status_results=[
            *[
                script.CommandResult(0, json.dumps([pending]), "")
                for _ in range(30)
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


def test_timeout_without_current_authoritative_record_stays_fail_closed(
    source_tree: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script,
        "DEPLOYMENT_STATUS_MAX_ATTEMPTS",
        1,
        raising=False,
    )
    runner = DeploymentBoundaryRunner(
        script.CommandResult(124, "", ""),
        baseline=[_deployment_record("older-deployment")],
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

    assert result["ok"] is False
    assert result["category"] == "deployment_status_unverified"
    assert result["deployment_accepted"] is False
    assert result["deployment_command_timed_out"] is True
    assert result["deployment_status_checked"] is True
    assert result["deployment_record_found"] is False
    assert result["azure_mutation_made"] is None


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
