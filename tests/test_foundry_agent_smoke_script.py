import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.services.foundry_agent_client import FoundryAgentClientError
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
    FoundryExtractionParseError,
)


def _settings(
    agent_provider: str = "foundry",
    project_endpoint: str | None = (
        "https://secret-agent.services.ai.azure.com/api/projects/demo"
    ),
    foundry_project_endpoint: str | None = None,
    agent_id: str | None = "secret-agent-id",
) -> SimpleNamespace:
    return SimpleNamespace(
        agent_provider_normalized=agent_provider,
        azure_ai_foundry_agent_project_endpoint=project_endpoint,
        azure_ai_foundry_project_endpoint=foundry_project_endpoint,
        azure_ai_foundry_agent_id=agent_id,
    )


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: SimpleNamespace) -> None:
    import scripts.smoke_foundry_agent as script

    monkeypatch.setattr(script, "AppSettings", lambda: settings)


class FakeAgent:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        self.calls.append(raw_text)
        return SimpleNamespace(
            extraction=SimpleNamespace(
                patient=SimpleNamespace(name="Demo Patient"),
                reason_for_calling="routine medication refill",
                symptoms=["fatigue"],
                summary="Demo patient requests a routine medication refill.",
            ),
            urgency=SimpleNamespace(urgency="Routine"),
            handoffNote="Demo handoff note.",
            metadata=SimpleNamespace(provider="foundry", agentMode="manual-smoke"),
        )


class FailingAgent:
    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        raise RuntimeError("raw secret endpoint failure")


class StatusCodeError(Exception):
    def __init__(self, status_code: int, message: str = "raw secret message") -> None:
        super().__init__(message)
        self.status_code = status_code


class CategoryFailingAgent:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        raise self.error


class ContractInvalidAgent:
    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        raise FoundryExtractionContractError(
            "raw model output: {\"patient\":\"secret\"}"
        )


class ContractInvalidResultAgent:
    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        return SimpleNamespace(
            extraction=SimpleNamespace(summary="   "),
            urgency=SimpleNamespace(urgency="Routine"),
            handoffNote="Demo handoff note.",
        )


class ParseFailingAgent:
    async def analyze_intake(self, raw_text: str) -> SimpleNamespace:
        raise FoundryExtractionParseError(
            "raw model output: {malformed secret-agent-id}"
        )


def _patch_script_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    env_text: str,
) -> Path:
    env_file = tmp_path / ".env.foundry-agent.local"
    env_file.write_text(env_text)
    return env_file


def _json_output(captured: pytest.CaptureFixture[str]) -> dict[str, object]:
    return json.loads(captured.readouterr().out)


def test_foundry_agent_environment_readiness_reports_ready_when_present() -> None:
    import scripts.smoke_foundry_agent as script

    summary = script.build_foundry_agent_environment_readiness(
        _settings(agent_provider="foundry-agent"),
        sdk_available=True,
    )

    assert summary.provider == "foundry-agent"
    assert summary.mode == "check"
    assert summary.ready is True
    assert summary.required_settings_present == [
        "AGENT_PROVIDER",
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ID",
    ]
    assert summary.required_settings_missing == []
    assert summary.optional_settings_present == []
    assert summary.sdk_available is True
    assert summary.live_json_command_hint == (
        "python scripts/smoke_foundry_agent.py "
        "--env-file .env.foundry-agent.local --live --json"
    )
    assert "manual live JSON validation" in summary.recommended_next_step


def test_foundry_agent_environment_readiness_reports_missing_endpoint_safely() -> None:
    import scripts.smoke_foundry_agent as script

    summary = script.build_foundry_agent_environment_readiness(
        _settings(
            agent_provider="foundry-agent",
            project_endpoint=None,
            foundry_project_endpoint=None,
            agent_id="secret-agent-id",
        ),
        sdk_available=True,
    )

    assert summary.ready is False
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in summary.required_settings_missing
    assert "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" in summary.required_settings_missing
    combined_summary = str(summary)
    assert "secret-agent-id" not in combined_summary
    assert "https://secret-agent.services.ai.azure.com" not in combined_summary


def test_foundry_agent_environment_readiness_reports_missing_agent_id_safely() -> None:
    import scripts.smoke_foundry_agent as script

    summary = script.build_foundry_agent_environment_readiness(
        _settings(agent_provider="foundry-agent", agent_id=None),
        sdk_available=True,
    )

    assert summary.ready is False
    assert "AZURE_AI_FOUNDRY_AGENT_ID" in summary.required_settings_missing
    assert "secret-agent-id" not in str(summary)


def test_foundry_agent_environment_readiness_accepts_project_endpoint_alias() -> None:
    import scripts.smoke_foundry_agent as script

    summary = script.build_foundry_agent_environment_readiness(
        _settings(
            agent_provider="foundry",
            project_endpoint=None,
            foundry_project_endpoint=(
                "https://fallback-secret.services.ai.azure.com/api/projects/demo"
            ),
            agent_id="secret-agent-id",
        ),
        sdk_available=True,
    )

    assert summary.ready is True
    assert "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" in summary.required_settings_present
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" not in (
        summary.required_settings_missing
    )
    assert "fallback-secret" not in str(summary)


def test_foundry_agent_environment_readiness_reports_sdk_without_client_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.smoke_foundry_agent as script

    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created by readiness helper"),
    )

    summary = script.build_foundry_agent_environment_readiness(
        _settings(agent_provider="foundry-agent"),
        sdk_available=False,
    )

    assert summary.ready is False
    assert summary.required_settings_missing == []
    assert summary.sdk_available is False
    assert "Install the optional Azure AI Foundry Agent SDK" in (
        summary.recommended_next_step
    )


def test_foundry_agent_smoke_script_requires_foundry_provider(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="mock"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Foundry Agent smoke-test environment check needs attention" in captured.err
    assert "Required settings missing: AGENT_PROVIDER" in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_reports_missing_preflight_settings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(project_endpoint=None, agent_id=None))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created"),
    )

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Required settings missing:" in captured.err
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in captured.err
    assert "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT" in captured.err
    assert "AZURE_AI_FOUNDRY_AGENT_ID" in captured.err
    assert "secret-agent" not in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_check_does_not_create_agent_or_live_client(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created in --check"),
    )
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "No Foundry Agent client was created" in captured.out
    assert "No Azure call was made" in captured.out
    assert "Live JSON command hint:" in captured.out
    assert "--live --json" in captured.out
    assert "Optional Foundry Agent SDK package appears importable" in captured.out
    assert "secret-agent" not in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_check_reports_sdk_visibility_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: False)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "environment check needs attention" in captured.out
    assert "Optional Foundry Agent SDK package is not importable" in captured.out
    assert "Install the optional Azure AI Foundry Agent SDK" in captured.out
    assert "No Azure call was made" in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_check_output_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(
        monkeypatch,
        _settings(
            agent_provider="foundry-agent",
            project_endpoint=(
                "https://secret-agent.services.ai.azure.com/api/projects/demo"
            ),
            agent_id="secret-agent-id",
        ),
    )
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)

    exit_code = script.main(["--check"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert exit_code == 0
    assert "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT" in combined_output
    assert "AZURE_AI_FOUNDRY_AGENT_ID" in combined_output
    assert "https://secret-agent.services.ai.azure.com" not in combined_output
    assert "secret-agent-id" not in combined_output
    assert "bearer" not in combined_output.lower()
    assert "token" not in combined_output.lower()
    assert "Traceback" not in combined_output
    assert "raw prompt" not in combined_output.lower()
    assert "raw model" not in combined_output.lower()
    assert "taylor quinn" not in combined_output.lower()
    assert "demo-callback-002" not in combined_output


def test_foundry_agent_smoke_script_default_does_not_call_live_agent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created without --live"),
    )

    exit_code = script.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "--check" in captured.err
    assert "--live" in captured.err
    assert "--print-agent-instructions" in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_prints_agent_instructions_without_settings(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    monkeypatch.setattr(
        script,
        "AppSettings",
        lambda: pytest.fail("Settings should not be loaded for instruction printing"),
    )
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created"),
    )
    monkeypatch.setattr(
        script,
        "foundry_agent_sdk_available",
        lambda: pytest.fail("SDK should not be checked"),
    )

    exit_code = script.main(["--print-agent-instructions"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Foundry Agent Instruction Pack" in captured.out
    assert "Instruction version: foundry-agent-intake-v1" in captured.out
    assert "Return JSON only" in captured.out
    assert "Expected JSON shape:" in captured.out
    assert "Fictional test input:" in captured.out
    assert "python scripts/smoke_foundry_agent.py --env-file .env.foundry-agent.local --check" in captured.out
    assert "--live --json" in captured.out
    assert "mock/offline by default" in captured.out
    assert "Restore AGENT_PROVIDER=mock" in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_print_agent_instructions_output_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "https://secret-agent.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", "secret-agent-id")
    monkeypatch.setenv("NURSE_NOTIFICATION_EMAIL", "real.person@example.com")
    monkeypatch.setenv("NURSE_NOTIFICATION_PHONE_NUMBER", "+1 555 555 0123")

    exit_code = script.main(["--print-agent-instructions"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    assert exit_code == 0
    for unsafe_text in [
        "https://secret-agent.services.ai.azure.com",
        "secret-agent-id",
        "bearer",
        "token",
        "raw model output",
        "real.person@example.com",
        "+1 555 555 0123",
        "Traceback",
    ]:
        assert unsafe_text not in combined_output


def test_foundry_agent_smoke_script_calls_agent_only_in_live_mode(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    fake_agent = FakeAgent()
    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: fake_agent,
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert fake_agent.calls == [script.FICTIONAL_AGENT_INTAKE_TEXT]
    assert "Foundry Agent smoke test completed" in captured.out
    assert "Routine" in captured.out
    assert "routine medication refill" in captured.out
    assert "fictional demo intake" in captured.out
    assert "secret-agent" not in captured.out
    assert "instructions" not in captured.out.lower()
    assert captured.err == ""


def test_foundry_agent_smoke_script_live_json_success_summary_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    fake_agent = FakeAgent()
    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(script, "create_nurse_intake_agent", lambda settings: fake_agent)

    exit_code = script.main(["--live", "--json"])

    payload = _json_output(capsys)
    assert exit_code == 0
    assert payload == {
        "ok": True,
        "mode": "live",
        "provider": "foundry-agent",
        "category": "success",
        "message": "Live Foundry Agent smoke validation completed successfully.",
        "agent_attempted": True,
        "agent_output_valid": True,
        "fallback_used": False,
        "fields_present": ["extraction", "urgency", "handoffNote"],
        "recommended_next_step": "No action needed for this manual smoke result.",
    }
    assert fake_agent.calls == [script.FICTIONAL_AGENT_INTAKE_TEXT]


def test_foundry_agent_smoke_script_live_json_authentication_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(
        monkeypatch,
        _settings(
            agent_provider="foundry-agent",
            project_endpoint="https://secret-agent.services.ai.azure.com/api/projects/demo",
            agent_id="secret-agent-id",
        ),
    )
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: CategoryFailingAgent(
            StatusCodeError(401, "raw bearer token endpoint secret")
        ),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["category"] == "authentication_or_authorization_failed"
    assert (
        payload["recommended_next_step"]
        == "Check Azure login, tenant access, and project RBAC permissions."
    )
    combined_output = captured.out + captured.err
    assert "raw bearer token endpoint secret" not in combined_output
    assert "https://secret-agent.services.ai.azure.com" not in combined_output
    assert "secret-agent-id" not in combined_output
    assert "Traceback" not in combined_output


@pytest.mark.parametrize(
    ("error", "safe_category"),
    [
        (
            StatusCodeError(403, "raw RBAC secret"),
            "authentication_or_authorization_failed",
        ),
        (StatusCodeError(404, "raw agent secret-agent-id"), "azure_request_failed"),
        (StatusCodeError(400, "raw Azure bad request detail"), "azure_request_failed"),
        (RuntimeError("unexpected raw exception secret"), "unexpected_error"),
    ],
)
def test_foundry_agent_smoke_script_live_json_failures_map_to_safe_categories(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    safe_category: str,
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: CategoryFailingAgent(error),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["category"] == safe_category
    combined_output = captured.out + captured.err
    assert "raw" not in combined_output
    assert "secret" not in combined_output
    assert "secret-agent-id" not in combined_output
    assert "Traceback" not in combined_output


def test_foundry_agent_smoke_script_live_json_contract_invalid_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: ContractInvalidAgent(),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["category"] == "contract_invalid"
    assert payload["agent_output_valid"] is False
    assert "raw model output" not in captured.out
    assert "patient" not in captured.out
    assert "Traceback" not in captured.out + captured.err


def test_foundry_agent_smoke_script_live_json_contract_invalid_result_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: ContractInvalidResultAgent(),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["category"] == "contract_invalid"
    assert payload["agent_attempted"] is True
    assert payload["agent_output_valid"] is False
    assert payload["fields_present"] == ["extraction", "urgency", "handoffNote"]
    assert "summary" not in captured.out
    assert "Traceback" not in captured.out + captured.err


def test_foundry_agent_smoke_script_live_json_parse_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(
        monkeypatch,
        _settings(
            agent_provider="foundry-agent",
            project_endpoint="https://secret-agent.services.ai.azure.com/api/projects/demo",
            agent_id="secret-agent-id",
        ),
    )
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: ParseFailingAgent(),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["category"] == "response_parse_failed"
    assert payload["agent_output_valid"] is False
    combined_output = captured.out + captured.err
    assert "raw model output" not in combined_output
    assert "{malformed secret-agent-id}" not in combined_output
    assert "https://secret-agent.services.ai.azure.com" not in combined_output
    assert "secret-agent-id" not in combined_output
    assert "Traceback" not in combined_output


def test_foundry_agent_smoke_script_live_json_missing_configuration_not_attempted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(
        monkeypatch,
        _settings(
            agent_provider="foundry-agent",
            project_endpoint=None,
            agent_id=None,
        ),
    )
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created"),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert payload["provider"] == "foundry-agent"
    assert payload["mode"] == "live"
    assert payload["ok"] is False
    assert payload["agent_attempted"] is False
    assert payload["agent_output_valid"] is None
    assert payload["category"] == "missing_configuration"
    assert "secret-agent" not in captured.out + captured.err


def test_foundry_agent_smoke_script_live_json_sdk_unavailable_not_attempted(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: False)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created"),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["category"] == "sdk_unavailable"
    assert payload["agent_attempted"] is False
    assert payload["agent_output_valid"] is None
    assert "secret-agent" not in captured.out + captured.err


def test_foundry_agent_smoke_script_live_json_sdk_construction_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: (_ for _ in ()).throw(
            FoundryAgentClientError(
                "secret SDK detail",
                category="foundry-agent-sdk-unavailable",
            )
        ),
    )

    exit_code = script.main(["--live", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["category"] == "sdk_unavailable"
    assert payload["agent_attempted"] is False
    assert "secret SDK detail" not in captured.out + captured.err


def test_foundry_agent_smoke_script_live_json_schema_is_stable_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: CategoryFailingAgent(StatusCodeError(500)),
    )

    exit_code = script.main(["--live", "--json"])

    payload = _json_output(capsys)
    assert exit_code == 1
    assert list(payload) == [
        "ok",
        "mode",
        "provider",
        "category",
        "message",
        "agent_attempted",
        "agent_output_valid",
        "fallback_used",
        "fields_present",
        "recommended_next_step",
    ]
    assert payload["category"] == "azure_request_failed"
    assert payload["agent_output_valid"] is None


def test_foundry_agent_smoke_script_returns_nonzero_on_agent_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: FailingAgent(),
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Foundry Agent smoke test failed" in captured.err
    assert "Safe failure category: unknown" in captured.err
    assert "Next check:" in captured.err
    assert "raw secret endpoint failure" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (StatusCodeError(401, "bearer token secret"), "authentication"),
        (StatusCodeError(403, "forbidden endpoint secret"), "authorization"),
        (StatusCodeError(404, "agent id secret not found"), "not_found"),
        (StatusCodeError(400, "bad prompt secret"), "bad_request"),
        (
            FoundryExtractionContractError("raw prompt parse secret"),
            "parsing",
        ),
        (RuntimeError("full endpoint token secret"), "unknown"),
    ],
)
def test_foundry_agent_smoke_script_live_failures_are_categorized_safely(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: BaseException,
    category: str,
) -> None:
    import scripts.smoke_foundry_agent as script

    _patch_settings(monkeypatch, _settings(agent_provider="foundry-agent"))
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: CategoryFailingAgent(error),
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert f"Safe failure category: {category}" in captured.err
    assert "Next check:" in captured.err
    assert "secret" not in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_foundry_agent_smoke_script_classifies_client_error_categories() -> None:
    import scripts.smoke_foundry_agent as script

    assert (
        script.classify_live_agent_failure(
            FoundryAgentClientError("secret", category="foundry-agent-sdk-unavailable")
        )
        == "sdk_missing"
    )
    assert (
        script.classify_live_agent_failure(
            FoundryAgentClientError("secret", category="foundry-agent-missing-configuration")
        )
        == "configuration"
    )


def test_foundry_agent_smoke_script_does_not_send_notifications(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script
    import src.app.services.email_notification_sender_factory as email_factory
    import src.app.services.sms_notification_sender_factory as sms_factory

    fake_agent = FakeAgent()
    _patch_settings(monkeypatch, _settings())
    monkeypatch.setattr(script, "create_nurse_intake_agent", lambda settings: fake_agent)
    monkeypatch.setattr(
        email_factory,
        "create_email_notification_sender",
        lambda settings: pytest.fail("Email sender should not be created"),
    )
    monkeypatch.setattr(
        sms_factory,
        "create_sms_notification_sender",
        lambda settings: pytest.fail("SMS sender should not be created"),
    )

    exit_code = script.main(["--live"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no email or SMS was sent" in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_env_file_check_loads_missing_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    env_file = _patch_script_env(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "AGENT_PROVIDER=foundry-agent",
                "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT=https://secret-agent.services.ai.azure.com/api/projects/demo",
                "AZURE_AI_FOUNDRY_AGENT_ID=secret-agent-id",
            ]
        ),
    )
    for key in [
        "AGENT_PROVIDER",
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "AZURE_AI_FOUNDRY_AGENT_ID",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)
    monkeypatch.setattr(
        script,
        "create_nurse_intake_agent",
        lambda settings: pytest.fail("Agent should not be created in --check"),
    )

    exit_code = script.main(["--env-file", str(env_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Loaded Foundry Agent smoke environment file" in captured.out
    assert "preflight passed" in captured.out
    assert "secret-agent" not in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_shell_env_overrides_env_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    env_file = _patch_script_env(
        monkeypatch,
        tmp_path,
        "\n".join(
            [
                "AGENT_PROVIDER=mock",
                "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT=https://file-secret.services.ai.azure.com/api/projects/demo",
                "AZURE_AI_FOUNDRY_AGENT_ID=file-secret-agent-id",
            ]
        ),
    )
    monkeypatch.setenv("AGENT_PROVIDER", "foundry-agent")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "https://shell-secret.services.ai.azure.com/api/projects/demo",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_AGENT_ID", "shell-secret-agent-id")
    monkeypatch.setattr(script, "foundry_agent_sdk_available", lambda: True)

    exit_code = script.main(["--env-file", str(env_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "preflight passed" in captured.out
    assert "file-secret" not in captured.out
    assert "shell-secret" not in captured.out
    assert captured.err == ""


def test_foundry_agent_smoke_script_missing_env_file_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_foundry_agent as script

    missing_file = tmp_path / "secret-agent.env"

    exit_code = script.main(["--env-file", str(missing_file), "--check"])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Foundry Agent smoke env file not found" in captured.err
    assert "secret-agent.env" not in captured.err
    assert "No Azure call was made" in captured.err
    assert captured.out == ""
