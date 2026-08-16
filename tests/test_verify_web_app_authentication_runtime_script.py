import importlib
import json
from types import SimpleNamespace

import pytest


CLIENT_ID = "11111111-2222-4333-8444-555555555555"
TENANT_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
BASE_URL = "https://private-runtime-host.example"


def _script():
    return importlib.import_module(
        "scripts.verify_web_app_authentication_runtime"
    )


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


def test_check_is_offline_and_constructs_no_transport(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("--check must not construct an Azure runner"),
        raising=False,
    )
    monkeypatch.setattr(
        script,
        "_create_runtime_transport",
        lambda _origin: pytest.fail("--check must not construct HTTP transport"),
        raising=False,
    )

    exit_code = script.main(["--check", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["category"] == "runtime_contract_valid"
    assert payload["runtime_verification_attempted"] is False
    assert payload["authentication_reads"] == 0


def test_live_gates_on_exact_authentication_read_then_runs_seven_gets(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    commands: list[list[str]] = []
    transport_calls: list[str] = []
    request = SimpleNamespace(
        resource_group="fictional-resource-group",
        web_app_name="fictional-web-app",
        hosted_origin=BASE_URL,
        client_application_id=CLIENT_ID,
        tenant_id=TENANT_ID,
    )

    class Runner:
        def run(self, args: list[str]):
            commands.append(args)
            return SimpleNamespace(
                return_code=0,
                stdout=_authentication_payload(),
                stderr="private stderr",
            )

    class Transport:
        def get(self, path: str, _timeout: float):
            from src.app.services.web_app_readiness_verification import HttpResponse

            transport_calls.append(path)
            if path == "/health":
                body = {"status": "ok", "service": "nurse-intake-assistant"}
            elif path == "/version":
                body = {
                    "service": "nurse-intake-assistant",
                    "version": "0.1.0",
                    "environment": "hosted",
                    "artifactDigest": "a" * 64,
                }
            elif path == "/demo/status":
                body = {
                    "demoModeReady": True,
                    "appMode": "mock",
                    "aiProvider": "mock",
                    "speechProvider": "mock",
                    "emailProvider": "mock",
                    "smsProvider": "mock",
                    "agentProvider": "mock",
                    "agentStatus": {
                        "provider": "mock",
                        "ready": True,
                        "mode": "mock",
                        "missingSettings": [],
                    },
                    "agentProviderStatus": {
                        "provider": "mock",
                        "configured": True,
                        "liveValidation": "not_attempted",
                        "manualValidationAvailable": False,
                        "manualValidationCommand": None,
                        "missingSettings": [],
                        "warnings": [],
                    },
                    "notificationsSuppressed": True,
                    "safeForLocalDemo": True,
                    "safetyBoundary": "Human review required.",
                    "warnings": [],
                }
            else:
                return HttpResponse(401, b"private body")
            return HttpResponse(200, json.dumps(body).encode())

    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), request),
        raising=False,
    )
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner())
    monkeypatch.setattr(script, "_create_runtime_transport", lambda _origin: Transport())

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["category"] == "authentication_perimeter_verified"
    assert payload["authentication_reads"] == 1
    assert payload["anonymous_gets_attempted"] == 3
    assert payload["protected_gets_attempted"] == 4
    assert len(commands) == 1
    assert commands[0][:3] == ["az", "resource", "show"]
    assert commands[0][commands[0].index("--name") + 1] == "authsettingsV2"
    assert transport_calls == [
        "/health",
        "/version",
        "/demo/status",
        "/demo",
        "/cases",
        "/docs",
        "/openapi.json",
    ]
    assert CLIENT_ID not in output
    assert TENANT_ID not in output
    assert BASE_URL not in output


def test_missing_current_ready_evidence_stops_before_runner_and_transport(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(script, "_load_private_request", lambda _args: None)
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("invalid READY must stop before Azure runner"),
    )
    monkeypatch.setattr(
        script,
        "_create_runtime_transport",
        lambda _origin: pytest.fail("invalid READY must stop before transport"),
    )

    exit_code = script.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "safe_runtime_verification_blocked"
    assert payload["reason"] == "readiness_evidence_invalid"
    assert payload["authentication_reads"] == 0
    assert payload["network_request_count"] == 0


def test_authentication_mismatch_stops_before_http_transport_and_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    request = SimpleNamespace(
        resource_group="fictional-resource-group",
        web_app_name="fictional-web-app",
        hosted_origin=BASE_URL,
        client_application_id=CLIENT_ID,
        tenant_id=TENANT_ID,
    )

    class Runner:
        def run(self, _args: list[str]):
            payload = json.loads(_authentication_payload())
            payload["requireAuthentication"] = False
            return SimpleNamespace(
                return_code=0,
                stdout=json.dumps(payload),
                stderr="private stderr",
            )

    monkeypatch.setenv("OPERATOR_ENTRA_APPLICATION_ID", CLIENT_ID)
    monkeypatch.setenv("OPERATOR_ENTRA_TENANT_ID", TENANT_ID)
    monkeypatch.setattr(
        script,
        "_load_private_request",
        lambda _args: (SimpleNamespace(), request),
    )
    monkeypatch.setattr(script, "_create_azure_cli_runner", lambda: Runner())
    monkeypatch.setattr(
        script,
        "_create_runtime_transport",
        lambda _origin: pytest.fail("invalid Authentication must stop HTTP"),
    )

    exit_code = script.main(["--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 2
    assert payload["category"] == "safe_runtime_verification_blocked"
    assert payload["reason"] == "authentication_configuration_invalid"
    assert payload["authentication_reads"] == 1
    assert payload["network_request_count"] == 1
    assert CLIENT_ID not in output
    assert TENANT_ID not in output
    assert BASE_URL not in output
