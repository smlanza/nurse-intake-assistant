import json
from pathlib import Path

import pytest

from src.app.services.application_insights_intake_telemetry_proof import (
    ApplicationInsightsIntakeTelemetryProofResult,
)


def _result(**changes: object) -> ApplicationInsightsIntakeTelemetryProofResult:
    values: dict[str, object] = {
        "ok": True,
        "mode": "check",
        "category": "success",
        "fictional_input": True,
        "readiness_verified": True,
        "account_verified": False,
        "application_insights_resource_verified": False,
        "production_composition_used": False,
        "intake_attempted": False,
        "case_persisted_in_memory": False,
        "notifications_suppressed": True,
        "telemetry_provider_verified": True,
        "telemetry_emission_attempted": False,
        "telemetry_emission_count": 0,
        "query_attempted": False,
        "eligible_record_count": 0,
        "telemetry_record_verified": False,
        "allowlisted_dimensions_verified": True,
        "unexpected_dimensions_absent": True,
        "sensitive_content_absent": True,
        "azure_mutation_made": False,
        "recommended_next_step": "Review the sanitized result.",
    }
    values.update(changes)
    return ApplicationInsightsIntakeTelemetryProofResult(**values)


def test_check_mode_is_offline_and_outputs_one_deterministic_json_line(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_application_insights_intake_telemetry as script

    monkeypatch.setattr(script, "_load_check_contract", lambda config: (object(), object()))
    monkeypatch.setattr(script, "_sdk_available", lambda: True)
    monkeypatch.setattr(script, "_cli_available", lambda: True)
    monkeypatch.setattr(script, "build_check_result", lambda **kwargs: _result())
    monkeypatch.setattr(script, "_create_runner", lambda: pytest.fail("no runner"))
    monkeypatch.setattr(script, "compose_application", lambda settings: pytest.fail("no composition"))

    code = script.main(["--check", "--json"])
    captured = capsys.readouterr()

    assert code == 0
    assert captured.err == ""
    assert captured.out.endswith("\n") and not captured.out.endswith("\n\n")
    assert json.loads(captured.out) == _result().to_json_dict()


def test_live_mode_requires_json_config_and_receipt(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_application_insights_intake_telemetry as script

    for argv in (
        ["--live"],
        ["--live", "--json"],
        ["--live", "--json", "--config", ".env.daily-azure.local"],
    ):
        code = script.main(argv)
        payload = json.loads(capsys.readouterr().out)
        assert code == 2
        assert payload["category"] == "invalid_configuration"


def test_invalid_readiness_stops_before_runner_or_composition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_application_insights_intake_telemetry as script

    monkeypatch.setattr(
        script,
        "_load_local_contract",
        lambda config, receipt: (_ for _ in ()).throw(script.ProofCliError("readiness_invalid")),
    )
    monkeypatch.setattr(script, "_create_runner", lambda: pytest.fail("no runner"))
    monkeypatch.setattr(script, "compose_application", lambda settings: pytest.fail("no composition"))

    code = script.main(
        [
            "--live",
            "--json",
            "--config",
            ".env.daily-azure.local",
            "--readiness-receipt",
            ".artifacts/daily-azure-rebuild/readiness-receipt.json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["category"] == "readiness_invalid"


def test_live_cli_uses_default_no_approval_and_sanitized_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_application_insights_intake_telemetry as script

    config = object()
    receipt = object()
    monkeypatch.setattr(script, "_load_local_contract", lambda config_path, receipt_path: (config, receipt))
    monkeypatch.setattr(script, "_sdk_available", lambda: True)
    monkeypatch.setattr(script, "_cli_available", lambda: True)
    monkeypatch.setattr(script, "build_check_result", lambda **kwargs: _result())
    monkeypatch.setattr(script, "_create_runner", lambda: object())
    monkeypatch.setattr(script, "prompt_for_approval", lambda summary: False)

    class FakeProof:
        def __init__(self, **kwargs):
            assert kwargs["config"] is config
            assert kwargs["readiness_receipt"] is receipt
            assert kwargs["approver"] is script.prompt_for_approval

        def run_live(self):
            return _result(ok=False, mode="live", category="approval_declined")

    monkeypatch.setattr(script, "ApplicationInsightsIntakeTelemetryProof", FakeProof)

    code = script.main(
        [
            "--live",
            "--json",
            "--config",
            ".env.daily-azure.local",
            "--readiness-receipt",
            ".artifacts/daily-azure-rebuild/readiness-receipt.json",
        ]
    )
    captured = capsys.readouterr()

    assert code == 2
    assert json.loads(captured.out)["category"] == "approval_declined"
    assert "fictional-daily" not in captured.out
    assert "InstrumentationKey" not in captured.out


def test_unexpected_cli_failure_never_exposes_exception(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.smoke_application_insights_intake_telemetry as script

    monkeypatch.setattr(
        script,
        "_load_check_contract",
        lambda config: (_ for _ in ()).throw(RuntimeError("EXCEPTION_SECRET_SENTINEL")),
    )

    code = script.main(["--check", "--json"])
    captured = capsys.readouterr()

    assert code == 1
    assert json.loads(captured.out)["category"] == "unexpected_error"
    assert "EXCEPTION_SECRET_SENTINEL" not in captured.out
    assert captured.err == ""


def test_check_defaults_use_current_repository_owned_paths() -> None:
    import scripts.smoke_application_insights_intake_telemetry as script

    args = script._parse_args(["--check", "--json"])

    assert args.config == script.ROOT / ".env.daily-azure.local"
    assert args.readiness_receipt == script.ROOT / Path(
        ".artifacts/daily-azure-rebuild/readiness-receipt.json"
    )


def test_check_contract_uses_fictional_receipt_without_loading_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.smoke_application_insights_intake_telemetry as script

    config = object()
    receipt = object()
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *args, **kwargs: config)
    monkeypatch.setattr(
        script,
        "build_fictional_check_readiness_receipt",
        lambda value: receipt if value is config else pytest.fail("wrong config"),
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *args, **kwargs: pytest.fail("check must not read a receipt"),
    )

    assert script._load_check_contract(Path("fictional-config")) == (config, receipt)
