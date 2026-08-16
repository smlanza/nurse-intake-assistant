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


def _hosted_verifier_args() -> list[str]:
    return [
        "--hosted-verifier-project-endpoint",
        "https://fictional.invalid/api/projects/example",
        "--hosted-verifier-stable-agent-endpoint",
        "https://fictional.invalid/api/projects/example/agents/fictional-agent/endpoint/protocols/openai",
        "--hosted-verifier-agent-name",
        "fictional-agent",
        "--hosted-verifier-agent-version",
        "fictional-version",
        "--hosted-verifier-model-deployment-name",
        "fictional-model",
    ]


def _hosted_verifier_values() -> dict[str, str]:
    return {
        "hosted_verifier_project_endpoint": (
            "https://fictional.invalid/api/projects/example"
        ),
        "hosted_verifier_stable_agent_endpoint": (
            "https://fictional.invalid/api/projects/example/agents/fictional-agent/endpoint/protocols/openai"
        ),
        "hosted_verifier_agent_name": "fictional-agent",
        "hosted_verifier_agent_version": "fictional-version",
        "hosted_verifier_model_deployment_name": "fictional-model",
    }


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
    assert None not in payload.values()
    assert all(
        type(value) is bool
        for key, value in payload.items()
        if key not in {"category", "mode", "operation", "transport"}
    )


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


def test_retired_metadata_mode_is_explicit_and_mutually_exclusive() -> None:
    script = _script()

    with pytest.raises(SystemExit):
        script._parse_args(
            [
                "--live-tunnel",
                "--live-metadata-verification",
                "--config",
                "fictional.env",
                "--json",
            ]
        )
    minimal = script._parse_args(["--live-metadata-verification", "--json"])
    compatible = script._parse_args(
        [
            "--live-metadata-verification",
            "--config",
            "fictional.env",
            "--json",
            *_hosted_verifier_args(),
        ]
    )
    assert minimal.live_metadata_verification is True
    assert minimal.live_tunnel is False
    assert compatible.live_metadata_verification is True
    assert compatible.live_tunnel is False


def test_retired_metadata_mode_main_rejects_before_run_live(
    monkeypatch,
    capsys,
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "run_live",
        lambda *_a, **_k: pytest.fail("retired mode must stop before run_live"),
    )
    exit_code = script.main(
        [
            "--live-metadata-verification",
            "--config",
            "fictional.env",
            "--json",
            *_hosted_verifier_args(),
        ],
        input_stream=io.StringIO("y\ny\ny\n"),
        output_stream=io.StringIO(),
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 2
    assert captured.err == ""
    assert payload["category"] == "ssh_hosted_identity_execution_unsupported"
    assert payload["mode"] == "live-metadata-verification"
    assert payload["ok"] is False


def test_retired_metadata_mode_run_live_rejects_before_every_live_boundary(
    monkeypatch,
) -> None:
    script = _script()
    for name in (
        "load_daily_azure_config",
        "load_matching_daily_azure_readiness_receipt",
        "_verify_hosted_verifier_configuration",
        "_create_configuration_runner",
        "_create_service",
        "_prompt",
    ):
        monkeypatch.setattr(
            script,
            name,
            lambda *_a, _name=name, **_k: pytest.fail(
                f"retired mode reached {_name}"
            ),
        )
    monkeypatch.setattr(
        script,
        "HostedVerifierRuntimeConfiguration",
        SimpleNamespace(
            from_mapping=lambda *_a, **_k: pytest.fail(
                "retired mode constructed runtime configuration"
            )
        ),
    )
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
    )

    result = script.run_live(
        args,
        input_stream=io.StringIO("y\n"),
        output_stream=io.StringIO(),
    )

    assert result.category == "ssh_hosted_identity_execution_unsupported"
    assert result.mode == "live-metadata-verification"
    for field in (
        "azure_call_made",
        "tunnel_process_started",
        "ssh_command_attempted",
        "interpreter_probe_attempted",
        "module_probe_attempted",
        "remote_check_attempted",
        "metadata_verification_attempted",
        "managed_identity_attempted",
        "agent_invocation_attempted",
        "azure_mutation_made",
    ):
        assert getattr(result, field) is False


def test_retired_metadata_mode_is_deterministic_and_sanitized(capsys) -> None:
    script = _script()
    argv = ["--live-metadata-verification", "--json"]

    assert script.main(argv) == 2
    first = capsys.readouterr()
    assert script.main(argv) == 2
    second = capsys.readouterr()

    assert first == second
    assert first.err == ""
    assert first.out.endswith("\n")
    assert first.out.count("\n") == 1
    payload = json.loads(first.out)
    assert payload["category"] == "ssh_hosted_identity_execution_unsupported"
    assert payload["mode"] == "live-metadata-verification"
    assert payload["ok"] is False
    assert "metadata_verifier_category" not in payload
    for private_text in (
        *_hosted_verifier_values().values(),
        "WEBSITE_INSTANCE_ID",
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
    ):
        assert private_text not in first.out


def test_retired_metadata_cli_requires_no_configuration_projection() -> None:
    script = _script()
    args = script._parse_args(["--live-metadata-verification", "--json"])

    assert args.config is None
    assert all(
        getattr(args, attribute) is None
        for attribute in script.HOSTED_SETTING_OPTIONS.values()
    )


def test_metadata_preflight_reuses_exact_configuration_verifier_contract(
    monkeypatch,
) -> None:
    script = _script()
    runner = object()
    captured: list[tuple[object, ...]] = []
    expected = script.WebAppConfigurationVerificationResult.live_success(
        hosted_verifier_configuration_verified=True
    )
    monkeypatch.setattr(script, "_create_configuration_runner", lambda: runner)

    def verify(*args, **kwargs):
        captured.append((*args, kwargs))
        return expected

    monkeypatch.setattr(script, "verify_web_app_configuration", verify)
    args = SimpleNamespace(**_hosted_verifier_values())

    result = script._verify_hosted_verifier_configuration(
        SimpleNamespace(enable_hosted_foundry_verifier=True),
        SimpleNamespace(resource_group="contract-rg", web_app_name="contract-app"),
        args,
    )

    assert result == expected
    assert len(captured) == 1
    resource_group, web_app_name, settings, kwargs = captured[0]
    assert resource_group == "contract-rg"
    assert web_app_name == "contract-app"
    assert settings == {
        setting_name: getattr(args, attribute)
        for setting_name, attribute in script.HOSTED_SETTING_OPTIONS.items()
    }
    assert set(settings) == set(script.HOSTED_SETTING_OPTIONS)
    assert kwargs == {
        "verify_hosted_foundry_verifier": True,
        "runner": runner,
    }


def test_disabled_metadata_preflight_stops_before_runner_or_verifier(
    monkeypatch,
) -> None:
    script = _script()
    monkeypatch.setattr(
        script,
        "_create_configuration_runner",
        lambda: pytest.fail("disabled preflight must not construct runner"),
    )
    monkeypatch.setattr(
        script,
        "verify_web_app_configuration",
        lambda *_a, **_k: pytest.fail("disabled preflight must not read Azure"),
    )

    result = script._verify_hosted_verifier_configuration(
        SimpleNamespace(enable_hosted_foundry_verifier=False),
        SimpleNamespace(resource_group="contract-rg", web_app_name="contract-app"),
        SimpleNamespace(**_hosted_verifier_values()),
    )

    assert result.category == "hosted_verifier_configuration_invalid"
    assert result.azure_request_attempted is False


def test_retired_mode_ignores_runtime_values_before_ssh_service(
    monkeypatch,
) -> None:
    script = _script()
    private_hostile_value = "private-runtime; $(touch /tmp/must-not-run)"
    config = SimpleNamespace(
        subscription_name="contract-subscription",
        enable_hosted_foundry_verifier=True,
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
    monkeypatch.setattr(
        script,
        "_verify_hosted_verifier_configuration",
        lambda *_a, **_k: (
            script.WebAppConfigurationVerificationResult.live_success(
                hosted_verifier_configuration_verified=True
            )
        ),
    )
    monkeypatch.setattr(
        script,
        "_create_service",
        lambda *_a: pytest.fail("invalid value must stop before SSH service"),
    )
    values = _hosted_verifier_values()
    values["hosted_verifier_agent_version"] = private_hostile_value
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
        config=Path("fictional-config"),
        readiness_receipt=Path("fictional-receipt"),
        **values,
    )

    prompts = io.StringIO()
    result = script.run_live(
        args,
        input_stream=io.StringIO(),
        output_stream=prompts,
    )

    assert result == script._retired_metadata_mode_result()
    assert result.category == "ssh_hosted_identity_execution_unsupported"
    for field in (
        "azure_call_made",
        "tunnel_process_started",
        "ssh_command_attempted",
        "interpreter_probe_attempted",
        "module_probe_attempted",
        "remote_check_attempted",
        "metadata_verification_attempted",
        "managed_identity_attempted",
        "agent_invocation_attempted",
        "azure_mutation_made",
    ):
        assert getattr(result, field) is False
    serialized_result = json.dumps(result.to_json_dict())
    assert prompts.getvalue() == ""
    assert private_hostile_value not in serialized_result


def test_retired_metadata_mode_never_reaches_approval_or_service(
    monkeypatch,
) -> None:
    script = _script()
    config = SimpleNamespace(
        subscription_name="contract-subscription",
        enable_hosted_foundry_verifier=True,
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
    proof = script.WebAppConfigurationVerificationResult.live_success(
        hosted_verifier_configuration_verified=True
    )
    monkeypatch.setattr(
        script,
        "_verify_hosted_verifier_configuration",
        lambda *_a, **_k: proof,
    )
    captured: list[object] = []

    class Service:
        def run_live_tunnel(self, request, *, approvals):
            captured.append(request)
            assert approvals.approve_tunnel() is True
            assert approvals.approve_probes() is True
            assert approvals.approve_metadata_verification() is True
            return script.HostedFoundryAgentSshTransportResult.build(
                ok=True,
                category="success",
                mode="live-metadata-verification",
                metadata_verification_attempted=True,
                managed_identity_attempted=True,
                metadata_verification_valid=True,
                tunnel_process_reaped=True,
                private_known_hosts_removed=True,
            )

    monkeypatch.setattr(
        script,
        "_create_service",
        lambda received, runtime: Service()
        if received == proof
        and type(runtime) is script.HostedVerifierRuntimeConfiguration
        else pytest.fail("metadata service requires the exact proof"),
    )
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
        config=Path("fictional-config"),
        readiness_receipt=Path("fictional-receipt"),
        **_hosted_verifier_values(),
    )
    prompts = io.StringIO()

    result = script.run_live(
        args,
        input_stream=io.StringIO("y\ny\ny\n"),
        output_stream=prompts,
    )

    assert result.ok is False
    assert result.category == "ssh_hosted_identity_execution_unsupported"
    assert captured == []
    summary = prompts.getvalue()
    assert summary == ""
    serialized_result = json.dumps(result.to_json_dict())
    for private_value in _hosted_verifier_values().values():
        assert private_value not in summary
        assert private_value not in serialized_result


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
