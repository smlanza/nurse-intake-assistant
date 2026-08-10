import importlib
import json

import pytest


CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def _script():
    return importlib.import_module("scripts.verify_web_app_authentication")


def test_check_defaults_to_disabled_and_is_sanitized(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = _script().main(["--check"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["authentication_state_verified"] is True
    assert payload["authentication_v2_enabled"] is False
    assert payload["azure_request_attempted"] is False


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
