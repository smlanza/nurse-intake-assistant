import json

import pytest


BASE_URL = "https://secret-host.example"


class FakeTransport:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def get(self, path: str, _timeout_seconds: float):
        from src.app.services.web_app_readiness_verification import HttpResponse

        self.paths.append(path)
        payloads = {
            "/health": {"status": "ok", "service": "nurse-intake-assistant"},
            "/version": {
                "service": "nurse-intake-assistant",
                "version": "0.1.0",
                "environment": "local",
                "artifactDigest": "unpackaged",
            },
            "/demo/status": {
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
                "safetyBoundary": "Human nurse review is required.",
                "warnings": [],
            },
        }
        return HttpResponse(200, json.dumps(payloads[path]).encode())


def test_check_is_offline_sanitized_and_does_not_claim_hosted_readiness(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_web_app_readiness as script

    monkeypatch.setattr(
        script,
        "_create_live_transport",
        lambda _base_url: pytest.fail("check mode must not construct HTTP transport"),
    )

    exit_code = script.main(
        ["--base-url", f" {BASE_URL}/ ", "--check", "--json"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["mode"] == "check"
    assert payload["category"] == "success"
    assert payload["base_url_valid"] is True
    assert payload["hosted_request_attempted"] is False
    assert payload["health_verified"] is False
    assert payload["version_verified"] is False
    assert payload["demo_status_verified"] is False
    assert payload["safe_hosted_posture_verified"] is False
    assert "secret-host" not in output


def test_live_lazily_creates_transport_and_returns_sanitized_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_web_app_readiness as script

    transport = FakeTransport()
    created_for: list[str] = []

    def create_transport(base_url: str) -> FakeTransport:
        created_for.append(base_url)
        return transport

    monkeypatch.setattr(script, "_create_live_transport", create_transport)

    exit_code = script.main(
        ["--base-url", f"{BASE_URL}/", "--live", "--json"]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert created_for == [BASE_URL]
    assert transport.paths == ["/health", "/version", "/demo/status"]
    assert payload["ok"] is True
    assert payload["safe_hosted_posture_verified"] is True
    assert "secret-host" not in output
    assert "https://" not in output


def test_live_failure_is_nonzero_and_does_not_expose_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.verify_web_app_readiness as script

    class FailingTransport:
        def get(self, _path: str, _timeout_seconds: float):
            from src.app.services.web_app_readiness_verification import (
                HttpRequestError,
            )

            raise HttpRequestError(
                "https://secret-host.example Bearer secret-token patient@example.com"
            )

    monkeypatch.setattr(
        script,
        "_create_live_transport",
        lambda _base_url: FailingTransport(),
    )

    exit_code = script.main(["--base-url", BASE_URL, "--live", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code != 0
    assert payload["category"] == "http_request_failed"
    for unsafe in ("secret-host", "Bearer", "secret-token", "patient@example.com"):
        assert unsafe not in output


def test_cli_requires_explicit_exclusive_mode_and_live_json() -> None:
    import scripts.verify_web_app_readiness as script

    with pytest.raises(SystemExit):
        script.main(["--base-url", BASE_URL])
    with pytest.raises(SystemExit):
        script.main(["--base-url", BASE_URL, "--check", "--live", "--json"])
    with pytest.raises(SystemExit):
        script.main(["--base-url", BASE_URL, "--live"])
