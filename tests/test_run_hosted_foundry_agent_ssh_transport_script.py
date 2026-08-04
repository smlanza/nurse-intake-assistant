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


def test_metadata_mode_is_explicit_mutually_exclusive_and_requires_config() -> None:
    script = _script()

    with pytest.raises(SystemExit):
        script._parse_args(["--live-metadata-verification", "--json"])
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
    args = script._parse_args(
        [
            "--live-metadata-verification",
            "--config",
            "fictional.env",
            "--json",
            *_hosted_verifier_args(),
        ]
    )
    assert args.live_metadata_verification is True
    assert args.live_tunnel is False


@pytest.mark.parametrize("receipt_state", ["missing", "stale", "mismatched"])
def test_metadata_mode_invalid_receipt_stops_before_service_construction(
    monkeypatch, receipt_state: str
) -> None:
    script = _script()
    config = SimpleNamespace(
        subscription_name="contract-subscription",
        enable_hosted_foundry_verifier=True,
    )
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        script,
        "_create_service",
        lambda: pytest.fail(f"{receipt_state} receipt must stop before service"),
    )
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
        config=Path("fictional-config"),
        readiness_receipt=Path("fictional-receipt"),
    )

    result = script.run_live(
        args,
        input_stream=io.StringIO("y\ny\ny\n"),
        output_stream=io.StringIO(),
    )

    assert result.category == "configuration_invalid"
    assert result.mode == "live-metadata-verification"
    assert result.tunnel_process_started is False


def test_metadata_mode_invalid_hosted_configuration_stops_before_service(
    monkeypatch,
) -> None:
    script = _script()
    config = SimpleNamespace(subscription_name="contract-subscription")
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
        lambda *_a, **_k: script.WebAppConfigurationVerificationResult.failure(
            "hosted_verifier_configuration_invalid",
            local_contract_validated=True,
            azure_request_attempted=True,
        ),
    )
    monkeypatch.setattr(
        script,
        "_create_service",
        lambda: pytest.fail("invalid hosted configuration must stop first"),
    )
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
        config=Path("fictional-config"),
        readiness_receipt=Path("fictional-receipt"),
        **_hosted_verifier_values(),
    )

    result = script.run_live(
        args,
        input_stream=io.StringIO("y\ny\ny\n"),
        output_stream=io.StringIO(),
    )

    assert result.category == "hosted_verifier_configuration_invalid"
    assert result.azure_call_made is True
    assert result.tunnel_process_started is False
    assert result.ssh_command_attempted is False
    assert result.managed_identity_attempted is False


def test_metadata_cli_requires_exact_hosted_verifier_projection() -> None:
    script = _script()
    base = [
        "--live-metadata-verification",
        "--config",
        "fictional.env",
        "--json",
    ]

    with pytest.raises(SystemExit):
        script._parse_args(base)

    args = script._parse_args(
        [
            *base,
            *_hosted_verifier_args(),
        ]
    )

    assert args.hosted_verifier_agent_version == "fictional-version"


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


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("hosted_verifier_project_endpoint", "not-an-endpoint"),
        ("hosted_verifier_agent_name", "different-agent"),
        ("hosted_verifier_agent_version", " "),
        ("hosted_verifier_agent_version", "bad\x00version"),
        ("hosted_verifier_agent_version", "bad\rversion"),
        ("hosted_verifier_agent_version", "bad\nversion"),
        ("hosted_verifier_model_deployment_name", "x" * 257),
    ],
)
def test_invalid_runtime_value_stops_before_ssh_service(
    monkeypatch,
    attribute: str,
    value: str,
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
    values[attribute] = value
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
        config=Path("fictional-config"),
        readiness_receipt=Path("fictional-receipt"),
        **values,
    )

    result = script.run_live(
        args,
        input_stream=io.StringIO(),
        output_stream=io.StringIO(),
    )

    assert result.category == "hosted_verifier_configuration_invalid"
    assert result.azure_call_made is True
    assert result.tunnel_process_started is False
    assert result.ssh_command_attempted is False


def test_metadata_mode_loads_matching_receipt_and_uses_distinct_approval(
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

    assert result.ok is True
    assert len(captured) == 1
    assert captured[0].mode == "live-metadata-verification"
    summary = prompts.getvalue()
    for expected in (
        "Remote execution count: one",
        "Mode: hosted metadata verification",
        "System-assigned managed identity: required",
        "Foundry metadata reads: permitted",
        "Agent invocation: prohibited",
        "Azure mutation: prohibited",
        "Retry permitted: no",
    ):
        assert expected in summary
    serialized_result = json.dumps(result.to_json_dict())
    for private_value in _hosted_verifier_values().values():
        assert private_value not in summary
        assert private_value not in serialized_result


def test_successful_preflight_constructs_exact_typed_runtime_configuration(
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
    proof = script.WebAppConfigurationVerificationResult.live_success(
        hosted_verifier_configuration_verified=True
    )
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_a, **_k: receipt,
    )
    events: list[str] = []

    def verify(*_args, **_kwargs):
        events.append("proof")
        return proof

    monkeypatch.setattr(script, "_verify_hosted_verifier_configuration", verify)

    class Service:
        def run_live_tunnel(self, request, *, approvals):
            assert request.mode == "live-metadata-verification"
            return script.HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode=request.mode,
            )

    def create_service(received_proof, runtime_configuration):
        assert events == ["proof"]
        assert received_proof == proof
        assert (
            type(runtime_configuration)
            is script.HostedVerifierRuntimeConfiguration
        )
        assert tuple(
            name
            for name, _value in runtime_configuration._assignment_pairs()
        ) == tuple(script.HOSTED_SETTING_OPTIONS)
        events.append("service")
        return Service()

    monkeypatch.setattr(script, "_create_service", create_service)
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
        config=Path("fictional-config"),
        readiness_receipt=Path("fictional-receipt"),
        **_hosted_verifier_values(),
    )

    result = script.run_live(
        args,
        input_stream=io.StringIO(),
        output_stream=io.StringIO(),
    )

    assert result.category == "approval_denied"
    assert events == ["proof", "service"]


def test_changed_readiness_evidence_invalidates_current_prompt_approval(
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
    receipt_results = iter((receipt, receipt, None))
    monkeypatch.setattr(script, "load_daily_azure_config", lambda *_a, **_k: config)
    monkeypatch.setattr(
        script,
        "load_matching_daily_azure_readiness_receipt",
        lambda *_a, **_k: next(receipt_results),
    )
    proof = script.WebAppConfigurationVerificationResult.live_success(
        hosted_verifier_configuration_verified=True
    )
    monkeypatch.setattr(
        script,
        "_verify_hosted_verifier_configuration",
        lambda *_a, **_k: proof,
    )

    class Service:
        def run_live_tunnel(self, request, *, approvals):
            assert request.mode == "live-metadata-verification"
            assert approvals.approve_tunnel() is False
            return script.HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode=request.mode,
            )

    monkeypatch.setattr(
        script,
        "_create_service",
        lambda _proof, _runtime: Service(),
    )
    args = SimpleNamespace(
        live_tunnel=False,
        live_metadata_verification=True,
        config=Path("fictional-config"),
        readiness_receipt=Path("fictional-receipt"),
        **_hosted_verifier_values(),
    )

    result = script.run_live(
        args,
        input_stream=io.StringIO("y\n"),
        output_stream=io.StringIO(),
    )

    assert result.category == "approval_denied"
    assert result.tunnel_process_started is False


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
