import importlib
import json

import pytest


RESOURCE_GROUP = "fictional-rg"
WEB_APP_NAME = "fictional-web-app"


def _script():
    return importlib.import_module("scripts.verify_web_app_configuration")


def test_check_mode_is_offline_and_does_not_construct_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_live_runner",
        lambda: pytest.fail("check mode must not construct an Azure CLI runner"),
    )

    exit_code = script.main(["--check"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "check"
    assert payload["azure_request_attempted"] is False
    assert payload["web_app_present"] is False


def test_live_mode_lazily_uses_injected_runner_and_prints_sanitized_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    service = importlib.import_module(
        "src.app.services.web_app_configuration_verification"
    )

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []
            self.results = [
                service.CommandResult(
                    0,
                    json.dumps(
                        {
                            "provisioningState": "Succeeded",
                            "kind": "app,linux",
                            "httpsOnly": True,
                            "identityType": "SystemAssigned",
                        }
                    ),
                    "",
                ),
                service.CommandResult(
                    0,
                    json.dumps(
                        {
                            "linuxFxVersion": "PYTHON|3.12",
                            "appCommandLine": "python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000",
                            "ftpsState": "Disabled",
                            "minTlsVersion": "1.2",
                            "scmMinTlsVersion": "1.2",
                            "healthCheckPath": "/health",
                        }
                    ),
                    "",
                ),
                service.CommandResult(
                    0,
                    json.dumps(
                        [
                            {"name": "APP_MODE", "value": "mock"},
                            {"name": "AI_PROVIDER", "value": "mock"},
                            {"name": "AGENT_PROVIDER", "value": "mock"},
                            {"name": "SPEECH_PROVIDER", "value": "mock"},
                            {"name": "EMAIL_PROVIDER", "value": "mock"},
                            {"name": "SMS_PROVIDER", "value": "mock"},
                            {"name": "DEMO_SUPPRESS_NOTIFICATIONS", "value": "true"},
                            {"name": "SCM_DO_BUILD_DURING_DEPLOYMENT", "value": "true"},
                        ]
                    ),
                    "",
                ),
            ]

        def run(self, args: list[str]):
            self.calls.append(args)
            return self.results.pop(0)

    runner = FakeRunner()
    monkeypatch.setattr(script, "_create_live_runner", lambda: runner)

    exit_code = script.main(
        [
            "--live",
            "--json",
            "--resource-group",
            RESOURCE_GROUP,
            "--web-app-name",
            WEB_APP_NAME,
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert len(runner.calls) == 3
    assert payload["ok"] is True
    assert payload["mode"] == "live"
    assert RESOURCE_GROUP not in output
    assert WEB_APP_NAME not in output


def test_cli_requires_explicit_exclusive_mode_and_live_arguments() -> None:
    script = _script()
    invalid_argv = (
        [],
        ["--check", "--live"],
        ["--live", "--resource-group", RESOURCE_GROUP, "--web-app-name", WEB_APP_NAME],
        ["--live", "--json", "--web-app-name", WEB_APP_NAME],
        ["--live", "--json", "--resource-group", RESOURCE_GROUP],
        ["--check", "--resource-group", RESOURCE_GROUP],
        ["--check", "--web-app-name", WEB_APP_NAME],
    )
    for argv in invalid_argv:
        with pytest.raises(SystemExit):
            script.main(argv)


def test_live_failure_is_nonzero_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    service = importlib.import_module(
        "src.app.services.web_app_configuration_verification"
    )

    class FailingRunner:
        def run(self, _args: list[str]):
            return service.CommandResult(
                1,
                "subscription-id raw stdout",
                "AuthorizationFailed secret-token",
            )

    monkeypatch.setattr(script, "_create_live_runner", FailingRunner)

    exit_code = script.main(
        [
            "--live",
            "--json",
            "--resource-group",
            RESOURCE_GROUP,
            "--web-app-name",
            WEB_APP_NAME,
        ]
    )

    output = capsys.readouterr().out
    assert exit_code != 0
    assert json.loads(output)["category"] == "authentication_or_authorization_failed"
    for forbidden in ("subscription-id", "raw stdout", "secret-token"):
        assert forbidden not in output


def test_subprocess_runner_uses_argument_list_and_safe_capture_options(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    captured: list[tuple[object, dict[str, object]]] = []

    class Completed:
        returncode = 0
        stdout = '{"safe":"value"}'
        stderr = "raw stderr"

    def fake_run(args: object, **kwargs: object) -> Completed:
        captured.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    command = ["az", "resource", "show"]

    result = script.SubprocessAzureCliRunner().run(command)

    assert isinstance(result, script.CommandResult)
    assert result.return_code == 0
    assert result.stdout == '{"safe":"value"}'
    assert result.stderr == "raw stderr"
    assert captured == [
        (
            command,
            {
                "shell": False,
                "capture_output": True,
                "text": True,
                "check": False,
            },
        )
    ]
    assert capsys.readouterr().out == ""


def test_missing_azure_cli_maps_to_sanitized_unavailable_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    service = importlib.import_module(
        "src.app.services.web_app_configuration_verification"
    )

    def missing_executable(*_args: object, **_kwargs: object):
        raise FileNotFoundError("secret executable path and token")

    monkeypatch.setattr(script.subprocess, "run", missing_executable)

    result = service.verify_web_app_configuration(
        RESOURCE_GROUP,
        WEB_APP_NAME,
        runner=script.SubprocessAzureCliRunner(),
    )

    rendered = json.dumps(result.to_json_dict())
    assert result.category == "azure_cli_unavailable"
    assert result.azure_request_attempted is True
    assert "secret executable" not in rendered
    assert "token" not in rendered
    assert capsys.readouterr().out == ""


def test_live_invalid_local_contract_does_not_construct_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    service = importlib.import_module(
        "src.app.services.web_app_configuration_verification"
    )
    created: list[bool] = []
    unsafe_settings = {**service.SAFE_APP_SETTINGS, "APP_MODE": "true"}
    monkeypatch.setattr(service, "SAFE_APP_SETTINGS", unsafe_settings)
    monkeypatch.setattr(
        script,
        "_create_live_runner",
        lambda: created.append(True),
    )

    exit_code = script.main(
        [
            "--live",
            "--json",
            "--resource-group",
            RESOURCE_GROUP,
            "--web-app-name",
            WEB_APP_NAME,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert payload["mode"] == "live"
    assert payload["category"] == "unexpected_error"
    assert payload["local_contract_validated"] is False
    assert payload["azure_request_attempted"] is False
    assert created == []
