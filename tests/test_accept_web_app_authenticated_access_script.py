import importlib
import json
from types import SimpleNamespace

import pytest


CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
PRIVATE_ORIGIN = "https://private-authenticated-host.example"


def _script():
    return importlib.import_module("scripts.accept_web_app_authenticated_access")


def _authentication_payload() -> str:
    return json.dumps(
        {
            "platformEnabled": True,
            "requireAuthentication": True,
            "unauthenticatedClientAction": "Return401",
            "excludedPaths": ["/health", "/version", "/demo/status"],
            "requireHttps": True,
            "entraEnabled": True,
            "clientId": CLIENT_ID,
            "openIdIssuer": (
                "https://login.microsoftonline.com/" f"{TENANT_ID}/v2.0"
            ),
        }
    )


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        resource_group="fictional-resource-group",
        web_app_name="fictional-web-app",
        hosted_origin=PRIVATE_ORIGIN,
        client_application_id=CLIENT_ID,
        tenant_id=TENANT_ID,
    )


def test_check_is_offline_and_creates_no_runner_transport_or_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("--check must not create an Azure runner"),
        raising=False,
    )
    monkeypatch.setattr(
        script,
        "_create_runtime_transport",
        lambda _origin: pytest.fail("--check must not create HTTP transport"),
        raising=False,
    )
    monkeypatch.setattr(
        script,
        "prompt_for_interactive_outcome",
        lambda _prompt: pytest.fail("--check must not prompt"),
        raising=False,
    )

    exit_code = script.main(["--check", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["category"] == "interactive_acceptance_contract_valid"
    assert payload["interactive_sign_in_attempts"] == 0
    assert payload["azure_commands"] == 0
    assert payload["network_request_count"] == 0


def test_live_revalidates_configuration_and_perimeter_before_one_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    commands: list[list[str]] = []
    checkpoints: list[object] = []

    class Runner:
        def run(self, args: list[str]):
            commands.append(args)
            return SimpleNamespace(
                return_code=0,
                stdout=_authentication_payload(),
                stderr="private stderr",
            )

    runtime_result = SimpleNamespace(
        ok=True,
        category="authentication_perimeter_verified",
        anonymous_gets_attempted=3,
        protected_gets_attempted=4,
    )
    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), _request()),
    )
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner())
    monkeypatch.setattr(
        script,
        "verify_web_app_authentication_runtime",
        lambda evidence, *, transport_factory: runtime_result,
    )
    monkeypatch.setattr(
        script,
        "prompt_for_interactive_outcome",
        lambda prompt: checkpoints.append(prompt) or "verified",
    )

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["category"] == "authenticated_application_access_verified"
    assert payload["authentication_reads"] == 1
    assert payload["runtime_perimeter_requests"] == 7
    assert payload["interactive_sign_in_attempts"] == 1
    assert payload["authenticated_protected_get_attempts"] == 1
    assert len(commands) == 1
    assert commands[0][:3] == ["az", "resource", "show"]
    assert commands[0][commands[0].index("--name") + 1] == "authsettingsV2"
    assert len(checkpoints) == 1
    assert checkpoints[0].route == "/demo"
    assert CLIENT_ID not in output
    assert TENANT_ID not in output
    assert PRIVATE_ORIGIN not in output


def test_runtime_perimeter_failure_blocks_interactive_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()

    class Runner:
        def run(self, _args: list[str]):
            return SimpleNamespace(
                return_code=0,
                stdout=_authentication_payload(),
                stderr="private stderr",
            )

    runtime_result = SimpleNamespace(
        ok=False,
        category="protected_route_acceptance_failed",
        anonymous_gets_attempted=3,
        protected_gets_attempted=1,
    )
    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), _request()),
    )
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner())
    monkeypatch.setattr(
        script,
        "verify_web_app_authentication_runtime",
        lambda evidence, *, transport_factory: runtime_result,
    )
    monkeypatch.setattr(
        script,
        "prompt_for_interactive_outcome",
        lambda _prompt: pytest.fail("invalid perimeter must stop before prompt"),
    )

    exit_code = script.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "authenticated_acceptance_blocked"
    assert payload["reason"] == "runtime_perimeter_evidence_invalid"
    assert payload["authentication_reads"] == 1
    assert payload["runtime_perimeter_requests"] == 4
    assert payload["interactive_sign_in_attempts"] == 0
