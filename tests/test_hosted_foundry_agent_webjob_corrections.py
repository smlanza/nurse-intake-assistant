import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = (
    ROOT / "App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py"
)


def test_staged_entrypoint_imports_only_from_app_service_home(tmp_path: Path) -> None:
    fake_home = tmp_path / "app-service-home"
    app_root = fake_home / "site/wwwroot"
    operation_root = app_root / "src/app/operations"
    operation_root.mkdir(parents=True)
    for relative in ("src/__init__.py", "src/app/__init__.py", "src/app/operations/__init__.py"):
        path = app_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    (operation_root / "verify_hosted_foundry_agent.py").write_text(
        "def main(argv):\n"
        "    print('{\"fake_home_operation\":true}')\n"
        "    return 0 if argv == ['--live', '--json'] else 9\n"
    )

    staged_root = tmp_path / "kudu-temp/jobs/triggered/fixed/random"
    staged_root.mkdir(parents=True)
    staged_entrypoint = staged_root / "run.py"
    shutil.copy2(ENTRYPOINT, staged_entrypoint)
    unrelated_cwd = tmp_path / "unrelated-working-directory"
    unrelated_cwd.mkdir()
    environment = {
        "HOME": str(fake_home),
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": "",
    }

    completed = subprocess.run(
        [sys.executable, "-I", str(staged_entrypoint)],
        cwd=unrelated_cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.strip() == '{"fake_home_operation":true}'
    assert completed.stderr == ""


def test_historical_success_before_trigger_lower_bound_fails_closed() -> None:
    service = importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_execution"
    )

    category, observed, terminal, succeeded = service._correlated_status(
        json.dumps(
            [{"status": "Success", "start_time": "2020-01-01T00:00:00Z"}]
        ),
        service._parse_time("2026-07-19T10:00:00Z"),
    )

    assert category == "correlated_run_not_observed"
    assert (observed, terminal, succeeded) == (False, False, False)


def test_ordinary_web_app_cli_does_not_require_hosted_verifier_values() -> None:
    script = importlib.import_module("scripts.deploy_web_app_infra")

    args = script._parse_args(
        [
            "--check",
            "--resource-group",
            "fictional-rg",
            "--location",
            "centralus",
            "--environment-name",
            "demo",
            "--project-name",
            "nurse-intake",
            "--web-app-name",
            "fictional-web-app",
            "--json",
        ]
    )

    assert args.enable_hosted_foundry_verifier is False
    assert args.hosted_verifier_project_endpoint is None


def test_discovery_is_a_distinct_single_read_mode() -> None:
    service = importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_execution"
    )

    class Runner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]):
            self.calls.append(args)
            return service.CommandResult(
                0,
                '[{"name":"verify-hosted-foundry-agent"}]',
                "",
            )

    runner = Runner()
    request = service.HostedFoundryAgentWebJobExecutionRequest(
        mode="live-discover",
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        source_root=ROOT,
    )

    result = service.execute_hosted_foundry_agent_webjob(request, runner=runner)

    assert result.ok is True
    assert result.remote_webjob_discovered is True
    assert result.trigger_request_accepted is False
    assert runner.calls == [
        [
            "az",
            "webapp",
            "webjob",
            "triggered",
            "list",
            "--resource-group",
            "fictional-rg",
            "--name",
            "fictional-web-app",
            "--query",
            "[].{name:name}",
            "--only-show-errors",
            "--output",
            "json",
        ]
    ]
