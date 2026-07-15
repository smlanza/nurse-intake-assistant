import importlib
import json
import subprocess
import sys

import pytest


VALID_ARGUMENTS = [
    "--resource-group",
    "fictional-webapp-rg",
    "--location",
    "eastus2",
    "--environment-name",
    "demo",
    "--project-name",
    "nurse-intake",
    "--web-app-name",
    "fictional-nurse-intake-web-app",
]


def _script():
    return importlib.import_module("scripts.deploy_web_app_infra")


def test_importing_module_performs_no_azure_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sys.modules.pop("scripts.deploy_web_app_infra", None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("import must not execute Azure CLI"),
    )

    _script()


def test_modes_are_required_and_mutually_exclusive() -> None:
    script = _script()
    for argv in (
        VALID_ARGUMENTS,
        ["--check", "--what-if", *VALID_ARGUMENTS],
        ["--check", "--live", *VALID_ARGUMENTS],
        ["--what-if", "--live", *VALID_ARGUMENTS],
    ):
        with pytest.raises(SystemExit):
            script.main(argv)


def test_required_operator_arguments_are_enforced() -> None:
    script = _script()
    for flag in (
        "--resource-group",
        "--location",
        "--environment-name",
        "--project-name",
        "--web-app-name",
    ):
        index = VALID_ARGUMENTS.index(flag)
        argv = ["--check", *VALID_ARGUMENTS[:index], *VALID_ARGUMENTS[index + 2 :]]
        with pytest.raises(SystemExit):
            script.main(argv)


def test_check_prints_sanitized_json_without_constructing_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("check mode must not construct a runner"),
    )

    exit_code = script.main(["--check", "--json", *VALID_ARGUMENTS])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["category"] == "success"
    assert payload["azure_operation_attempted"] is False
    assert payload["deploy_app"] is True
    assert payload["deploy_foundry"] is False


def test_unsafe_argument_fails_before_runner_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    created: list[bool] = []
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: created.append(True),
    )
    argv = [
        value if value != "fictional-webapp-rg" else "unsafe\nresource-group"
        for value in VALID_ARGUMENTS
    ]

    exit_code = script.main(["--live", "--json", *argv])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert payload["category"] == "invalid_arguments"
    assert payload["azure_operation_attempted"] is False
    assert created == []


def test_invalid_local_contract_fails_before_runner_construction(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path,
) -> None:
    script = _script()
    created: list[bool] = []
    invalid_template = tmp_path / "main.bicep"
    invalid_template.write_text("param deployApp bool = false\n")
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: created.append(True),
    )

    exit_code = script.main(
        [
            "--what-if",
            "--json",
            *VALID_ARGUMENTS,
            "--template-file",
            str(invalid_template),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert payload["category"] == "local_contract_invalid"
    assert payload["azure_operation_attempted"] is False
    assert created == []


@pytest.mark.parametrize("mode", ["--what-if", "--live"])
def test_azure_modes_lazily_use_one_injected_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    script = _script()

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]):
            self.calls.append(args)
            return script.CommandResult(
                0,
                '{"changes":[],"secret":"sensitive Azure output"}',
                "",
            )

    runner = FakeRunner()
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: runner)

    exit_code = script.main([mode, "--json", *VALID_ARGUMENTS])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert len(runner.calls) == 1
    assert "sensitive Azure output" not in output


def test_non_json_what_if_prints_only_sanitized_summary(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    class FakeRunner:
        def run(self, _args: list[str]):
            return script.CommandResult(
                0,
                json.dumps(
                    {
                        "changes": [
                            {
                                "changeType": "Create",
                                "resourceId": "/subscriptions/raw-id/resourceGroups/raw-rg",
                            },
                            {"changeType": "Modify"},
                            {"changeType": "Modify"},
                            {"changeType": "Delete"},
                            {"changeType": "NoChange"},
                        ]
                    }
                ),
                "raw stderr",
            )

    monkeypatch.setattr(script, "_create_azure_cli_runner", FakeRunner)

    exit_code = script.main(["--what-if", *VALID_ARGUMENTS])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "preview" in output.lower()
    assert "creates: 1" in output.lower()
    assert "modifies: 2" in output.lower()
    assert "deletes: 1" in output.lower()
    assert "unchanged: 1" in output.lower()
    assert "review" in output.lower()
    assert "raw-id" not in output
    assert "raw-rg" not in output
    assert "raw stderr" not in output


def test_json_what_if_prints_exactly_one_sanitized_object(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    class FakeRunner:
        def run(self, _args: list[str]):
            return script.CommandResult(
                0,
                '{"changes":[{"changeType":"Create","resourceId":"raw-id"}]}',
                "raw stderr",
            )

    monkeypatch.setattr(script, "_create_azure_cli_runner", FakeRunner)

    exit_code = script.main(["--what-if", "--json", *VALID_ARGUMENTS])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert len(output.splitlines()) == 1
    payload = json.loads(output)
    assert payload["create_count"] == 1
    assert payload["what_if_summary_available"] is True
    assert "raw-id" not in output
    assert "raw stderr" not in output


def test_subprocess_runner_uses_argument_list_shell_false_and_captured_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    captured: list[tuple[object, dict[str, object]]] = []

    class Completed:
        returncode = 0
        stdout = "raw stdout"
        stderr = "raw stderr"

    def fake_run(args: object, **kwargs: object) -> Completed:
        captured.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    args = ["az", "deployment", "group", "what-if"]

    result = script.SubprocessAzureCliRunner().run(args)

    assert result == script.CommandResult(0, "raw stdout", "raw stderr")
    assert captured == [
        (
            args,
            {
                "shell": False,
                "capture_output": True,
                "text": True,
                "check": False,
            },
        )
    ]
    assert capsys.readouterr().out == ""


def test_subprocess_runner_handles_missing_azure_cli_without_printing(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("secret executable path")
        ),
    )

    result = script.SubprocessAzureCliRunner().run(["az", "version"])

    assert result == script.CommandResult(127, "", "")
    assert capsys.readouterr().out == ""
