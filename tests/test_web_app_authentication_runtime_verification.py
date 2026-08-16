import json
from urllib.error import HTTPError

import pytest


BASE_URL = "https://private-runtime-host.example"
PRIVATE_BODY = "private-runtime-response"


def _health() -> dict[str, object]:
    return {"status": "ok", "service": "nurse-intake-assistant"}


def _version() -> dict[str, object]:
    return {
        "service": "nurse-intake-assistant",
        "version": "0.1.0",
        "environment": "hosted",
        "artifactDigest": "a" * 64,
    }


def _demo_status() -> dict[str, object]:
    return {
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


def _evidence(**overrides: object):
    from src.app.services.web_app_authentication_runtime_verification import (
        RuntimeAuthenticationEvidence,
    )

    values: dict[str, object] = {
        "hosted_origin": BASE_URL,
        "ready_current": True,
        "exact_web_app_current": True,
        "artifact_readiness_current": True,
        "authentication_configuration_current": True,
    }
    values.update(overrides)
    return RuntimeAuthenticationEvidence(**values)


class FakeTransport:
    def __init__(self, responses: dict[str, tuple[int, object]]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, float]] = []

    def get(self, path: str, timeout_seconds: float):
        from src.app.services.web_app_readiness_verification import HttpResponse

        self.calls.append((path, timeout_seconds))
        status_code, payload = self.responses[path]
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        return HttpResponse(status_code=status_code, body=body)


def _successful_responses() -> dict[str, tuple[int, object]]:
    return {
        "/health": (200, _health()),
        "/version": (200, _version()),
        "/demo/status": (200, _demo_status()),
        "/demo": (401, PRIVATE_BODY.encode()),
        "/cases": (401, PRIVATE_BODY.encode()),
        "/docs": (401, PRIVATE_BODY.encode()),
        "/openapi.json": (401, PRIVATE_BODY.encode()),
    }


def test_runtime_verifies_exact_fixed_routes_sequentially_without_retry() -> None:
    from src.app.services.web_app_authentication_runtime_verification import (
        ANONYMOUS_PATHS,
        PROTECTED_PATHS,
        verify_web_app_authentication_runtime,
    )

    transport = FakeTransport(_successful_responses())
    created_for: list[str] = []

    def factory(origin: str) -> FakeTransport:
        created_for.append(origin)
        return transport

    result = verify_web_app_authentication_runtime(
        _evidence(),
        transport_factory=factory,
    )

    assert ANONYMOUS_PATHS == ("/health", "/version", "/demo/status")
    assert PROTECTED_PATHS == ("/demo", "/cases", "/docs", "/openapi.json")
    assert created_for == [BASE_URL]
    assert [path for path, _timeout in transport.calls] == [
        *ANONYMOUS_PATHS,
        *PROTECTED_PATHS,
    ]
    assert result.ok is True
    assert result.category == "authentication_perimeter_verified"
    assert result.anonymous_gets_attempted == 3
    assert result.protected_gets_attempted == 4
    assert all(
        (
            result.anonymous_health_verified,
            result.anonymous_version_verified,
            result.anonymous_demo_status_verified,
            result.protected_demo_verified,
            result.protected_cases_verified,
            result.protected_docs_verified,
            result.protected_openapi_verified,
            result.authentication_perimeter_verified,
        )
    )
    serialized = json.dumps(result.to_json_dict())
    assert BASE_URL not in serialized
    assert PRIVATE_BODY not in serialized


def test_anonymous_route_requires_existing_readiness_response_contract() -> None:
    from src.app.services.web_app_authentication_runtime_verification import (
        verify_web_app_authentication_runtime,
    )

    responses = _successful_responses()
    responses["/version"] = (200, {"private": PRIVATE_BODY})
    transport = FakeTransport(responses)

    result = verify_web_app_authentication_runtime(
        _evidence(),
        transport_factory=lambda _origin: transport,
    )

    assert result.ok is False
    assert result.category == "anonymous_route_acceptance_failed"
    assert result.route == "version"
    assert result.reason == "response_contract_mismatch"
    assert [path for path, _timeout in transport.calls] == ["/health", "/version"]
    serialized = json.dumps(result.to_json_dict())
    assert BASE_URL not in serialized
    assert PRIVATE_BODY not in serialized


@pytest.mark.parametrize("status_code", (200, 302))
def test_protected_success_or_redirect_fails_closed(status_code: int) -> None:
    from src.app.services.web_app_authentication_runtime_verification import (
        verify_web_app_authentication_runtime,
    )

    responses = _successful_responses()
    responses["/demo"] = (status_code, PRIVATE_BODY.encode())
    transport = FakeTransport(responses)

    result = verify_web_app_authentication_runtime(
        _evidence(),
        transport_factory=lambda _origin: transport,
    )

    assert result.ok is False
    assert result.category == "protected_route_acceptance_failed"
    assert result.route == "demo"
    assert result.reason == "protected_route_not_401"
    assert result.anonymous_gets_attempted == 3
    assert result.protected_gets_attempted == 1
    assert [path for path, _timeout in transport.calls].count("/demo") == 1


@pytest.mark.parametrize(
    "missing_field",
    (
        "ready_current",
        "exact_web_app_current",
        "artifact_readiness_current",
        "authentication_configuration_current",
    ),
)
def test_each_current_evidence_contract_blocks_before_transport(
    missing_field: str,
) -> None:
    from src.app.services.web_app_authentication_runtime_verification import (
        verify_web_app_authentication_runtime,
    )

    result = verify_web_app_authentication_runtime(
        _evidence(**{missing_field: False}),
        transport_factory=lambda _origin: pytest.fail(
            "invalid evidence must stop before transport construction"
        ),
    )

    assert result.ok is False
    assert result.category == "safe_runtime_verification_blocked"
    assert result.reason == "readiness_evidence_invalid"
    assert result.anonymous_gets_attempted == 0
    assert result.protected_gets_attempted == 0


def test_standard_transport_sends_no_credentials_cookies_or_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.web_app_readiness_verification as readiness
    from src.app.services.web_app_authentication_runtime_verification import (
        verify_web_app_authentication_runtime,
    )

    requests: list[object] = []
    handlers: list[object] = []

    class FakeResponse:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.body

    class FakeOpener:
        def open(self, request: object, timeout: float):
            requests.append(request)
            path = request.full_url.removeprefix(BASE_URL)
            if path == "/health":
                return FakeResponse(json.dumps(_health()).encode())
            if path == "/version":
                return FakeResponse(json.dumps(_version()).encode())
            if path == "/demo/status":
                return FakeResponse(json.dumps(_demo_status()).encode())
            raise HTTPError(request.full_url, 401, PRIVATE_BODY, {}, None)

    def fake_build_opener(*created_handlers: object) -> FakeOpener:
        handlers.extend(created_handlers)
        return FakeOpener()

    monkeypatch.setattr(readiness, "build_opener", fake_build_opener)

    result = verify_web_app_authentication_runtime(
        _evidence(),
        transport_factory=readiness.UrllibWebAppReadinessTransport,
    )

    assert result.ok is True
    assert len(requests) == 7
    assert all(request.get_method() == "GET" for request in requests)
    assert all(request.data is None for request in requests)
    assert all(request.get_header("Authorization") is None for request in requests)
    assert all(request.get_header("Cookie") is None for request in requests)
    assert len(handlers) == 1
    assert handlers[0].redirect_request(
        requests[3],
        None,
        302,
        "Found",
        {"Location": "https://login.example/private"},
        "https://login.example/private",
    ) is None
