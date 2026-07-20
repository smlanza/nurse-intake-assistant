import json
from urllib.error import HTTPError

import pytest


BASE_URL = "https://secret-host.example"
ARTIFACT_DIGEST = "a" * 64


def _health() -> dict[str, object]:
    return {"status": "ok", "service": "nurse-intake-assistant"}


def _version() -> dict[str, object]:
    return {
        "service": "nurse-intake-assistant",
        "version": "0.1.0",
        "environment": "local",
        "artifactDigest": ARTIFACT_DIGEST,
    }


def _demo_status(**overrides: object) -> dict[str, object]:
    status: dict[str, object] = {
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
        "safetyBoundary": (
            "Local mock/demo only. Not for production clinical use. "
            "AI output requires human nurse review."
        ),
        "warnings": [],
    }
    status.update(overrides)
    return status


class FakeTransport:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def get(self, path: str, timeout_seconds: float):
        from src.app.services.web_app_readiness_verification import HttpResponse

        self.calls.append((path, timeout_seconds))
        response = self.responses[path]
        if isinstance(response, BaseException):
            raise response
        status_code, payload = response
        body = payload if isinstance(payload, str) else json.dumps(payload)
        return HttpResponse(status_code=status_code, body=body.encode())


def _success_transport() -> FakeTransport:
    return FakeTransport(
        {
            "/health": (200, _health()),
            "/version": (200, _version()),
            "/demo/status": (200, _demo_status()),
        }
    )


def test_check_normalizes_https_origin_without_constructing_transport() -> None:
    from src.app.services.web_app_readiness_verification import (
        check_web_app_readiness_configuration,
        normalize_web_app_base_url,
    )

    assert normalize_web_app_base_url("  https://Example.COM/  ") == (
        "https://example.com"
    )

    result = check_web_app_readiness_configuration("https://Example.COM/")

    assert result.ok is True
    assert result.mode == "check"
    assert result.category == "success"
    assert result.base_url_valid is True
    assert result.hosted_request_attempted is False
    assert result.health_verified is False
    assert result.version_verified is False
    assert result.demo_status_verified is False
    assert result.safe_hosted_posture_verified is False


@pytest.mark.parametrize(
    ("base_url", "expected_category"),
    [
        (None, "missing_configuration"),
        ("", "missing_configuration"),
        ("http://example.com", "invalid_configuration"),
        ("https://user:password@example.com", "invalid_configuration"),
        ("https://example.com?secret=value", "invalid_configuration"),
        ("https://example.com#fragment", "invalid_configuration"),
        ("https://example.com/application", "invalid_configuration"),
        ("example.com", "invalid_configuration"),
    ],
)
def test_check_rejects_missing_or_unsafe_base_urls(
    base_url: str | None,
    expected_category: str,
) -> None:
    from src.app.services.web_app_readiness_verification import (
        check_web_app_readiness_configuration,
    )

    result = check_web_app_readiness_configuration(base_url)

    assert result.ok is False
    assert result.category == expected_category
    assert result.base_url_valid is False
    assert result.hosted_request_attempted is False
    assert "example.com" not in json.dumps(result.to_json_dict())


def test_live_verifies_exact_read_only_endpoints_and_safe_hosted_posture() -> None:
    from src.app.services.web_app_readiness_verification import (
        DEFAULT_TIMEOUT_SECONDS,
        verify_web_app_readiness,
    )

    transport = _success_transport()
    created_for: list[str] = []

    def factory(normalized_base_url: str) -> FakeTransport:
        created_for.append(normalized_base_url)
        return transport

    result = verify_web_app_readiness(
        f"{BASE_URL}/",
        transport_factory=factory,
        expected_application_artifact_digest=ARTIFACT_DIGEST,
    )

    assert created_for == [BASE_URL]
    assert transport.calls == [
        ("/health", DEFAULT_TIMEOUT_SECONDS),
        ("/version", DEFAULT_TIMEOUT_SECONDS),
        ("/demo/status", DEFAULT_TIMEOUT_SECONDS),
    ]
    assert result.ok is True
    assert result.mode == "live"
    assert result.category == "success"
    assert result.hosted_request_attempted is True
    assert result.health_verified is True
    assert result.version_verified is True
    assert result.demo_status_verified is True
    assert result.safe_hosted_posture_verified is True
    assert result.application_artifact_matches is True
    serialized = json.dumps(result.to_json_dict())
    assert "secret-host" not in serialized
    assert "https://" not in serialized
    assert ARTIFACT_DIGEST not in serialized


def test_old_hosted_artifact_fails_after_accepted_deployment() -> None:
    from src.app.services.web_app_readiness_verification import verify_web_app_readiness

    transport = _success_transport()
    result = verify_web_app_readiness(
        BASE_URL,
        transport_factory=lambda _: transport,
        expected_application_artifact_digest="b" * 64,
    )

    assert result.ok is False
    assert result.category == "application_artifact_mismatch"
    assert result.application_artifact_matches is False
    assert "a" * 64 not in json.dumps(result.to_json_dict())
    assert "b" * 64 not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    ("responses", "expected_category", "expected_progress"),
    [
        (
            {"/health": (503, {"secret": "raw-body"})},
            "unexpected_http_status",
            (False, False, False),
        ),
        (
            {"/health": (200, "not-json secret-host.example")},
            "malformed_json",
            (False, False, False),
        ),
        (
            {"/health": (200, {"status": "ok"})},
            "response_contract_mismatch",
            (False, False, False),
        ),
        (
            {
                "/health": (200, _health()),
                "/version": (200, _version()),
                "/demo/status": (200, _demo_status(aiProvider="foundry")),
            },
            "unsafe_hosted_posture",
            (True, True, True),
        ),
    ],
)
def test_live_classifies_response_failures_without_exposing_payloads(
    responses: dict[str, object],
    expected_category: str,
    expected_progress: tuple[bool, bool, bool],
) -> None:
    from src.app.services.web_app_readiness_verification import (
        verify_web_app_readiness,
    )

    transport = FakeTransport(responses)
    result = verify_web_app_readiness(
        BASE_URL,
        transport_factory=lambda _: transport,
    )

    assert result.ok is False
    assert result.category == expected_category
    assert (
        result.health_verified,
        result.version_verified,
        result.demo_status_verified,
    ) == expected_progress
    serialized = json.dumps(result.to_json_dict())
    for unsafe in (
        "secret-host",
        "raw-body",
        "not-json",
        "https://",
        "Authorization",
        "Bearer",
        "Traceback",
    ):
        assert unsafe not in serialized


@pytest.mark.parametrize(
    ("error_factory", "expected_category"),
    [
        (lambda: _http_error(), "http_request_failed"),
        (lambda: RuntimeError("secret-host.example Bearer token"), "unexpected_error"),
    ],
)
def test_live_classifies_request_and_internal_failures_safely(
    error_factory,
    expected_category: str,
) -> None:
    from src.app.services.web_app_readiness_verification import (
        verify_web_app_readiness,
    )

    transport = FakeTransport({"/health": error_factory()})
    result = verify_web_app_readiness(
        BASE_URL,
        transport_factory=lambda _: transport,
    )

    assert result.ok is False
    assert result.category == expected_category
    assert result.hosted_request_attempted is True
    serialized = json.dumps(result.to_json_dict())
    assert "secret-host" not in serialized
    assert "Bearer" not in serialized
    assert "token" not in serialized


def _http_error() -> Exception:
    from src.app.services.web_app_readiness_verification import HttpRequestError

    return HttpRequestError("secret-host.example Bearer token")


def test_standard_library_transport_uses_get_without_body_credentials_or_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.web_app_readiness_verification as verification

    captured: list[tuple[object, float]] = []
    handlers: list[object] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"status":"ok"}'

    class FakeOpener:
        def open(self, request: object, timeout: float):
            captured.append((request, timeout))
            return FakeResponse()

    def fake_build_opener(*created_handlers: object) -> FakeOpener:
        handlers.extend(created_handlers)
        return FakeOpener()

    monkeypatch.setattr(verification, "build_opener", fake_build_opener)
    transport = verification.UrllibWebAppReadinessTransport(BASE_URL)

    response = transport.get("/health", 3.0)

    request, timeout = captured[0]
    assert len(captured) == 1
    assert request.full_url == f"{BASE_URL}/health"
    assert request.get_method() == "GET"
    assert request.data is None
    assert request.get_header("Authorization") is None
    assert timeout == 3.0
    assert response.status_code == 200
    assert len(handlers) == 1


def test_redirect_is_not_followed_and_stops_readiness_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.web_app_readiness_verification as verification

    opened: list[tuple[object, float]] = []
    handlers: list[object] = []

    class RedirectingOpener:
        def open(self, request: object, timeout: float):
            opened.append((request, timeout))
            raise HTTPError(
                request.full_url,
                302,
                "Found",
                {"Location": "https://other-host.example/unexpected"},
                None,
            )

    def fake_build_opener(*created_handlers: object) -> RedirectingOpener:
        handlers.extend(created_handlers)
        return RedirectingOpener()

    monkeypatch.setattr(verification, "build_opener", fake_build_opener)

    result = verification.verify_web_app_readiness(
        BASE_URL,
        transport_factory=verification.UrllibWebAppReadinessTransport,
    )

    assert result.ok is False
    assert result.category == "unexpected_http_status"
    assert result.health_verified is False
    assert result.version_verified is False
    assert result.demo_status_verified is False
    assert [request.full_url for request, _timeout in opened] == [
        f"{BASE_URL}/health"
    ]
    assert len(handlers) == 1
    assert handlers[0].redirect_request(
        opened[0][0],
        None,
        302,
        "Found",
        {"Location": "https://other-host.example/unexpected"},
        "https://other-host.example/unexpected",
    ) is None


def test_health_contract_validates_only_stable_required_fields() -> None:
    from src.app.services.web_app_readiness_verification import (
        _health_contract_valid,
    )

    assert _health_contract_valid(_health())
    assert _health_contract_valid({**_health(), "revision": "future"})
    assert all(
        not _health_contract_valid(payload)
        for payload in (
            None,
            [],
            {},
            {"status": "ok"},
            {"service": "nurse-intake-assistant"},
            {"status": "healthy", "service": "nurse-intake-assistant"},
            {"status": "ok", "service": 42},
        )
    )


def test_version_contract_accepts_nonempty_values_and_additional_fields() -> None:
    from src.app.services.web_app_readiness_verification import (
        _version_contract_valid,
    )

    assert _version_contract_valid(_version())
    assert _version_contract_valid(
        {
            "service": "nurse-intake-assistant",
            "version": "7.4.2-beta.1",
            "environment": "hosted-test",
            "artifactDigest": "b" * 64,
            "revision": "future",
        }
    )
    assert all(
        not _version_contract_valid(payload)
        for payload in (
            None,
            [],
            {},
            {"service": "nurse-intake-assistant", "version": "1.0.0"},
            {
                "service": "nurse-intake-assistant",
                "version": "",
                "environment": "hosted",
            },
            {
                "service": "nurse-intake-assistant",
                "version": "1.0.0",
                "environment": "",
            },
            {
                "service": "nurse-intake-assistant",
                "version": 100,
                "environment": "hosted",
            },
            {
                "service": "nurse-intake-assistant",
                "version": "1.0.0",
                "environment": False,
            },
            {
                "service": "other-service",
                "version": "1.0.0",
                "environment": "hosted",
            },
        )
    )
