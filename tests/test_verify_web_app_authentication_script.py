import importlib
import json
from types import SimpleNamespace

import pytest


CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _script():
    return importlib.import_module("scripts.verify_web_app_authentication")


def test_check_defaults_to_disabled_and_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("--check must remain offline"),
        raising=False,
    )

    exit_code = script.main(["--check"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["authentication_state_verified"] is True
    assert payload["authentication_v2_enabled"] is False
    assert payload["azure_request_attempted"] is False


def test_live_reads_exact_authsettings_v2_once_and_verifies_semantics(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    commands: list[list[str]] = []
    request = SimpleNamespace(
        resource_group="fictional-resource-group",
        web_app_name="fictional-web-app",
        client_application_id=CLIENT_ID,
        tenant_id=TENANT_ID,
    )

    class RecordingRunner:
        def run(self, args: list[str]):
            commands.append(args)
            return SimpleNamespace(
                return_code=0,
                stdout=json.dumps(
                    {
                        "platformEnabled": True,
                        "requireAuthentication": True,
                        "unauthenticatedClientAction": "Return401",
                        "excludedPaths": ["/health", "/version", "/demo/status"],
                        "requireHttps": True,
                        "entraEnabled": True,
                        "clientId": CLIENT_ID,
                        "openIdIssuer": (
                            "https://login.microsoftonline.com/"
                            f"{TENANT_ID}/v2.0"
                        ),
                    }
                ),
                stderr="private stderr",
            )

    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), request),
        raising=False,
    )
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: RecordingRunner(),
        raising=False,
    )

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["category"] == "authentication_configuration_verified"
    assert payload["authentication_reads"] == 1
    assert len(commands) == 1
    assert commands[0][:3] == ["az", "resource", "show"]
    assert commands[0][commands[0].index("--name") + 1] == "authsettingsV2"
    assert not any(
        part in {"deployment", "what-if", "create", "update"}
        for part in commands[0]
    )
    assert CLIENT_ID not in output
    assert TENANT_ID not in output


def test_live_missing_operator_identifiers_stops_before_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.delenv("OPERATOR_ENTRA_APPLICATION_ID", raising=False)
    monkeypatch.delenv("OPERATOR_ENTRA_TENANT_ID", raising=False)
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("invalid identifiers must stop before runner construction"),
        raising=False,
    )

    exit_code = script.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "operator_identifiers_unavailable"
    assert payload["azure_request_attempted"] is False
    assert payload["authentication_reads"] == 0


def test_enabled_check_requires_exactly_one_pair_and_never_serializes_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _script().main(
        [
            "--check",
            "--expect-enabled",
            "--client-application-id",
            CLIENT_ID,
            "--tenant-id",
            TENANT_ID,
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["authentication_v2_enabled"] is True
    assert payload["anonymous_exclusions_verified"] is True
    assert CLIENT_ID not in output
    assert TENANT_ID not in output


@pytest.mark.parametrize(
    "argv",
    (
        [],
        ["--check", "--client-application-id", CLIENT_ID],
        ["--check", "--tenant-id", TENANT_ID],
        ["--check", "--expect-enabled", "--client-application-id", CLIENT_ID],
        ["--check", "--expect-enabled", "--tenant-id", TENANT_ID],
        [
            "--check",
            "--expect-enabled",
            "--client-application-id",
            CLIENT_ID,
            "--client-application-id",
            CLIENT_ID,
            "--tenant-id",
            TENANT_ID,
        ],
    ),
)
def test_cli_rejects_missing_conflicting_or_duplicate_configuration(
    argv: list[str],
) -> None:
    with pytest.raises(SystemExit):
        _script().main(argv)
