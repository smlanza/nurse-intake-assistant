import importlib
import json
from types import SimpleNamespace

import pytest


ARGS = [
    "--resource-group",
    "fictional-rg",
    "--web-app-name",
    "fictional-app",
    "--config",
    ".env.daily-azure.local",
    "--readiness-receipt",
    ".artifacts/daily-azure-rebuild/readiness-receipt.json",
    "--json",
]


def _script():
    return importlib.import_module(
        "scripts.deploy_hosted_foundry_agent_webjob"
    )


def test_check_is_offline_and_creates_no_live_dependency(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_evidence_reader",
        lambda *_args: pytest.fail("check must not create evidence reader"),
    )
    monkeypatch.setattr(
        script,
        "_create_uploader",
        lambda: pytest.fail("check must not create uploader"),
    )
    monkeypatch.setattr(
        script,
        "_create_discoverer",
        lambda: pytest.fail("check must not create discoverer"),
    )

    code = script.main(["--check", *ARGS])

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["category"] == "check_complete"
    assert payload["upload_attempted"] is False


def test_live_prompt_defaults_no_and_stdout_remains_sanitized_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    config = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-app",
    )
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda *_args, **_kwargs: config,
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        script,
        "load_hosted_foundry_agent_webjob_handoff",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        script,
        "_create_evidence_reader",
        lambda *_args: object(),
    )
    captured = []
    factories = []

    def deploy(*_args, approver, discovery_factory, **_kwargs):
        factories.append(discovery_factory)
        captured.append(approver(SimpleNamespace(
            heading="HOSTED WEBJOB DEPLOYMENT",
            facts=(("Upload fixed triggered WebJob", "yes"),),
        )))
        return SimpleNamespace(
            ok=False,
            to_json_dict=lambda: {
                "ok": False,
                "category": "approval_required",
                "upload_attempted": False,
                "trigger_attempted": False,
            },
        )

    monkeypatch.setattr(
        script,
        "deploy_hosted_foundry_agent_webjob",
        deploy,
    )
    monkeypatch.setattr(script.sys, "stdin", SimpleNamespace(readline=lambda: ""))

    code = script.main(["--live", *ARGS])

    streams = capsys.readouterr()
    assert code == 2
    assert captured == [False]
    assert factories == [script._create_discoverer]
    assert json.loads(streams.out)["upload_attempted"] is False
    assert "Proceed? [y/N]" in streams.err
    assert "fictional-rg" not in streams.out + streams.err
    assert "fictional-app" not in streams.out + streams.err
