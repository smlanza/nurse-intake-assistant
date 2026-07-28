from datetime import datetime, timezone
import importlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest


VALID_NAMES = [
    "--resource-group", "fictional-rg",
    "--web-app-name", "fictional-web-app",
    "--json",
]
LIVE_EVIDENCE = ["--environment-fingerprint", "a" * 64]
HANDOFF_INPUTS = [
    "--config",
    ".env.daily-azure.local",
    "--readiness-receipt",
    ".artifacts/daily-azure-rebuild/readiness-receipt.json",
]


def _script():
    return importlib.import_module("scripts.run_hosted_foundry_agent_verification")


def _service():
    return importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_execution"
    )


class MemoryStore:
    def __init__(self, receipt=None) -> None:
        self.receipt = receipt
        self.outcome = None
        self.reservation = False

    def acquire_reservation(self):
        if self.reservation:
            return None
        self.reservation = True
        return _service().TriggerReservation(1, 1)

    def release_reservation(self, reservation) -> None:
        self.reservation = False

    def reservation_exists(self) -> bool:
        return self.reservation

    def read(self):
        return self.receipt

    def write(self, receipt) -> None:
        self.receipt = receipt

    def read_blocked(self):
        return None

    def write_blocked(self, blocked) -> None:
        raise AssertionError("blocked state is unexpected")

    def read_outcome(self):
        return self.outcome

    def write_outcome(self, outcome) -> None:
        self.outcome = outcome


def _receipt():
    service = _service()
    return service.TriggerReceipt(
        schema_version=service.TRIGGER_RECEIPT_SCHEMA_VERSION,
        state="accepted",
        trigger_not_before=datetime(2026, 7, 19, 10, tzinfo=timezone.utc),
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        webjob_name=service.WEBJOB_NAME,
        environment_fingerprint="a" * 64,
    )


def _install_generation_handoff(
    monkeypatch: pytest.MonkeyPatch,
    script,
) -> None:
    config = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    readiness = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    handoff = SimpleNamespace(environment_fingerprint="a" * 64)
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda *_args, **_kwargs: config,
    )
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_args: readiness,
    )
    monkeypatch.setattr(
        script,
        "load_hosted_foundry_agent_webjob_handoff",
        lambda *_args, **_kwargs: handoff,
    )


def test_import_and_check_construct_no_runner_or_azure_operation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sys.modules.pop("scripts.run_hosted_foundry_agent_verification", None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("import/check must not execute CLI"),
    )
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("check must not construct a runner"),
    )
    monkeypatch.setattr(
        script,
        "_create_kudu_discoverer",
        lambda: pytest.fail("check must not construct a discoverer"),
    )

    exit_code = script.main(["--check", *VALID_NAMES])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["mode"] == "check"
    assert payload["azure_operation_attempted"] is False
    assert payload["remote_webjob_discovered"] is False
    assert payload["invocation_attempted"] is False


def test_cli_requires_one_explicit_mode_names_and_json() -> None:
    script = _script()
    for argv in (
        [],
        ["--check", "--live-discover", *VALID_NAMES],
        ["--check", "--live-trigger", *VALID_NAMES],
        ["--check", "--resource-group", "rg", "--web-app-name", "app"],
        ["--check", "--web-app-name", "app", "--json"],
        ["--live-status", "--resource-group", "rg", "--json"],
    ):
        with pytest.raises(SystemExit):
            script.main(argv)


@pytest.mark.parametrize(
    ("mode", "stdout"),
    [
        ("--live-discover", '[{"name":"verify-hosted-foundry-agent"}]'),
        ("--live-trigger", "{}"),
        (
            "--live-status",
            '[{"status":"Success","start_time":"2026-07-19T10:00:00Z"}]',
        ),
    ],
)
def test_live_modes_lazily_construct_one_runner_and_print_sanitized_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    stdout: str,
) -> None:
    script = _script()
    service = _service()
    store = MemoryStore(_receipt() if mode == "--live-status" else None)
    monkeypatch.setattr(service, "FileTriggerReceiptStore", lambda _root: store)

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def run(self, args: list[str]):
            self.calls.append(args)
            return service.CommandResult(0, stdout, "raw stderr")

    created: list[bool] = []
    _install_generation_handoff(monkeypatch, script)
    if mode == "--live-discover":
        kudu = importlib.import_module(
            "src.app.services.hosted_foundry_agent_webjob_kudu"
        )

        class Discoverer:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def discover(self, web_app_name: str, webjob_name: str):
                self.calls.append((web_app_name, webjob_name))
                return kudu.KuduWebJobDiscoveryResult.success()

        dependency = Discoverer()

        def factory():
            created.append(True)
            return dependency

        monkeypatch.setattr(script, "_create_kudu_discoverer", factory)
        monkeypatch.setattr(
            script,
            "_create_azure_cli_runner",
            lambda: pytest.fail("discovery must not use CLI WebJob list"),
        )
    else:
        dependency = FakeRunner()

        def factory():
            created.append(True)
            return dependency

        monkeypatch.setattr(script, "_create_azure_cli_runner", factory)

    exit_code = script.main([mode, *VALID_NAMES, *HANDOFF_INPUTS])

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert created == [True]
    assert len(dependency.calls) == 1
    assert payload["invocation_attempted"] is (mode == "--live-status")
    if mode == "--live-discover":
        assert dependency.calls == [
            ("fictional-web-app", service.WEBJOB_NAME)
        ]
        assert payload["remote_webjob_discovered"] is True
    for forbidden in (
        "fictional-rg", "fictional-web-app", "raw stderr", "discarded", "2026-07-19",
    ):
        assert forbidden not in output


def test_status_without_receipt_fails_before_runner_factory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    service = _service()
    monkeypatch.setattr(service, "FileTriggerReceiptStore", lambda _root: MemoryStore())
    _install_generation_handoff(monkeypatch, script)
    created: list[bool] = []
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: created.append(True),
    )

    exit_code = script.main(["--live-status", *VALID_NAMES, *HANDOFF_INPUTS])

    assert exit_code == 2
    assert json.loads(capsys.readouterr().out)["category"] == "trigger_receipt_missing"
    assert created == []


@pytest.mark.parametrize(
    ("mode", "stdout"),
    [
        ("--live-discover", '[{"name":"verify-hosted-foundry-agent"}]'),
        ("--live-trigger", "{}"),
        (
            "--live-status",
            '[{"status":"Success","start_time":"2026-07-19T10:00:00Z"}]',
        ),
    ],
)
def test_live_modes_consume_private_handoff_without_operator_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    stdout: str,
) -> None:
    script = _script()
    service = _service()
    store = MemoryStore(_receipt() if mode == "--live-status" else None)
    monkeypatch.setattr(service, "FileTriggerReceiptStore", lambda _root: store)
    config = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    readiness = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    handoff = SimpleNamespace(environment_fingerprint="a" * 64)
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_args: readiness,
    )
    monkeypatch.setattr(
        script,
        "load_hosted_foundry_agent_webjob_handoff",
        lambda *_args, **_kwargs: handoff,
    )

    class Runner:
        def run(self, _args):
            return service.CommandResult(0, stdout, "")

    if mode == "--live-discover":
        kudu = importlib.import_module(
            "src.app.services.hosted_foundry_agent_webjob_kudu"
        )

        class Discoverer:
            def discover(self, _web_app_name, _webjob_name):
                return kudu.KuduWebJobDiscoveryResult.success()

        monkeypatch.setattr(
            script,
            "_create_kudu_discoverer",
            Discoverer,
        )
    else:
        monkeypatch.setattr(script, "_create_azure_cli_runner", Runner)

    code = script.main(
        [
            mode,
            *VALID_NAMES,
            "--config",
            ".env.daily-azure.local",
            "--readiness-receipt",
            ".artifacts/daily-azure-rebuild/readiness-receipt.json",
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "a" * 64 not in output
    assert "environment_fingerprint" not in output


def test_invalid_readiness_or_handoff_stops_before_runner_factory(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    config = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("invalid handoff must stop before runner"),
    )
    monkeypatch.setattr(
        script,
        "_create_kudu_discoverer",
        lambda: pytest.fail("invalid handoff must stop before discoverer"),
    )

    code = script.main(
        [
            "--live-discover",
            *VALID_NAMES,
            "--config",
            ".env.daily-azure.local",
            "--readiness-receipt",
            ".artifacts/daily-azure-rebuild/readiness-receipt.json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["category"] == "generation_handoff_invalid"


@pytest.mark.parametrize(
    "mode",
    ["--live-discover", "--live-trigger", "--live-status"],
)
def test_operator_fingerprint_cannot_bypass_receipt_and_private_handoff(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("missing receipt and handoff must stop before runner"),
    )
    monkeypatch.setattr(
        script,
        "_create_kudu_discoverer",
        lambda: pytest.fail(
            "missing receipt and handoff must stop before discoverer"
        ),
    )

    code = script.main([mode, *VALID_NAMES, *LIVE_EVIDENCE])

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["category"] == "generation_handoff_invalid"
    assert payload["azure_operation_attempted"] is False


def test_conflicting_direct_and_handoff_fingerprints_fail_before_runner(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    config = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    readiness = SimpleNamespace(
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
    )
    handoff = SimpleNamespace(environment_fingerprint="a" * 64)
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_args, **_kwargs: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_args: readiness,
    )
    monkeypatch.setattr(
        script,
        "load_hosted_foundry_agent_webjob_handoff",
        lambda *_args, **_kwargs: handoff,
    )
    monkeypatch.setattr(
        script,
        "_create_azure_cli_runner",
        lambda: pytest.fail("conflict must stop before runner"),
    )
    monkeypatch.setattr(
        script,
        "_create_kudu_discoverer",
        lambda: pytest.fail("conflict must stop before discoverer"),
    )

    code = script.main(
        [
            "--live-discover",
            *VALID_NAMES,
            "--config",
            ".env.daily-azure.local",
            "--readiness-receipt",
            ".artifacts/daily-azure-rebuild/readiness-receipt.json",
            "--environment-fingerprint",
            "b" * 64,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["category"] == "generation_handoff_invalid"


def test_subprocess_runner_uses_safe_argument_list_and_never_prints(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    captured: list[tuple[object, dict[str, object]]] = []

    class Completed:
        returncode = 0
        stdout = "raw stdout"
        stderr = "raw stderr"

    def fake_run(args: object, **kwargs: object) -> Completed:
        captured.append((args, kwargs))
        return Completed()

    monkeypatch.setattr(script.subprocess, "run", fake_run)
    args = ["az", "account", "show"]

    result = script.SubprocessAzureCliRunner().run(args)

    assert result == script.CommandResult(0, "raw stdout", "raw stderr")
    assert captured == [(args, {
        "shell": False,
        "capture_output": True,
        "text": True,
        "check": False,
    })]
    assert capsys.readouterr().out == ""


def test_missing_cli_raises_proven_process_not_started_without_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    script = _script()
    monkeypatch.setattr(
        script.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("secret path")),
    )

    with pytest.raises(script.AzureCliProcessNotStarted):
        script.SubprocessAzureCliRunner().run(["az", "version"])

    assert capsys.readouterr().out == ""
