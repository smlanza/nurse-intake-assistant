import json
from io import StringIO
from types import SimpleNamespace

import pytest

from scripts import cleanup_daily_azure_environment as script
from src.app.services.daily_azure_environment_cleanup import CleanupResult


def test_cleanup_runner_preserves_subprocess_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimedOutRunner:
        def run(self, args):
            return SimpleNamespace(
                return_code=124,
                stdout="",
                stderr="",
                timed_out=True,
            )

    monkeypatch.setattr(script, "_SubprocessRunner", TimedOutRunner)

    outcome = script._CleanupSubprocessRunner().run(
        ["az", "group", "delete"]
    )

    assert outcome.return_code == 124
    assert outcome.timed_out is True


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["--check"],
        ["--inspect", "--config", ".env.daily-azure.local", "--json"],
        ["--cleanup", "--config", ".env.daily-azure.local", "--json"],
        [
            "--check",
            "--inspect",
            "--config",
            ".env.daily-azure.local",
            "--json",
        ],
        [
            "--cleanup",
            "--live",
            "--config",
            ".env.daily-azure.local",
        ],
    ],
)
def test_invalid_modes_fail_before_runner_construction(
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
) -> None:
    monkeypatch.setattr(
        script,
        "_create_live_runner",
        lambda: pytest.fail("invalid mode constructed runner"),
    )

    with pytest.raises(SystemExit) as error:
        script._parse_args(arguments)

    assert error.value.code == 2


def test_check_mode_creates_no_runner(monkeypatch, capsys) -> None:
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *a, **k: object())
    monkeypatch.setattr(
        script,
        "_create_live_runner",
        lambda: pytest.fail("check constructed live runner"),
    )

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def check(self):
            return CleanupResult.local_contract_valid()

    monkeypatch.setattr(script, "DailyAzureEnvironmentCleanup", Service)

    assert (
        script.main(
            ["--check", "--config", ".env.daily-azure.local", "--json"]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["category"] == "local_contract_valid"


def test_inspect_mode_never_receives_an_approver(monkeypatch, capsys) -> None:
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *a, **k: object())
    runner = object()
    monkeypatch.setattr(script, "_create_live_runner", lambda: runner)

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def inspect(self, purpose, *, runner):
            assert purpose.value == "end_of_day"
            assert runner is not None
            return CleanupResult.already_clean(purpose)

    monkeypatch.setattr(script, "DailyAzureEnvironmentCleanup", Service)

    assert (
        script.main(
            [
                "--inspect",
                "--live",
                "--config",
                ".env.daily-azure.local",
                "--json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["category"] == "already_clean"


@pytest.mark.parametrize("response", ("", "\n", "n\n", "maybe\n"))
def test_cleanup_prompt_defaults_to_no(
    response: str,
) -> None:
    output = StringIO()
    summary = script.CleanupApprovalSummary(
        purpose=script.CleanupPurpose.END_OF_DAY,
        owned_resource_group_present=True,
        resource_group_deletion_required=True,
        soft_deleted_foundry_account_count=1,
        foundry_purge_required=True,
        healthy_reusable_environment=False,
    )

    assert (
        script.prompt_for_cleanup_approval(
            summary,
            input_stream=StringIO(response),
            output_stream=output,
        )
        is False
    )
    rendered = output.getvalue()
    assert "DAILY DISPOSABLE AZURE CLEANUP" in rendered
    assert "Proceed? [y/N]" in rendered
    assert "subscription" not in rendered.casefold()


def test_cleanup_cli_uses_one_prompt_and_sanitized_json(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *a, **k: object())
    runner = object()
    monkeypatch.setattr(script, "_create_live_runner", lambda: runner)
    monkeypatch.setattr(script.sys, "stdin", StringIO("y\n"))

    class Service:
        def __init__(self, *args, **kwargs):
            pass

        def cleanup(self, purpose, *, runner, approver):
            summary = script.CleanupApprovalSummary(
                purpose=purpose,
                owned_resource_group_present=True,
                resource_group_deletion_required=True,
                soft_deleted_foundry_account_count=0,
                foundry_purge_required=True,
                healthy_reusable_environment=False,
            )
            assert approver(summary) is True
            return CleanupResult.cleanup_completed(purpose)

    monkeypatch.setattr(script, "DailyAzureEnvironmentCleanup", Service)

    assert (
        script.main(
            [
                "--cleanup",
                "--live",
                "--config",
                ".env.daily-azure.local",
                "--json",
            ]
        )
        == 0
    )
    output = capsys.readouterr()
    payload = json.loads(output.out)
    assert payload["category"] == "cleanup_completed"
    assert payload["resource_group_absent"] is True
    assert payload["foundry_tombstones_absent"] is True
    assert output.err.count("Proceed? [y/N]") == 1
    assert "fictional-daily-rg" not in output.out


def test_script_has_no_unattended_approval_or_shell_execution() -> None:
    source = open(script.__file__, encoding="utf-8").read()
    assert "--yes" not in source
    assert "--force" not in source
    assert "shell=True" not in source
    assert "os.system" not in source
