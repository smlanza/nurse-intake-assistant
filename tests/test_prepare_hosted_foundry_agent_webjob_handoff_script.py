import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def _script():
    return importlib.import_module(
        "scripts.prepare_hosted_foundry_agent_webjob_handoff"
    )


ARGS = [
    "--config",
    ".env.daily-azure.local",
    "--readiness-receipt",
    ".artifacts/daily-azure-rebuild/readiness-receipt.json",
    "--json",
]


def _result(*, ok: bool = True):
    return SimpleNamespace(
        ok=ok,
        to_json_dict=lambda: {
            "ok": ok,
            "category": "success" if ok else "generation_evidence_invalid",
            "operation": "prepare_hosted_foundry_agent_webjob_handoff",
            "mode": "live",
            "readiness_receipt_validated": ok,
            "evidence_read_attempted": ok,
            "handoff_persisted": ok,
            "webjob_operation_attempted": False,
        },
    )


def test_check_is_offline_and_constructs_no_reader(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_evidence_reader",
        lambda *_args: pytest.fail("check must not construct a reader"),
    )

    code = script.main(["--check", *ARGS])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "check"


def test_live_validates_receipt_before_constructing_reader(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        script,
        "_create_evidence_reader",
        lambda *_args: pytest.fail("invalid receipt must stop first"),
    )

    code = script.main(["--live", *ARGS])

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["category"] == "readiness_receipt_invalid"
    assert payload["evidence_read_attempted"] is False


def test_live_passes_validated_receipt_to_preparation_and_sanitizes_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    script = _script()
    config = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    receipt = object()
    reader = object()
    store = object()
    captured: list[tuple[object, object, object]] = []
    monkeypatch.setattr(script, "ROOT", tmp_path)
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_args: receipt,
    )
    monkeypatch.setattr(script, "_create_evidence_reader", lambda *_args: reader)
    monkeypatch.setattr(script, "_create_handoff_store", lambda *_args: store)
    monkeypatch.setattr(
        script,
        "prepare_hosted_foundry_agent_webjob_handoff",
        lambda _request, *, readiness_receipt, evidence_reader, handoff_store: (
            captured.append((readiness_receipt, evidence_reader, handoff_store))
            or _result()
        ),
    )

    code = script.main(["--live", *ARGS])

    output = capsys.readouterr().out
    assert code == 0
    assert captured == [(receipt, reader, store)]
    assert "fingerprint" not in output
    assert "fictional-rg" not in output
    assert "fictional-web-app" not in output
