import importlib
import json
import subprocess
import sys

import pytest


VALID_ARGUMENTS = [
    "--resource-group",
    "fictional-resource-group",
    "--web-app-name",
    "fictional-nurse-intake-web-app",
    "--foundry-account-name",
    "fictional-foundry-account",
    "--foundry-project-name",
    "fictional-foundry-project",
]


def _script():
    return importlib.import_module("scripts.deploy_foundry_agent_consumer_rbac")


def test_import_performs_no_azure_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules.pop("scripts.deploy_foundry_agent_consumer_rbac", None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("import must not run Azure CLI"),
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


@pytest.mark.parametrize(
    "flag",
    [
        "--resource-group",
        "--web-app-name",
        "--foundry-account-name",
        "--foundry-project-name",
    ],
)
def test_required_names_are_enforced(flag: str) -> None:
    script = _script()
    index = VALID_ARGUMENTS.index(flag)
    argv = ["--check", *VALID_ARGUMENTS[:index], *VALID_ARGUMENTS[index + 2 :]]

    with pytest.raises(SystemExit):
        script.main(argv)


def test_role_definition_override_is_not_a_cli_option() -> None:
    script = _script()

    with pytest.raises(SystemExit):
        script.main(
            [
                "--check",
                *VALID_ARGUMENTS,
                "--role-definition-id",
                "owner-role-id",
            ]
        )


def test_check_is_offline_and_prints_sanitized_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("check must not construct a runner"),
    )

    exit_code = script.main(["--check", "--json", *VALID_ARGUMENTS])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["category"] == "success"
    assert payload["template_valid"] is True
    assert payload["azure_operation_attempted"] is False
    assert payload["deployment_request_accepted"] is False


def test_unsafe_input_fails_before_runner_construction(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()
    constructed: list[bool] = []
    monkeypatch.setattr(
        script, "_create_azure_cli_runner", lambda: constructed.append(True)
    )
    argv = [
        value if value != "fictional-resource-group" else "unsafe\nresource-group"
        for value in VALID_ARGUMENTS
    ]

    exit_code = script.main(["--live", "--json", *argv])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "invalid_request"
    assert payload["azure_operation_attempted"] is False
    assert constructed == []


@pytest.mark.parametrize("mode", ["--what-if", "--live"])
def test_azure_modes_lazily_use_exactly_one_injected_runner(
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
                '{"changes":[],"principalId":"raw-principal"}',
                "raw stderr",
            )

    runner = FakeRunner()
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: runner)

    exit_code = script.main([mode, "--json", *VALID_ARGUMENTS])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert len(runner.calls) == 1
    assert "raw-principal" not in output
    assert "raw stderr" not in output


def test_non_json_what_if_prints_all_sanitized_counts_and_manual_review_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = _script()

    class FakeRunner:
        def run(self, _args: list[str]):
            return script.CommandResult(
                0,
                json.dumps(
                    {
                        "changes": [
                            {"changeType": "Create", "resourceId": "/raw/id"},
                            {"changeType": "Modify"},
                            {"changeType": "Delete"},
                            {"changeType": "NoChange"},
                            {"changeType": "Ignore"},
                            {"changeType": "Deploy"},
                            {"changeType": "Unsupported"},
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
    assert "modifies: 1" in output.lower()
    assert "deletes: 1" in output.lower()
    assert "unchanged: 1" in output.lower()
    assert "ignored: 1" in output.lower()
    assert "deploy-uncertain: 1" in output.lower()
    assert "unsupported: 1" in output.lower()
    assert "manual review" in output.lower()
    assert "/raw/id" not in output
    assert "raw stderr" not in output


def test_subprocess_runner_uses_argument_list_without_shell(
    monkeypatch: pytest.MonkeyPatch,
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


def test_subprocess_runner_maps_missing_azure_cli_to_sanitized_result(
    monkeypatch: pytest.MonkeyPatch,
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
