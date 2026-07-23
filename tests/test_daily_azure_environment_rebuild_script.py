import json
from io import StringIO
from pathlib import Path

import pytest

from scripts import rebuild_daily_azure_environment as script
from src.app.services.daily_azure_environment_rebuild import (
    DailyAzureEnvironmentRebuildResult,
)


def test_daily_azure_environment_rebuild_cli_boundary_exists() -> None:
    assert callable(script.main)


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--check"],
        ["--live", "--config", ".env.daily-azure.local"],
        [
            "--check",
            "--live",
            "--config",
            ".env.daily-azure.local",
            "--json",
        ],
    ],
)
def test_cli_rejects_missing_or_incompatible_modes(arguments: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        script._parse_args(arguments)
    assert error.value.code == 2


def test_check_mode_does_not_construct_live_runner(monkeypatch, capsys) -> None:
    class Config:
        discover_hosted_foundry_webjob = True

    monkeypatch.setattr(script, "load_daily_azure_config", lambda *a, **k: Config())
    monkeypatch.setattr(
        script,
        "_create_live_runner",
        lambda _config: pytest.fail("offline check constructed a live runner"),
    )

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def check(self):
            return DailyAzureEnvironmentRebuildResult(
                ok=True,
                category="success",
                mode="check",
                local_orchestration_ready=True,
            )

    monkeypatch.setattr(script, "DailyAzureEnvironmentRebuild", Service)

    assert script.main(["--check", "--config", ".env.daily-azure.local", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["local_orchestration_ready"] is True
    assert payload["azure_mutation_made"] is False
    assert payload["agent_invoked"] is False


def test_live_json_output_is_sanitized_and_exit_code_is_deterministic(
    monkeypatch, capsys
) -> None:
    class Config:
        discover_hosted_foundry_webjob = True

    monkeypatch.setattr(script, "load_daily_azure_config", lambda *a, **k: Config())
    sentinel_runner = object()
    monkeypatch.setattr(script, "_create_live_runner", lambda _config: sentinel_runner)

    class Service:
        def __init__(self, *args, **kwargs):
            self.runner_factory = kwargs["runner_factory"]

        def live(self, *, approver):
            assert self.runner_factory() is sentinel_runner
            assert callable(approver)
            return DailyAzureEnvironmentRebuildResult._verified_ready(
                {
                    "local_orchestration_ready": True,
                    "account_verified": True,
                    "resource_group_ready": True,
                    "foundry_infrastructure_verified": True,
                    "prompt_agent_verified": True,
                    "immutable_routing_verified": True,
                    "web_app_configuration_verified": True,
                    "application_package_created": True,
                    "application_artifact_current": True,
                    "application_deployment_attempted": True,
                    "application_deployment_accepted": True,
                    "hosted_readiness_verified": True,
                },
                azure_mutation_made=False,
            )

    monkeypatch.setattr(script, "DailyAzureEnvironmentRebuild", Service)
    assert script.main(["--live", "--config", ".env.daily-azure.local", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["daily_environment_ready"] is True
    assert payload["consumer_rbac_verified"] is False
    assert payload["agent_invoked"] is False
    assert payload["webjob_discovered"] is False
    assert payload["webjob_triggered"] is False
    assert payload["webjob_status_read"] is False
    assert payload["managed_identity_verification_performed"] is False
    assert not any(
        key in payload
        for key in (
            "resource_group",
            "endpoint",
            "hostname",
            "agent_version",
            "principal_id",
            "command",
        )
    )


def test_cli_sanitizes_unexpected_errors_without_traceback(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret traceback")),
    )
    assert script.main(["--check", "--config", ".env.daily-azure.local", "--json"]) == 2
    output = capsys.readouterr()
    assert json.loads(output.out)["category"] == "unexpected_error"
    assert "secret traceback" not in output.out
    assert "Traceback" not in output.err


def test_live_rbac_approval_prompt_stays_on_stderr_and_stdout_is_valid_json(
    monkeypatch, capsys
) -> None:
    class Config:
        discover_hosted_foundry_webjob = True

    monkeypatch.setattr(script, "load_daily_azure_config", lambda *a, **k: Config())
    monkeypatch.setattr(script, "_create_live_runner", lambda _config: object())
    monkeypatch.setattr(script.sys, "stdin", StringIO("n\n"))

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def live(self, *, approver):
            approved = approver(
                script.ApprovalSummary(
                    stage="consumer_rbac_deployment",
                    heading="FOUNDRY AGENT CONSUMER RBAC",
                    facts=(
                        (
                            "Preview classification",
                            "Unsupported role-assignment preview",
                        ),
                        ("Azure assignment contents proved", "no"),
                        ("Manual review required", "yes"),
                    ),
                    evidence_binding="current-rbac-plan",
                )
            )
            assert approved is False
            return DailyAzureEnvironmentRebuildResult(
                ok=False,
                category="consumer_rbac_operator_declined",
                mode="live",
                consumer_rbac_assignment_required=True,
            )

    monkeypatch.setattr(script, "DailyAzureEnvironmentRebuild", Service)

    assert script.main(["--live", "--config", ".env.daily-azure.local", "--json"]) == 1
    output = capsys.readouterr()
    assert json.loads(output.out)["category"] == "consumer_rbac_operator_declined"
    assert "FOUNDRY AGENT CONSUMER RBAC" in output.err
    assert "Preview classification: Unsupported role-assignment preview" in output.err
    assert "Azure assignment contents proved: no" in output.err
    assert "Manual review required: yes" in output.err
    assert "Proceed? [y/N]" in output.err
    assert "assignment creation" not in output.err.casefold()
    assert "FOUNDRY AGENT CONSUMER RBAC" not in output.out


def test_exact_create_rbac_prompt_is_truthful_and_defaults_to_no() -> None:
    destination = StringIO()
    approved = script.prompt_for_stage_approval(
        script.ApprovalSummary(
            stage="consumer_rbac_deployment",
            heading="FOUNDRY AGENT CONSUMER RBAC",
            facts=(
                ("Preview classification", "Exact Create"),
                ("Azure assignment contents proved", "yes"),
                ("Manual review required", "no"),
            ),
            evidence_binding="sanitized-binding",
        ),
        input_stream=StringIO("\n"),
        output_stream=destination,
    )

    output = destination.getvalue()
    assert approved is False
    assert "Preview classification: Exact Create" in output
    assert "Azure assignment contents proved: yes" in output
    assert "Manual review required: no" in output
    assert "Proceed? [y/N]" in output


def test_cli_has_no_hosted_proof_skip_flag() -> None:
    with pytest.raises(SystemExit):
        script._parse_args(
            [
                "--live",
                "--json",
                "--config",
                ".env.daily-azure.local",
                "--skip-webjob-discovery",
            ]
        )


def test_script_contains_no_shell_command_construction() -> None:
    source = Path(script.__file__).read_text()
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "live-trigger" not in source
    assert "live-status" not in source
