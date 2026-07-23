import importlib
import json

import pytest


RESOURCE_GROUP = "fictional-resource-group"
WEB_APP_NAME = "fictional-nurse-intake-web-app"
FOUNDRY_ACCOUNT_NAME = "fictional-foundry-account"
FOUNDRY_PROJECT_NAME = "fictional-foundry-project"
NAMES = [
    "--resource-group", RESOURCE_GROUP,
    "--web-app-name", WEB_APP_NAME,
    "--foundry-account-name", FOUNDRY_ACCOUNT_NAME,
    "--foundry-project-name", FOUNDRY_PROJECT_NAME,
]


def _script():
    return importlib.import_module("scripts.verify_foundry_agent_consumer_rbac")


def test_import_and_help_have_no_azure_side_effect(monkeypatch, capsys) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("import/help must not create a runner"),
    )

    with pytest.raises(SystemExit) as help_exit:
        script.main(["--help"])

    assert help_exit.value.code == 0
    assert "read-only" in capsys.readouterr().out.lower()


def test_check_is_json_offline_and_does_not_construct_runner(monkeypatch, capsys) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("check must not construct a runner"),
    )

    exit_code = script.main(["--check", *NAMES, "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "check"
    assert payload["azure_request_attempted"] is False


def test_invalid_live_name_fails_before_runner_creation(monkeypatch, capsys) -> None:
    script = _script()
    created: list[bool] = []
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: created.append(True),
    )

    exit_code = script.main(
        [
            "--live", "--json",
            "--resource-group", "unsafe/resource-group",
            "--web-app-name", WEB_APP_NAME,
            "--foundry-account-name", FOUNDRY_ACCOUNT_NAME,
            "--foundry-project-name", FOUNDRY_PROJECT_NAME,
        ]
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["category"] == "invalid_configuration"
    assert created == []


def test_cli_requires_exclusive_mode_all_names_and_json() -> None:
    script = _script()
    invalid = (
        [],
        ["--check", "--live", *NAMES, "--json"],
        ["--check", *NAMES],
        ["--live", *NAMES],
        ["--live", "--json", *NAMES[:-2]],
    )
    for argv in invalid:
        with pytest.raises(SystemExit):
            script.main(argv)


def test_live_success_and_failure_have_distinct_sanitized_exit_codes(
    monkeypatch, capsys
) -> None:
    script = _script()
    service = importlib.import_module(
        "src.app.services.foundry_agent_consumer_rbac_verification"
    )
    principal = "00000000-0000-0000-0000-000000000001"
    subscription = "00000000-0000-0000-0000-000000000002"
    scope = (
        f"/subscriptions/{subscription}/resourceGroups/{RESOURCE_GROUP}"
        f"/providers/Microsoft.CognitiveServices/accounts/{FOUNDRY_ACCOUNT_NAME}"
        f"/projects/{FOUNDRY_PROJECT_NAME}"
    )
    role = (
        f"/subscriptions/{subscription}/providers/Microsoft.Authorization/roleDefinitions/"
        "eed3b665-ab3a-47b6-8f48-c9382fb1dad6"
    )
    web_app_resource_id = (
        f"/subscriptions/{subscription}/resourceGroups/{RESOURCE_GROUP}/providers/"
        f"Microsoft.Web/sites/{WEB_APP_NAME}"
    )

    class Runner:
        def __init__(self, success: bool) -> None:
            self.results = (
                [
                    service.CommandResult(
                        0,
                        json.dumps(
                            {
                                "principalId": principal,
                                "type": "SystemAssigned",
                                "webAppId": web_app_resource_id,
                            }
                        ),
                        "",
                    ),
                    service.CommandResult(
                        0,
                        json.dumps({"name": FOUNDRY_PROJECT_NAME, "id": scope}),
                        "",
                    ),
                    service.CommandResult(0, json.dumps([{"principalId": principal, "roleDefinitionId": role, "scope": scope}]), ""),
                ]
                if success
                else [service.CommandResult(1, "raw subscription-secret", "AuthorizationFailed token-secret")]
            )

        def run(self, _args):
            return self.results.pop(0)

    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner(True))
    assert script.main(["--live", *NAMES, "--json"]) == 0
    success_output = capsys.readouterr().out
    assert json.loads(success_output)["ok"] is True
    assert principal not in success_output
    assert subscription not in success_output

    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner(False))
    assert script.main(["--live", *NAMES, "--json"]) == 2
    failure_output = capsys.readouterr().out
    assert json.loads(failure_output)["category"] == "authentication_or_authorization_failed"
    assert "subscription-secret" not in failure_output
    assert "token-secret" not in failure_output


def test_subprocess_runner_uses_argument_list_and_safe_capture(monkeypatch, capsys) -> None:
    script = _script()
    captured = []

    class Completed:
        returncode = 0
        stdout = '{"safe":true}'
        stderr = "raw stderr"

    def fake_run(args, **kwargs):
        captured.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    command = ["az", "resource", "show"]

    result = script.SubprocessAzureCliRunner().run(command)

    assert result == script.CommandResult(0, '{"safe":true}', "raw stderr")
    assert captured == [
        (
            command,
            {"shell": False, "capture_output": True, "text": True, "check": False},
        )
    ]
    assert capsys.readouterr().out == ""


def test_missing_azure_cli_is_sanitized(monkeypatch, capsys) -> None:
    script = _script()

    def missing(*_args, **_kwargs):
        raise FileNotFoundError("secret executable path")

    monkeypatch.setattr(script.subprocess, "run", missing)
    exit_code = script.main(["--live", *NAMES, "--json"])

    output = capsys.readouterr().out
    assert exit_code == 2
    assert json.loads(output)["category"] == "azure_cli_unavailable"
    assert "secret executable" not in output
