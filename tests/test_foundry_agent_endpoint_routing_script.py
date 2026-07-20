import json
from types import SimpleNamespace

import pytest


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        azure_ai_foundry_agent_project_endpoint=(
            "https://secret.example/api/projects/demo"
        ),
        azure_ai_foundry_agent_endpoint=(
            "https://secret.example/api/projects/demo/agents/secret-agent/"
            "endpoint/protocols/openai"
        ),
        azure_ai_foundry_agent_name="secret-agent",
        azure_ai_foundry_agent_version="7",
        azure_ai_foundry_managed_identity_client_id=None,
    )


def test_check_loads_configuration_and_remains_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.configure_foundry_agent_endpoint_routing as script
    from src.app.services.foundry_agent_endpoint_routing import (
        FoundryAgentEndpointRoutingResult,
    )

    requests: list[object] = []

    class FakeRouting:
        def check(self, request: object) -> FoundryAgentEndpointRoutingResult:
            requests.append(request)
            return FoundryAgentEndpointRoutingResult.check_success()

        def configure(self, request: object) -> None:
            pytest.fail("check must not enter live configuration")

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_routing_service", FakeRouting)

    exit_code = script.main(["--check", "--json"])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert len(requests) == 1
    assert payload["ready"] is True
    assert payload["azure_call_made"] is False
    assert payload["azure_mutation_made"] is False
    assert payload["agent_invoked"] is False
    assert "secret.example" not in output
    assert "secret-agent" not in output
    assert '"7"' not in output


def test_live_calls_only_explicit_routing_service_once(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.configure_foundry_agent_endpoint_routing as script
    from src.app.services.foundry_agent_endpoint_routing import (
        FoundryAgentEndpointRoutingResult,
    )

    requests: list[object] = []

    class FakeRouting:
        def check(self, request: object) -> None:
            pytest.fail("live must not substitute check for configuration")

        def configure(self, request: object) -> FoundryAgentEndpointRoutingResult:
            requests.append(request)
            return FoundryAgentEndpointRoutingResult.live_success(updated=True)

    monkeypatch.setattr(script, "AppSettings", _settings)
    monkeypatch.setattr(script, "_create_routing_service", FakeRouting)

    exit_code = script.main(["--live", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert len(requests) == 1
    assert payload["routing_updated"] is True
    assert payload["azure_mutation_made"] is True
    assert payload["agent_invoked"] is False


@pytest.mark.parametrize(
    "missing_attribute",
    [
        "azure_ai_foundry_agent_project_endpoint",
        "azure_ai_foundry_agent_endpoint",
        "azure_ai_foundry_agent_name",
        "azure_ai_foundry_agent_version",
    ],
)
def test_missing_configuration_fails_before_service_creation(
    missing_attribute: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.configure_foundry_agent_endpoint_routing as script

    settings = _settings()
    setattr(settings, missing_attribute, None)
    monkeypatch.setattr(script, "AppSettings", lambda: settings)
    monkeypatch.setattr(
        script,
        "_create_routing_service",
        lambda: pytest.fail("missing configuration must not create service"),
    )

    exit_code = script.main(["--check", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload["category"] == "missing_configuration"
    assert payload["azure_call_made"] is False
    assert payload["agent_invoked"] is False


def test_live_requires_json_and_explicit_mode() -> None:
    import scripts.configure_foundry_agent_endpoint_routing as script

    with pytest.raises(SystemExit):
        script.main(["--live"])
    with pytest.raises(SystemExit):
        script.main([])


def test_missing_env_file_is_sanitized(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.configure_foundry_agent_endpoint_routing as script

    exit_code = script.main(
        ["--check", "--json", "--env-file", str(tmp_path / "missing.env")]
    )

    output = capsys.readouterr().out
    assert exit_code == 2
    assert json.loads(output)["category"] == "missing_configuration"
    assert str(tmp_path) not in output
