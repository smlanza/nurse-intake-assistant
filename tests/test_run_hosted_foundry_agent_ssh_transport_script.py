import importlib
import inspect
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


def _script():
    return importlib.import_module("scripts.run_hosted_foundry_agent_ssh_transport")


def test_check_cli_emits_one_sanitized_newline_terminated_json(capsys) -> None:
    script = _script()

    exit_code = script.main(["--check", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["category"] == "check_passed"
    assert payload["mode"] == "check"
    assert payload["transport"] == "app_service_tcp_tunnel"
    assert payload["tunnel_process_started"] is False
    assert payload["ssh_command_attempted"] is False
    assert payload["azure_call_made"] is False


def test_repeated_check_cli_output_is_byte_identical(capsys) -> None:
    script = _script()

    assert script.main(["--check", "--json"]) == 0
    first = capsys.readouterr().out
    assert script.main(["--check", "--json"]) == 0
    second = capsys.readouterr().out

    assert first == second


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--check"],
        ["--json"],
        ["--live-tunnel", "--json"],
        ["--check", "--json", "--port", "1234"],
        ["--check", "--json", "--command", "uname"],
        ["--check", "--json", "--module", "arbitrary"],
    ],
)
def test_cli_rejects_every_noncheck_or_override_shape(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        _script().main(argv)


def test_check_wrapper_source_has_no_live_dependency_surface() -> None:
    source = inspect.getsource(_script())

    for forbidden in (
        "import subprocess",
        "import socket",
        "Popen",
        "subprocess.",
        "--port",
        "--timeout",
        "--command",
        "--module",
        "AppSettings",
    ):
        assert forbidden not in source


def test_check_never_loads_live_configuration_or_service(monkeypatch) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "load_daily_azure_config",
        lambda *_args, **_kwargs: pytest.fail("check must not load config"),
    )
    monkeypatch.setattr(
        script,
        "run_live",
        lambda *_args, **_kwargs: pytest.fail("check must not enter live mode"),
    )

    assert script.main(["--check", "--json"]) == 0


def test_live_requires_existing_validated_configuration() -> None:
    with pytest.raises(SystemExit):
        _script().main(["--live-tunnel", "--json"])


def test_live_loads_matching_receipt_and_delegates_fixed_request(monkeypatch) -> None:
    script = _script()
    config = SimpleNamespace(
        subscription_name="contract-subscription",
        resource_group="contract-rg",
        web_app_name="contract-web-app",
    )
    receipt = SimpleNamespace(
        resource_group="contract-rg",
        web_app_name="contract-web-app",
    )
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_a, **_k: receipt,
    )
    captured: list[object] = []

    class Service:
        def run_live_tunnel(self, request, *, approvals):
            captured.append(request)
            assert approvals.approve_tunnel() is True
            assert approvals.approve_probes() is True
            assert approvals.approve_remote_check() is True
            return script.HostedFoundryAgentSshTransportResult.build(
                ok=True,
                category="success",
                mode="live-tunnel",
                tunnel_process_reaped=True,
                private_known_hosts_removed=True,
            )

    monkeypatch.setattr(script, "_create_service", lambda: Service())
    args = SimpleNamespace(
        config=Path("ignored-config"),
        readiness_receipt=Path("ignored-receipt"),
    )
    prompts = io.StringIO()

    result = script.run_live(
        args,
        input_stream=io.StringIO("y\ny\ny\n"),
        output_stream=prompts,
    )

    assert result.ok is True
    assert len(captured) == 1
    assert captured[0].mode == "live-tunnel"
    assert "Managed identity, metadata, and Agent activity: prohibited" in (
        prompts.getvalue()
    )


def test_direct_script_execution_matches_imported_cli_contract() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/run_hosted_foundry_agent_ssh_transport.py",
            "--check",
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout.endswith("\n")
    assert completed.stdout.count("\n") == 1
    assert json.loads(completed.stdout)["category"] == "check_passed"
