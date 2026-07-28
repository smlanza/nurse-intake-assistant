from io import BytesIO
import json
from types import SimpleNamespace
from urllib.error import HTTPError, URLError

import pytest


TOKEN = "header.payload.signature"
WEBJOB_NAME = "verify-hosted-foundry-agent"


def _service():
    import src.app.services.hosted_foundry_agent_webjob_kudu as service

    return service


class TokenRunner:
    def __init__(self, token: str = TOKEN) -> None:
        self.token = token
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        return SimpleNamespace(
            return_code=0,
            stdout=f"{self.token}\n",
            stderr="secret token stderr",
        )


class Response:
    def __init__(self, payload: bytes, status: object = 200) -> None:
        self.payload = payload
        self.status = status
        self.read_calls: list[int] = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, amount: int) -> bytes:
        self.read_calls.append(amount)
        return self.payload


class Opener:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        return self.response


def _discover(payload: object):
    service = _service()
    response = Response(json.dumps(payload).encode())
    runner = TokenRunner()
    opener = Opener(response)
    result = service.KuduTriggeredWebJobDiscoverer(
        token_runner=runner,
        opener=opener,
    ).discover("fictional-app", WEBJOB_NAME)
    return service, result, runner, opener, response


@pytest.mark.parametrize(
    "payload",
    [
        {"name": WEBJOB_NAME, "run_command": "run.py"},
        {
            "name": WEBJOB_NAME,
            "run_command": "run.py",
            "latest_run": None,
        },
    ],
)
def test_exact_kudu_triggered_webjob_resource_is_authoritative(
    payload: object,
) -> None:
    service, result, runner, opener, response = _discover(payload)

    assert result == service.KuduWebJobDiscoveryResult.success()
    assert runner.calls == [list(service.KUDU_BEARER_TOKEN_COMMAND)]
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert timeout > 0
    assert request.method == "GET"
    assert request.data is None
    assert request.full_url.endswith(
        "/api/triggeredwebjobs/verify-hosted-foundry-agent"
    )
    assert "/run" not in request.full_url
    assert {
        name.casefold(): value
        for name, value in request.header_items()
    } == {"authorization": f"Bearer {TOKEN}"}
    assert len(response.read_calls) == 1
    serialized = json.dumps(result.to_json_dict())
    for forbidden in (
        TOKEN,
        "fictional-app",
        "azurewebsites",
        "run.py",
        WEBJOB_NAME,
    ):
        assert forbidden not in serialized


def test_kudu_discovery_ignores_all_nonproof_top_level_fields() -> None:
    payload = {
        "name": WEBJOB_NAME,
        "run_command": "run.py",
        "latest_run": None,
        "error": {"secret": "ignored-error"},
        "extra_info_url": ["ignored-extra-info"],
        "history_url": {"secret": "ignored-history"},
        "scheduler_logs_url": 17,
        "settings": "ignored-settings",
        "type": {"secret": "ignored-type"},
        "url": ["ignored-url"],
        "using_sdk": "ignored-using-sdk",
        "future_kudu_field": {"secret": "ignored-future"},
    }

    service, result, _runner, _opener, _response = _discover(payload)

    assert result == service.KuduWebJobDiscoveryResult.success()
    serialized = json.dumps(result.to_json_dict())
    assert "ignored" not in serialized
    assert "future_kudu_field" not in serialized


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "authentication_or_authorization_failed"),
        (403, "authentication_or_authorization_failed"),
        (404, "remote_webjob_missing"),
        (429, "discovery_throttled"),
        (500, "discovery_service_failed"),
        (502, "discovery_service_failed"),
        (503, "discovery_service_failed"),
        (418, "discovery_failed"),
    ],
)
def test_kudu_discovery_maps_http_failures_to_sanitized_categories(
    status: int,
    category: str,
) -> None:
    service = _service()

    class RejectingOpener:
        def open(self, _request, timeout):
            assert timeout > 0
            raise HTTPError(
                "https://secret-host.example/secret-path",
                status,
                "secret exception text",
                {"X-Secret": "secret header"},
                BytesIO(b"secret response body"),
            )

    result = service.KuduTriggeredWebJobDiscoverer(
        token_runner=TokenRunner(),
        opener=RejectingOpener(),
    ).discover("fictional-app", WEBJOB_NAME)

    assert result.category == category
    assert result.discovery_attempted is True
    assert result.remote_webjob_discovered is False
    serialized = json.dumps(result.to_json_dict())
    for forbidden in (
        TOKEN,
        "secret-host",
        "secret-path",
        "secret exception",
        "secret response",
        str(status),
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    "failure",
    [
        URLError("secret transport reason"),
        TimeoutError("secret timeout"),
        OSError("secret interruption"),
        RuntimeError("secret unknown read outcome"),
    ],
)
def test_kudu_discovery_transport_failure_is_ambiguous(
    failure: Exception,
) -> None:
    service = _service()

    class FailingOpener:
        def open(self, _request, timeout):
            assert timeout > 0
            raise failure

    result = service.KuduTriggeredWebJobDiscoverer(
        token_runner=TokenRunner(),
        opener=FailingOpener(),
    ).discover("fictional-app", WEBJOB_NAME)

    assert result.category == "discovery_ambiguous"
    assert result.discovery_attempted is True
    assert result.remote_webjob_discovered is False
    assert "secret" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        b"\xff",
        b"[]",
        b'[{"name":"verify-hosted-foundry-agent","run_command":"run.py"}]',
        (
            b'[{"name":"verify-hosted-foundry-agent","run_command":"run.py"},'
            b'{"name":"verify-hosted-foundry-agent","run_command":"run.py"}]'
        ),
        b"{}",
        (
            b'{"name":"verify-hosted-foundry-agent",'
            b'"name":"verify-hosted-foundry-agent",'
            b'"run_command":"run.py"}'
        ),
        b'{"name":"wrong","run_command":"run.py"}',
        b'{"name":"verify-hosted-foundry-agent","run_command":"wrong.py"}',
        (
            b'{"name":"verify-hosted-foundry-agent","run_command":"run.py",'
            b'"latest_run":[]}'
        ),
    ],
)
def test_kudu_discovery_rejects_every_unsupported_response_shape(
    payload: bytes,
) -> None:
    service = _service()
    result = service.KuduTriggeredWebJobDiscoverer(
        token_runner=TokenRunner(),
        opener=Opener(Response(payload)),
    ).discover("fictional-app", WEBJOB_NAME)

    assert result.category == "discovery_response_invalid"
    assert result.discovery_attempted is True
    assert result.remote_webjob_discovered is False
    serialized = json.dumps(result.to_json_dict())
    assert "secret" not in serialized
    assert WEBJOB_NAME not in serialized


def test_kudu_discovery_token_failure_stops_before_http() -> None:
    service = _service()
    runner = TokenRunner("invalid token with spaces")

    class NeverOpen:
        def open(self, *_args, **_kwargs):
            pytest.fail("invalid token must stop before Kudu")

    result = service.KuduTriggeredWebJobDiscoverer(
        token_runner=runner,
        opener=NeverOpen(),
    ).discover("fictional-app", WEBJOB_NAME)

    assert result.category == "authentication_or_authorization_failed"
    assert result.discovery_attempted is False
    assert result.remote_webjob_discovered is False
