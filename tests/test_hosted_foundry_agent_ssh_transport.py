from dataclasses import replace
import io
import json
import os
import shlex
import subprocess
import sys
from types import SimpleNamespace

import pytest

from src.app.services import hosted_foundry_agent_ssh_transport as transport
from src.app.services.web_app_hosting_contract import (
    HOSTED_VERIFIER_SETTING_NAMES,
)


VALID_HELP = transport.AzureCliHelpSurface(
    create_remote_connection=(
        "webapp create-remote-connection --subscription --resource-group --name "
        "--port --timeout --only-show-errors Ctrl + C to close"
    ),
    preview_ssh="webapp ssh preview",
)

FICTIONAL_RUNTIME_SETTINGS = {
    "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": (
        "https://fictional.invalid/api/projects/example"
    ),
    "AZURE_AI_FOUNDRY_AGENT_ENDPOINT": (
        "https://fictional.invalid/api/projects/example/agents/"
        "fictional-agent/endpoint/protocols/openai"
    ),
    "AZURE_AI_FOUNDRY_AGENT_NAME": "fictional-agent",
    "AZURE_AI_FOUNDRY_AGENT_VERSION": "fictional-version",
    "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": "fictional-model",
}


_DEFAULT_CONFIGURATION_PROOF = object()
_DEFAULT_RUNTIME_CONFIGURATION = object()


def _service(
    help_surface: object = VALID_HELP,
    configuration_proof: object = _DEFAULT_CONFIGURATION_PROOF,
    runtime_configuration: object = _DEFAULT_RUNTIME_CONFIGURATION,
):
    if configuration_proof is _DEFAULT_CONFIGURATION_PROOF:
        configuration_proof = (
            transport.WebAppConfigurationVerificationResult.live_success(
                hosted_verifier_configuration_verified=True
            )
        )
    if runtime_configuration is _DEFAULT_RUNTIME_CONFIGURATION:
        runtime_configuration = _runtime_configuration()
    return transport.HostedFoundryAgentSshTransport(
        help_reader=lambda: help_surface,
        hosted_verifier_configuration_proof=configuration_proof,
        hosted_verifier_runtime_configuration=runtime_configuration,
    )


def _request(mode: str = "live-tunnel"):
    return transport.HostedFoundryAgentSshTransportRequest(
        mode=mode,
        subscription="contract-subscription",
        resource_group="contract-rg",
        web_app_name="contract-web-app",
    )


def _approvals(
    *,
    tunnel: bool = True,
    probes: bool = True,
    remote: bool = True,
):
    return transport.HostedFoundryAgentSshTransportApprovals(
        approve_tunnel=lambda: tunnel,
        approve_probes=lambda: probes,
        approve_remote_check=lambda: remote,
    )


class FakeProcess:
    pid = 1234
    stdout = None
    stderr = None

    def __init__(
        self,
        *,
        poll_result: int | None = None,
        wait_outcomes: list[object] | None = None,
        raw_output: str = "",
    ) -> None:
        self.poll_result = poll_result
        self.wait_outcomes = list(wait_outcomes or [0])
        self.raw_output = raw_output
        self.wait_calls: list[float] = []
        self.reaped = False

    def poll(self):
        return self.poll_result

    def wait(self, timeout: float | None = None):
        self.wait_calls.append(timeout)
        outcome = self.wait_outcomes.pop(0) if self.wait_outcomes else 0
        if isinstance(outcome, BaseException):
            raise outcome
        self.reaped = True
        self.poll_result = int(outcome)
        return self.poll_result


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeSshRunner:
    def __init__(self, results: list[object] | None = None) -> None:
        self.results = list(results or _successful_remote_results())
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def run(self, args: tuple[str, ...], timeout_seconds: float):
        self.calls.append((args, timeout_seconds))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class FakeOutputObserver:
    def __init__(self, *, ready: bool = True, failed: bool = False) -> None:
        self.is_ready = ready
        self.is_failed = failed
        self.closed = False

    def ready(self) -> bool:
        return self.is_ready

    def failed(self) -> bool:
        return self.is_failed

    def close(self) -> None:
        self.closed = True


class ChunkStream:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = list(chunks)
        self.closed = False

    def readline(self) -> str:
        return self.chunks.pop(0) if self.chunks else ""

    def close(self) -> None:
        self.closed = True


def _proof_payload() -> dict[str, object]:
    return {
        "ok": True,
        "category": "check_passed",
        "operation": "prove_hosted_foundry_agent",
        "mode": "check",
        "execution_boundary": "app_service_ssh",
        "command_execution_attempted": False,
        "local_contract_validated": True,
        "hosted_environment_present": False,
        "managed_identity_attempted": False,
        "metadata_verification_attempted": False,
        "metadata_verified": False,
        "agent_invocation_attempted": False,
        "agent_output_valid": False,
        "fictional_data_only": True,
        "route_invoked": False,
        "persistence_attempted": False,
        "notification_attempted": False,
        "deterministic_rules_executed": False,
        "azure_call_made": False,
        "azure_mutation_made": False,
    }


def _metadata_payload() -> dict[str, object]:
    return {
        "ok": True,
        "category": "success",
        "operation": "verify_hosted_foundry_agent",
        "mode": "live",
        "local_contract_validated": True,
        "hosted_environment_present": True,
        "managed_identity_attempted": True,
        "managed_identity_authenticated": True,
        "project_access_verified": True,
        "agent_present": True,
        "configured_version_present": True,
        "agent_contract_verified": True,
        "agent_invocation_attempted": False,
        "azure_mutation_made": False,
        "recommended_next_step": (
            "Run the separate fictional-data hosted agent invocation."
        ),
    }


def _metadata_failure_payload(
    category: str = "not_running_in_hosted_environment",
    **changes: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "ok": False,
        "category": category,
        "operation": "verify_hosted_foundry_agent",
        "mode": "live",
        "local_contract_validated": True,
        "hosted_environment_present": False,
        "managed_identity_attempted": False,
        "managed_identity_authenticated": False,
        "project_access_verified": False,
        "agent_present": False,
        "configured_version_present": False,
        "agent_contract_verified": False,
        "agent_invocation_attempted": False,
        "azure_mutation_made": False,
        "recommended_next_step": (
            "Review the sanitized category before retrying verification."
        ),
    }
    payload.update(changes)
    return payload


def _metadata_approvals(
    *,
    tunnel: bool = True,
    probes: bool = True,
    metadata: bool = True,
):
    return SimpleNamespace(
        approve_tunnel=lambda: tunnel,
        approve_probes=lambda: probes,
        approve_remote_check=lambda: pytest.fail(
            "metadata mode must not request non-invoking check approval"
        ),
        approve_metadata_verification=lambda: metadata,
    )


def _line(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n"


def _successful_remote_results() -> list[transport.RemoteCommandResult]:
    return [
        transport.RemoteCommandResult(
            0,
            _line({"app_path_valid": True, "interpreter_valid": True}),
            "",
        ),
        transport.RemoteCommandResult(
            0,
            _line({"packaged_module_valid": True}),
            "",
        ),
        transport.RemoteCommandResult(0, _line(_proof_payload()), ""),
    ]


def _successful_metadata_results() -> list[transport.RemoteCommandResult]:
    return [
        *_successful_remote_results()[:2],
        transport.RemoteCommandResult(0, _line(_metadata_payload()), ""),
    ]


def _dependencies(
    *,
    process: FakeProcess | None = None,
    process_factory=None,
    port_available=True,
    tunnel_ready=True,
    ssh_runner: FakeSshRunner | None = None,
    clock: FakeClock | None = None,
    removed: list[str] | None = None,
    signals: list[str] | None = None,
    output_observer: FakeOutputObserver | None = None,
):
    process = process or FakeProcess()
    starts: list[tuple[str, ...]] = []
    removed = removed if removed is not None else []
    signals = signals if signals is not None else []
    clock = clock or FakeClock()
    output_observer = output_observer or FakeOutputObserver()

    def start(args: tuple[str, ...]):
        starts.append(args)
        if process_factory is not None:
            return process_factory(args)
        return process

    deps = transport.HostedFoundryAgentSshTransportDependencies(
        process_factory=start,
        port_available=(
            port_available
            if callable(port_available)
            else lambda _host, _port: port_available
        ),
        tunnel_ready=(
            tunnel_ready
            if callable(tunnel_ready)
            else lambda _host, _port: tunnel_ready
        ),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        ssh_runner=ssh_runner or FakeSshRunner(),
        observe_tunnel_output=lambda _process: output_observer,
        create_known_hosts=lambda: "/private/current-run-known-hosts",
        remove_known_hosts=lambda path: removed.append(path),
        send_interrupt=lambda _child: signals.append("interrupt"),
        terminate=lambda _child: signals.append("terminate"),
        kill=lambda _child: signals.append("kill"),
    )
    return deps, starts, removed, signals


def test_check_is_deterministic_and_starts_no_live_dependency(monkeypatch) -> None:
    monkeypatch.setattr(
        transport,
        "_default_dependencies",
        lambda: pytest.fail("check must not construct live dependencies"),
    )
    request = transport.build_hosted_foundry_agent_ssh_transport_check_request()

    first = _service().check(request)
    second = _service().check(request)

    assert first == second
    assert first.ok is True
    assert first.category == "check_passed"
    assert first.mode == "check"
    assert first.transport == "app_service_tcp_tunnel"
    assert first.cli_help_contract_valid is True
    assert first.tunnel_command_valid is True
    assert first.remote_command_contract_valid is True
    for field in (
        "tunnel_process_started",
        "tunnel_ready",
        "ssh_command_attempted",
        "interpreter_probe_attempted",
        "module_probe_attempted",
        "remote_check_attempted",
        "managed_identity_attempted",
        "metadata_verification_attempted",
        "agent_invocation_attempted",
        "azure_call_made",
        "azure_mutation_made",
    ):
        assert getattr(first, field) is False


@pytest.mark.parametrize("missing", [
    "--subscription",
    "--resource-group",
    "--name",
    "--port",
    "--timeout",
    "--only-show-errors",
    "Ctrl + C to close",
])
def test_missing_required_cli_option_fails_closed(missing: str) -> None:
    help_surface = replace(
        VALID_HELP,
        create_remote_connection=VALID_HELP.create_remote_connection.replace(
            missing, ""
        ),
    )

    result = _service(help_surface).check(
        transport.build_hosted_foundry_agent_ssh_transport_check_request()
    )

    assert result.ok is False
    assert result.category == "cli_unsupported"
    assert result.tunnel_process_started is False


@pytest.mark.parametrize("surface", [None, object(), {"--port": True}])
def test_malformed_cli_help_fails_closed(surface: object) -> None:
    result = _service(surface).check(
        transport.build_hosted_foundry_agent_ssh_transport_check_request()
    )

    assert result.category == "cli_unsupported"


def test_only_the_mode_selected_fixed_remote_commands_are_representable() -> None:
    commands = _service().permitted_remote_commands()

    assert commands == (
        transport.INTERPRETER_PROBE_COMMAND,
        transport.MODULE_PROBE_COMMAND,
        transport.REMOTE_CHECK_COMMAND,
        transport.REMOTE_METADATA_VERIFICATION_COMMAND,
    )
    assert all("APP_PATH" in command for command in commands)
    assert all("/home/site/wwwroot" not in command for command in commands)
    assert all("--live" not in command for command in commands[:-1])
    assert commands[-2].endswith("--check --json")
    assert commands[-1].endswith("--live --json")
    request_fields = set(
        transport.HostedFoundryAgentSshTransportRequest.__dataclass_fields__
    )
    assert request_fields == {
        "mode",
        "subscription",
        "resource_group",
        "web_app_name",
    }


def test_tunnel_argument_list_is_exact_and_never_selects_preview_ssh() -> None:
    command = transport.build_tunnel_command(_request())

    assert command == (
        "az",
        "webapp",
        "create-remote-connection",
        "--subscription",
        "contract-subscription",
        "--resource-group",
        "contract-rg",
        "--name",
        "contract-web-app",
        "--port",
        str(transport.LOCAL_PORT),
        "--timeout",
        str(transport.TUNNEL_TIMEOUT_SECONDS),
        "--only-show-errors",
    )
    assert "ssh" not in command
    assert "--slot" not in command
    assert "--instance" not in command
    assert "--debug" not in command
    assert "--verbose" not in command


@pytest.mark.parametrize("command", ["uname -a", "python -m arbitrary", "--live"])
def test_arbitrary_remote_command_is_rejected(command: str) -> None:
    with pytest.raises(ValueError):
        transport.build_ssh_command(command, "/private/current-run-known-hosts")


def test_ssh_contract_uses_private_known_hosts_and_loopback_only() -> None:
    args = transport.build_ssh_command(
        transport.INTERPRETER_PROBE_COMMAND,
        "/private/current-run-known-hosts",
    )

    assert args[0] == "ssh"
    assert args[-2] == "root@127.0.0.1"
    assert f"UserKnownHostsFile=/private/current-run-known-hosts" in args
    assert "GlobalKnownHostsFile=/dev/null" in args
    assert "StrictHostKeyChecking=accept-new" in args
    assert not any(".ssh/known_hosts" in value for value in args)


def test_occupied_port_blocks_process_construction() -> None:
    deps, starts, _, _ = _dependencies(port_available=False)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "port_unavailable"
    assert starts == []
    assert result.tunnel_process_started is False


def test_tunnel_approval_denial_blocks_every_live_dependency() -> None:
    deps, starts, removed, _ = _dependencies()

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(tunnel=False), dependencies=deps
    )

    assert result.category == "approval_denied"
    assert starts == []
    assert removed == []


def test_success_uses_one_process_three_commands_and_reaps() -> None:
    process = FakeProcess(raw_output="secret tunnel output")
    runner = FakeSshRunner()
    deps, starts, removed, signals = _dependencies(
        process=process,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.ok is True
    assert result.category == "success"
    assert len(starts) == 1
    assert [call[0][-1] for call in runner.calls] == list(
        transport.PERMITTED_REMOTE_COMMANDS[:3]
    )
    assert result.metadata_verification_attempted is False
    assert result.metadata_verification_valid is False
    assert result.managed_identity_attempted is False
    assert result.agent_invocation_attempted is False
    assert signals == ["interrupt"]
    assert process.reaped is True
    assert result.tunnel_process_reaped is True
    assert result.private_known_hosts_removed is True
    assert len(removed) == 1
    assert "secret tunnel output" not in json.dumps(result.to_json_dict())


def test_metadata_mode_uses_one_tunnel_two_probes_and_one_metadata_command() -> None:
    process = FakeProcess()
    runner = FakeSshRunner(_successful_metadata_results())
    deps, starts, removed, signals = _dependencies(
        process=process,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(),
        dependencies=deps,
    )

    assert result.ok is True
    assert result.category == "success"
    assert result.mode == "live-metadata-verification"
    assert len(starts) == 1
    commands = [call[0][-1] for call in runner.calls]
    assert commands[:2] == [
        transport.INTERPRETER_PROBE_COMMAND,
        transport.MODULE_PROBE_COMMAND,
    ]
    assert shlex.split(commands[2])[-5:] == [
        "python",
        "-m",
        transport.METADATA_VERIFICATION_MODULE,
        "--live",
        "--json",
    ]
    assert result.interpreter_valid is True
    assert result.packaged_module_valid is True
    assert result.remote_check_attempted is False
    assert result.remote_check_valid is False
    assert result.metadata_verification_attempted is True
    assert result.managed_identity_attempted is True
    assert result.metadata_verification_valid is True
    assert result.agent_invocation_attempted is False
    assert result.azure_mutation_made is False
    assert signals == ["interrupt"]
    assert result.tunnel_process_reaped is True
    assert result.private_known_hosts_removed is True
    assert len(removed) == 1


def test_metadata_mode_requires_configuration_proof_before_live_dependencies(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        transport,
        "_default_dependencies",
        lambda: pytest.fail("configuration proof must stop before dependencies"),
    )
    approvals = transport.HostedFoundryAgentSshTransportApprovals(
        approve_tunnel=lambda: pytest.fail("configuration proof must stop first"),
        approve_probes=lambda: pytest.fail("configuration proof must stop first"),
        approve_remote_check=lambda: pytest.fail("configuration proof must stop first"),
        approve_metadata_verification=lambda: pytest.fail(
            "configuration proof must stop first"
        ),
    )

    result = _service(configuration_proof=None).run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=approvals,
    )

    assert result.category == "hosted_verifier_configuration_invalid"
    for field in (
        "tunnel_process_started",
        "tunnel_ready",
        "ssh_command_attempted",
        "interpreter_probe_attempted",
        "module_probe_attempted",
        "metadata_verification_attempted",
        "managed_identity_attempted",
        "agent_invocation_attempted",
        "azure_mutation_made",
    ):
        assert getattr(result, field) is False


def test_metadata_mode_requires_runtime_configuration_before_live_dependencies(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        transport,
        "_default_dependencies",
        lambda: pytest.fail("runtime configuration must stop before dependencies"),
    )
    approvals = transport.HostedFoundryAgentSshTransportApprovals(
        approve_tunnel=lambda: pytest.fail("runtime configuration must stop first"),
        approve_probes=lambda: pytest.fail("runtime configuration must stop first"),
        approve_remote_check=lambda: pytest.fail("runtime configuration must stop first"),
        approve_metadata_verification=lambda: pytest.fail(
            "runtime configuration must stop first"
        ),
    )

    result = _service(runtime_configuration=None).run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=approvals,
    )

    assert result.category == "hosted_verifier_configuration_invalid"
    assert result.tunnel_process_started is False
    assert result.ssh_command_attempted is False
    assert result.metadata_verification_attempted is False
    assert result.managed_identity_attempted is False


def test_metadata_command_is_the_only_live_remote_command_permitted() -> None:
    command = transport.REMOTE_METADATA_VERIFICATION_COMMAND

    assert command == (
        'cd "$APP_PATH" && python -m '
        "src.app.operations.verify_hosted_foundry_agent --live --json"
    )
    assert "prove_hosted_foundry_agent" not in command
    assert "invoke_hosted_foundry_agent" not in command
    assert _service().permitted_remote_commands().count(command) == 1
    assert transport.build_ssh_command(
        command,
        "/private/current-run-known-hosts",
        hosted_verifier_runtime_configuration=_runtime_configuration(),
    )[-1] != command
    with pytest.raises(ValueError, match="configuration is invalid"):
        transport.build_ssh_command(
            command,
            "/private/current-run-known-hosts",
        )
    for unauthorized in (
        "python -m src.app.operations.prove_hosted_foundry_agent --live --json",
        "python -m src.app.operations.invoke_hosted_foundry_agent --live --json",
        command + " --prompt arbitrary",
        command + " --agent override",
        command + " --version override",
        command + " --endpoint override",
        command + " --credential override",
    ):
        with pytest.raises(ValueError):
            transport.build_ssh_command(
                unauthorized, "/private/current-run-known-hosts"
            )


def _runtime_configuration(settings=None):
    return transport.HostedVerifierRuntimeConfiguration.from_mapping(
        FICTIONAL_RUNTIME_SETTINGS if settings is None else settings
    )


def test_metadata_runtime_configuration_is_exact_typed_and_private() -> None:
    configuration = _runtime_configuration()

    assignments = configuration._assignment_pairs()

    assert type(configuration) is transport.HostedVerifierRuntimeConfiguration
    assert tuple(name for name, _value in assignments) == tuple(
        HOSTED_VERIFIER_SETTING_NAMES
    )
    assert len(assignments) == 5
    assert not any(
        value in repr(configuration)
        for value in FICTIONAL_RUNTIME_SETTINGS.values()
    )


def test_metadata_ssh_command_has_only_five_fixed_assignments_and_invocation() -> None:
    args = transport.build_ssh_command(
        transport.REMOTE_METADATA_VERIFICATION_COMMAND,
        "/private/current-run-known-hosts",
        hosted_verifier_runtime_configuration=_runtime_configuration(),
    )

    tokens = shlex.split(args[-1])
    assignments = tokens[4:9]

    assert tokens[:4] == ["cd", "$APP_PATH", "&&", "env"]
    assert tuple(item.split("=", 1)[0] for item in assignments) == tuple(
        HOSTED_VERIFIER_SETTING_NAMES
    )
    assert tokens[9:] == [
        "python",
        "-m",
        transport.METADATA_VERIFICATION_MODULE,
        "--live",
        "--json",
    ]
    assert tokens.count("&&") == 1
    assert tokens.count("python") == 1


def test_metadata_command_never_forwards_local_or_identity_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("UNRELATED_LOCAL_SETTING", "fictional-local-value")
    monkeypatch.setenv("WEBSITE_INSTANCE_ID", "fictional-instance")
    monkeypatch.setenv("IDENTITY_ENDPOINT", "https://identity.invalid")
    monkeypatch.setenv("IDENTITY_HEADER", "fictional-header")

    args = transport.build_ssh_command(
        transport.REMOTE_METADATA_VERIFICATION_COMMAND,
        "/private/current-run-known-hosts",
        hosted_verifier_runtime_configuration=_runtime_configuration(),
    )
    assignment_names = tuple(
        item.split("=", 1)[0] for item in shlex.split(args[-1])[4:9]
    )

    assert assignment_names == tuple(HOSTED_VERIFIER_SETTING_NAMES)
    for prohibited in (
        "UNRELATED_LOCAL_SETTING",
        "WEBSITE_INSTANCE_ID",
        "IDENTITY_ENDPOINT",
        "IDENTITY_HEADER",
    ):
        assert prohibited not in assignment_names


@pytest.mark.parametrize(
    "settings",
    [
        {},
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "EXTRA_SETTING": "fictional-extra",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": "",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_AGENT_VERSION": " ",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_AGENT_VERSION": "bad\x00version",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_AGENT_VERSION": "bad\rversion",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_AGENT_VERSION": "bad\nversion",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT": "not-an-endpoint",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_AGENT_NAME": "different-agent",
        },
        {
            **FICTIONAL_RUNTIME_SETTINGS,
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": "x" * 257,
        },
    ],
)
def test_invalid_metadata_runtime_configuration_fails_closed(settings) -> None:
    with pytest.raises(ValueError, match="configuration is invalid"):
        _runtime_configuration(settings)


@pytest.mark.parametrize(
    ("setting_name", "injection_shape"),
    [
        ("AZURE_AI_FOUNDRY_AGENT_VERSION", "fictional; touch /tmp/other"),
        ("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", "fictional && false"),
        ("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", "fictional $(false)"),
        ("AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME", "fictional ' quoted"),
    ],
)
def test_injection_shaped_value_cannot_change_fixed_metadata_command(
    setting_name: str,
    injection_shape: str,
) -> None:
    configuration = _runtime_configuration(
        {**FICTIONAL_RUNTIME_SETTINGS, setting_name: injection_shape}
    )

    args = transport.build_ssh_command(
        transport.REMOTE_METADATA_VERIFICATION_COMMAND,
        "/private/current-run-known-hosts",
        hosted_verifier_runtime_configuration=configuration,
    )
    tokens = shlex.split(args[-1])

    assert len(tokens[4:9]) == 5
    assert tokens.count("&&") == 1
    assert tokens.count("python") == 1
    assert tokens[9:] == [
        "python",
        "-m",
        transport.METADATA_VERIFICATION_MODULE,
        "--live",
        "--json",
    ]


def test_metadata_runtime_values_never_enter_serialized_transport_result() -> None:
    runner = FakeSshRunner(_successful_metadata_results())
    deps, _, _, _ = _dependencies(ssh_runner=runner)
    service = transport.HostedFoundryAgentSshTransport(
        help_reader=lambda: VALID_HELP,
        hosted_verifier_configuration_proof=(
            transport.WebAppConfigurationVerificationResult.live_success(
                hosted_verifier_configuration_verified=True
            )
        ),
        hosted_verifier_runtime_configuration=_runtime_configuration(),
    )

    result = service.run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(),
        dependencies=deps,
    )

    serialized = json.dumps(result.to_json_dict())
    assert result.ok is True
    assert not any(
        value in serialized for value in FICTIONAL_RUNTIME_SETTINGS.values()
    )


@pytest.mark.parametrize(
    ("tunnel", "probes", "metadata", "expected_calls", "expected_starts"),
    [
        (False, True, True, 0, 0),
        (True, False, True, 0, 1),
        (True, True, False, 2, 1),
    ],
    ids=["tunnel-denied", "probes-denied", "metadata-denied"],
)
def test_metadata_mode_preserves_each_default_no_approval_boundary(
    tunnel: bool,
    probes: bool,
    metadata: bool,
    expected_calls: int,
    expected_starts: int,
) -> None:
    runner = FakeSshRunner(_successful_metadata_results())
    deps, starts, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(
            tunnel=tunnel,
            probes=probes,
            metadata=metadata,
        ),
        dependencies=deps,
    )

    assert result.category == "approval_denied"
    assert len(starts) == expected_starts
    assert len(runner.calls) == expected_calls
    assert result.metadata_verification_attempted is False
    assert result.agent_invocation_attempted is False
    if expected_starts:
        assert result.tunnel_process_reaped is True


def test_metadata_mode_uses_authoritative_listener_readiness_without_marker() -> None:
    observer = FakeOutputObserver(ready=False)
    runner = FakeSshRunner(_successful_metadata_results())
    deps, starts, _, _ = _dependencies(
        tunnel_ready=True,
        output_observer=observer,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(probes=False),
        dependencies=deps,
    )

    assert result.category == "approval_denied"
    assert result.tunnel_ready is True
    assert len(starts) == 1
    assert runner.calls == []
    assert result.tunnel_process_reaped is True


def _metadata_result(payload: object, *, stderr: str = ""):
    stdout = payload if isinstance(payload, str) else _line(payload)
    return transport.RemoteCommandResult(0, stdout, stderr)


@pytest.mark.parametrize(
    ("category", "return_code", "progress"),
    [
        ("not_running_in_hosted_environment", 2, {}),
        (
            "managed_identity_unavailable",
            1,
            {"hosted_environment_present": True, "managed_identity_attempted": True},
        ),
        (
            "sdk_unavailable",
            2,
            {"hosted_environment_present": True, "managed_identity_attempted": True},
        ),
        (
            "project_access_failed",
            1,
            {"hosted_environment_present": True, "managed_identity_attempted": True},
        ),
        (
            "agent_contract_invalid",
            1,
            {
                "hosted_environment_present": True,
                "managed_identity_attempted": True,
                "managed_identity_authenticated": True,
                "project_access_verified": True,
                "agent_present": True,
                "configured_version_present": True,
            },
        ),
    ],
    ids=[
        "before-managed-identity",
        "managed-identity",
        "sdk-during-managed-identity",
        "foundry-metadata-access",
        "metadata-contract-validation",
    ],
)
def test_recognized_metadata_failure_preserves_only_allowlisted_category(
    category: str,
    return_code: int,
    progress: dict[str, bool],
) -> None:
    payload = _metadata_failure_payload(category)
    payload.update(progress)
    remote = transport.RemoteCommandResult(
        return_code,
        _line(payload),
        "",
    )
    runner = FakeSshRunner([*_successful_remote_results()[:2], remote])
    deps, starts, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(),
        dependencies=deps,
    )

    assert result.category == "metadata_verification_failed"
    assert result.metadata_verifier_category == category
    assert result.managed_identity_attempted is progress.get(
        "managed_identity_attempted", False
    )
    assert len(starts) == 1
    assert "metadata_verifier_category" in result.to_json_dict()


@pytest.mark.parametrize(
    "remote",
    [
        transport.RemoteCommandResult(
            2,
            _line(_metadata_failure_payload("unknown_remote_category")),
            "",
        ),
        transport.RemoteCommandResult(
            2,
            _line(_metadata_failure_payload(operation="wrong_operation")),
            "",
        ),
        transport.RemoteCommandResult(
            2,
            _line(_metadata_failure_payload(ok=0)),
            "",
        ),
        transport.RemoteCommandResult(
            2,
            _line(_metadata_failure_payload(managed_identity_attempted=True)),
            "",
        ),
        transport.RemoteCommandResult(
            2,
            _line({key: value for key, value in _metadata_failure_payload().items() if key != "mode"}),
            "",
        ),
        transport.RemoteCommandResult(
            2,
            _line(_metadata_failure_payload()) + _line(_metadata_failure_payload()),
            "",
        ),
        transport.RemoteCommandResult(
            2,
            "prefix" + _line(_metadata_failure_payload()),
            "",
        ),
        transport.RemoteCommandResult(
            2,
            _line(_metadata_failure_payload()),
            "private hosted environment detail",
        ),
        transport.RemoteCommandResult(2, "not-json\n", ""),
    ],
)
def test_non_authoritative_metadata_failure_remains_generic(remote) -> None:
    runner = FakeSshRunner([*_successful_remote_results()[:2], remote])
    deps, _, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(),
        dependencies=deps,
    )

    assert result.category == "metadata_verification_failed"
    assert "metadata_verifier_category" not in result.to_json_dict()
    assert "private hosted environment detail" not in json.dumps(
        result.to_json_dict()
    )


@pytest.mark.parametrize(
    "remote",
    [
        _metadata_result({}),
        _metadata_result({**_metadata_payload(), "ok": 1}),
        _metadata_result({**_metadata_payload(), "category": "check_passed"}),
        _metadata_result({**_metadata_payload(), "mode": "check"}),
        _metadata_result(
            {**_metadata_payload(), "operation": "prove_hosted_foundry_agent"}
        ),
        _metadata_result(
            {**_metadata_payload(), "managed_identity_attempted": False}
        ),
        _metadata_result(
            {**_metadata_payload(), "managed_identity_authenticated": False}
        ),
        _metadata_result({**_metadata_payload(), "project_access_verified": False}),
        _metadata_result({**_metadata_payload(), "agent_present": False}),
        _metadata_result(
            {**_metadata_payload(), "configured_version_present": False}
        ),
        _metadata_result(
            {**_metadata_payload(), "agent_contract_verified": False}
        ),
        _metadata_result(
            {**_metadata_payload(), "agent_invocation_attempted": True}
        ),
        _metadata_result({**_metadata_payload(), "azure_mutation_made": True}),
        _metadata_result({**_metadata_payload(), "unexpected": False}),
        _metadata_result("not-json\n"),
        _metadata_result(_line(_metadata_payload()) + _line(_metadata_payload())),
        _metadata_result("prefix" + _line(_metadata_payload())),
        _metadata_result(_line(_metadata_payload()) + "suffix\n"),
        _metadata_result(_metadata_payload(), stderr="private authentication text"),
    ],
)
def test_metadata_remote_result_is_an_exact_untrusted_boundary(remote) -> None:
    runner = FakeSshRunner([*_successful_remote_results()[:2], remote])
    deps, starts, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(),
        dependencies=deps,
    )

    assert result.category == "remote_output_invalid"
    assert len(starts) == 1
    assert len(runner.calls) == 3
    assert result.metadata_verification_attempted is True
    assert result.metadata_verification_valid is False
    assert result.agent_invocation_attempted is False
    assert result.tunnel_process_reaped is True
    assert "private authentication text" not in json.dumps(result.to_json_dict())


@pytest.mark.parametrize(
    "remote",
    [
        transport.RemoteCommandResult(1, "", "private authentication failure"),
        transport.RemoteCommandResult(3, "", "private authorization failure"),
        transport.RemoteCommandResult(4, "", "private contract drift"),
    ],
)
def test_metadata_remote_failure_is_sanitized_and_never_invokes(remote) -> None:
    runner = FakeSshRunner([*_successful_remote_results()[:2], remote])
    deps, starts, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(),
        dependencies=deps,
    )

    assert result.category == "metadata_verification_failed"
    assert len(starts) == 1
    assert len(runner.calls) == 3
    assert result.metadata_verification_attempted is True
    assert result.managed_identity_attempted is False
    assert result.agent_invocation_attempted is False
    assert result.tunnel_process_reaped is True
    serialized = json.dumps(result.to_json_dict())
    assert remote.stderr not in serialized


def test_metadata_runner_exception_is_sanitized_reaped_and_not_retried() -> None:
    runner = FakeSshRunner(
        [*_successful_remote_results()[:2], RuntimeError("private runner error")]
    )
    deps, starts, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request("live-metadata-verification"),
        approvals=_metadata_approvals(),
        dependencies=deps,
    )

    assert result.category == "unexpected_error"
    assert len(starts) == 1
    assert len(runner.calls) == 3
    assert result.agent_invocation_attempted is False
    assert result.tunnel_process_reaped is True
    assert "private runner error" not in json.dumps(result.to_json_dict())
    assert all(
        type(value) is bool
        for key, value in result.to_json_dict().items()
        if key not in {"category", "mode", "operation", "transport"}
    )


def test_early_child_exit_stops_without_ssh_and_reaps() -> None:
    process = FakeProcess(poll_result=7)
    runner = FakeSshRunner()
    deps, starts, _, signals = _dependencies(
        process=process,
        tunnel_ready=False,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "tunnel_unavailable"
    assert len(starts) == 1
    assert runner.calls == []
    assert signals == []
    assert result.tunnel_process_reaped is True


def test_readiness_observation_is_bounded_and_never_restarts() -> None:
    process = FakeProcess()
    clock = FakeClock()
    deps, starts, _, signals = _dependencies(
        process=process,
        tunnel_ready=False,
        clock=clock,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "tunnel_unavailable"
    assert len(starts) == 1
    assert clock.now == transport.TUNNEL_TIMEOUT_SECONDS
    assert len(clock.sleeps) > 1
    assert signals == ["interrupt"]
    assert result.tunnel_process_reaped is True


def test_owned_listener_establishes_readiness_without_output_marker() -> None:
    observer = FakeOutputObserver(ready=False)
    runner = FakeSshRunner()
    deps, starts, _, _ = _dependencies(
        tunnel_ready=True,
        output_observer=observer,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(probes=False), dependencies=deps
    )

    assert result.category == "approval_denied"
    assert result.tunnel_ready is True
    assert len(starts) == 1
    assert runner.calls == []
    assert observer.closed is True
    assert result.tunnel_process_reaped is True


@pytest.mark.parametrize(
    ("stdout_chunks", "stderr_chunks"),
    [
        ([], []),
        (["unrecognized stdout text\n"], []),
        ([], ["unrecognized stderr text"]),
        (["Ctrl + ", "C to close\n"], []),
    ],
    ids=["empty-output", "stdout-output", "stderr-no-newline", "partial-marker"],
)
def test_listener_readiness_does_not_require_useful_or_complete_cli_output(
    stdout_chunks: list[str],
    stderr_chunks: list[str],
) -> None:
    process = FakeProcess()
    process.stdout = ChunkStream(stdout_chunks)
    process.stderr = ChunkStream(stderr_chunks)
    observer = transport._PrivateTunnelOutputObserver(process)
    for thread in observer._threads:
        thread.join(1)
    runner = FakeSshRunner()
    deps, starts, _, _ = _dependencies(
        process=process,
        tunnel_ready=True,
        output_observer=observer,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(probes=False), dependencies=deps
    )

    assert result.category == "approval_denied"
    assert result.tunnel_ready is True
    assert len(starts) == 1
    assert runner.calls == []
    assert "unrecognized" not in json.dumps(result.to_json_dict())


def test_listener_probe_error_is_sanitized_as_tunnel_unavailable() -> None:
    runner = FakeSshRunner()

    def listener_error(_host: str, _port: int) -> bool:
        raise OSError("private listener error")

    deps, starts, _, _ = _dependencies(
        tunnel_ready=listener_error,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "tunnel_unavailable"
    assert result.tunnel_ready is False
    assert len(starts) == 1
    assert runner.calls == []
    assert result.tunnel_process_reaped is True
    assert "private listener error" not in json.dumps(result.to_json_dict())


def test_multiple_output_lines_in_one_chunk_remain_private_and_bounded() -> None:
    process = FakeProcess()
    process.stdout = ChunkStream(
        ["first line\nCtrl + C to close\nlast private line\n"]
    )
    process.stderr = ChunkStream([])
    observer = transport._PrivateTunnelOutputObserver(process)
    for thread in observer._threads:
        thread.join(1)

    assert observer.ready() is True
    assert observer.failed() is False
    assert not hasattr(observer, "raw_output")
    observer.close()


@pytest.mark.parametrize(
    ("observed_at", "expected_category", "expected_ready"),
    [
        (transport.TUNNEL_TIMEOUT_SECONDS - 0.01, "approval_denied", True),
        (transport.TUNNEL_TIMEOUT_SECONDS, "tunnel_unavailable", False),
    ],
)
def test_listener_readiness_obeys_strict_absolute_deadline(
    observed_at: float,
    expected_category: str,
    expected_ready: bool,
) -> None:
    process = FakeProcess()
    clock = FakeClock()

    def listener_ready(_host: str, _port: int) -> bool:
        clock.now = observed_at
        return True

    deps, starts, _, _ = _dependencies(
        process=process,
        tunnel_ready=listener_ready,
        clock=clock,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(probes=False), dependencies=deps
    )

    assert result.category == expected_category
    assert result.tunnel_ready is expected_ready
    assert len(starts) == 1
    assert result.tunnel_process_reaped is True


def test_zero_exit_before_listener_readiness_is_not_success() -> None:
    process = FakeProcess(poll_result=0)
    runner = FakeSshRunner()
    deps, starts, _, _ = _dependencies(
        process=process,
        tunnel_ready=True,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "tunnel_unavailable"
    assert result.tunnel_ready is False
    assert len(starts) == 1
    assert runner.calls == []
    assert result.tunnel_process_reaped is True


def test_malformed_process_poll_state_is_sanitized_and_ambiguous() -> None:
    process = FakeProcess(poll_result=None)
    process.poll_result = object()
    runner = FakeSshRunner()
    deps, starts, _, _ = _dependencies(process=process, ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "tunnel_outcome_ambiguous"
    assert len(starts) == 1
    assert runner.calls == []
    assert result.tunnel_process_reaped is True
    assert all(
        type(value) is bool
        for key, value in result.to_json_dict().items()
        if key not in {"category", "mode", "operation", "transport"}
    )


def test_output_observation_error_is_sanitized_and_ambiguous() -> None:
    class FailingObserver(FakeOutputObserver):
        def failed(self) -> bool:
            raise OSError("private read failure")

    observer = FailingObserver(ready=False)
    runner = FakeSshRunner()
    deps, starts, _, _ = _dependencies(
        output_observer=observer,
        tunnel_ready=True,
        ssh_runner=runner,
    )

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "tunnel_outcome_ambiguous"
    assert len(starts) == 1
    assert runner.calls == []
    assert result.tunnel_process_reaped is True
    assert "private read failure" not in json.dumps(result.to_json_dict())


def test_private_output_observer_drains_without_retaining_sensitive_text() -> None:
    secret = "password=not-serialized\n" * 20_000
    process = FakeProcess()
    process.stdout = io.StringIO(secret)
    process.stderr = io.StringIO("Ctrl + C to close\n")

    observer = transport._PrivateTunnelOutputObserver(process)
    for thread in observer._threads:
        thread.join(1)

    assert observer.ready() is True
    assert observer.failed() is False
    assert not hasattr(observer, "raw_output")
    observer.close()
    assert process.stdout.closed is True
    assert process.stderr.closed is True


def test_probe_approval_denial_reaps_and_blocks_all_ssh() -> None:
    runner = FakeSshRunner()
    deps, _, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(probes=False), dependencies=deps
    )

    assert result.category == "approval_denied"
    assert runner.calls == []
    assert result.tunnel_process_reaped is True


@pytest.mark.parametrize(
    "interpreter",
    [
        transport.RemoteCommandResult(1, "", "secret"),
        transport.RemoteCommandResult(0, "not-json\n", ""),
        transport.RemoteCommandResult(
            0,
            _line({"app_path_valid": 1, "interpreter_valid": True}),
            "",
        ),
        transport.RemoteCommandResult(
            0,
            _line({"app_path_valid": True, "interpreter_valid": True}) + "extra\n",
            "",
        ),
    ],
)
def test_interpreter_probe_failure_blocks_later_phases_and_sanitizes(
    interpreter: transport.RemoteCommandResult,
) -> None:
    runner = FakeSshRunner([interpreter])
    deps, _, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "interpreter_probe_failed"
    assert len(runner.calls) == 1
    assert result.module_probe_attempted is False
    assert result.remote_check_attempted is False
    assert "secret" not in json.dumps(result.to_json_dict())
    assert result.tunnel_process_reaped is True


def test_module_probe_failure_blocks_remote_check() -> None:
    runner = FakeSshRunner(
        [
            _successful_remote_results()[0],
            transport.RemoteCommandResult(
                0, _line({"packaged_module_valid": False}), "raw"
            ),
        ]
    )
    deps, _, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "module_probe_failed"
    assert len(runner.calls) == 2
    assert result.remote_check_attempted is False


def test_remote_check_approval_denial_stops_after_two_probes() -> None:
    runner = FakeSshRunner(_successful_remote_results()[:2])
    deps, _, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(remote=False), dependencies=deps
    )

    assert result.category == "approval_denied"
    assert len(runner.calls) == 2
    assert result.remote_check_attempted is False


@pytest.mark.parametrize(
    ("remote", "category"),
    [
        (transport.RemoteCommandResult(2, "", "secret"), "remote_check_failed"),
        (transport.RemoteCommandResult(0, "{}\n", ""), "remote_output_invalid"),
        (
            transport.RemoteCommandResult(0, _line({**_proof_payload(), "ok": 1}), ""),
            "remote_output_invalid",
        ),
        (
            transport.RemoteCommandResult(0, _line(_proof_payload()) + "extra\n", ""),
            "remote_output_invalid",
        ),
    ],
)
def test_remote_check_fails_closed_for_nonexact_outcome(
    remote: transport.RemoteCommandResult,
    category: str,
) -> None:
    runner = FakeSshRunner([*_successful_remote_results()[:2], remote])
    deps, _, _, _ = _dependencies(ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == category
    assert result.remote_check_valid is False
    assert result.tunnel_process_reaped is True
    assert "secret" not in json.dumps(result.to_json_dict())


def test_keyboard_interrupt_after_tunnel_construction_reaps_the_only_child() -> None:
    process = FakeProcess()
    runner = FakeSshRunner([KeyboardInterrupt()])
    deps, starts, _, signals = _dependencies(process=process, ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert len(starts) == 1
    assert result.category == "interrupted"
    assert result.remote_check_attempted is False
    assert signals == ["interrupt"]
    assert process.reaped is True
    assert result.tunnel_process_reaped is True


def test_sigterm_during_process_construction_is_deferred_until_reap(
    monkeypatch,
) -> None:
    handlers = {}
    monkeypatch.setattr(transport.signal, "getsignal", lambda _number: object())
    monkeypatch.setattr(
        transport.signal,
        "signal",
        lambda number, handler: handlers.__setitem__(number, handler),
    )
    process = FakeProcess()

    def start(_args):
        handlers[transport.signal.SIGTERM](transport.signal.SIGTERM, None)
        return process

    deps, starts, _, _ = _dependencies(process_factory=start)
    deps = replace(deps, install_signal_handlers=True)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert len(starts) == 1
    assert result.category == "interrupted"
    assert result.tunnel_process_reaped is True
    assert process.reaped is True


def test_sigterm_during_cleanup_is_deferred_until_reap(monkeypatch) -> None:
    handlers = {}
    monkeypatch.setattr(transport.signal, "getsignal", lambda _number: object())
    monkeypatch.setattr(
        transport.signal,
        "signal",
        lambda number, handler: handlers.__setitem__(number, handler),
    )

    class SignalDuringWaitProcess(FakeProcess):
        def wait(self, timeout: float | None = None):
            if not self.wait_calls:
                handlers[transport.signal.SIGTERM](transport.signal.SIGTERM, None)
            return super().wait(timeout)

    process = SignalDuringWaitProcess()
    deps, _, _, _ = _dependencies(process=process)
    deps = replace(deps, install_signal_handlers=True)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.ok is True
    assert result.tunnel_process_reaped is True
    assert process.reaped is True


def test_exception_after_construction_is_sanitized_and_reaped() -> None:
    process = FakeProcess()
    runner = FakeSshRunner([RuntimeError("secret")])
    deps, _, _, _ = _dependencies(process=process, ssh_runner=runner)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.category == "unexpected_error"
    assert result.tunnel_process_reaped is True
    assert "secret" not in json.dumps(result.to_json_dict())


def test_cleanup_escalates_interrupt_then_terminate_and_reaps() -> None:
    timeout = subprocess.TimeoutExpired("tunnel", 1)
    process = FakeProcess(wait_outcomes=[timeout, 0])
    deps, _, _, signals = _dependencies(process=process)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.ok is True
    assert signals == ["interrupt", "terminate"]
    assert result.tunnel_terminate_sent is True
    assert result.tunnel_kill_sent is False
    assert result.tunnel_process_reaped is True


def test_cleanup_escalates_through_kill_and_reaps() -> None:
    timeout = subprocess.TimeoutExpired("tunnel", 1)
    process = FakeProcess(wait_outcomes=[timeout, timeout, 0])
    deps, _, _, signals = _dependencies(process=process)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.ok is True
    assert signals == ["interrupt", "terminate", "kill"]
    assert result.tunnel_kill_sent is True
    assert result.tunnel_process_reaped is True


def test_post_kill_wait_continues_until_the_child_is_reaped() -> None:
    timeout = subprocess.TimeoutExpired("tunnel", 1)
    process = FakeProcess(wait_outcomes=[timeout, timeout, timeout, 0])
    deps, _, _, _ = _dependencies(process=process)

    result = _service().run_live_tunnel(
        _request(), approvals=_approvals(), dependencies=deps
    )

    assert result.ok is True
    assert result.tunnel_kill_sent is True
    assert result.tunnel_process_reaped is True
    assert process.wait_calls[-2:] == [None, None]


def test_module_probe_rejects_same_named_module_outside_app_path(tmp_path) -> None:
    app_path = tmp_path / "empty-app"
    fallback = tmp_path / "fallback"
    module_dir = fallback / "src" / "app" / "operations"
    app_path.mkdir()
    module_dir.mkdir(parents=True)
    for package in (fallback / "src", fallback / "src" / "app", module_dir):
        (package / "__init__.py").write_text("")
    (module_dir / "prove_hosted_foundry_agent.py").write_text(
        "def run_hosted_foundry_agent_proof(mode):\n    return mode\n"
    )
    environment = os.environ.copy()
    environment.update(APP_PATH=str(app_path), PYTHONPATH=str(fallback))

    completed = subprocess.run(
        [sys.executable, "-c", transport._MODULE_PROGRAM],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout) == {"packaged_module_valid": False}
    assert str(fallback) not in completed.stdout


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("mode", "live"),
        ("subscription", " --unsafe"),
        ("resource_group", "unsafe/group"),
        ("web_app_name", "unsafe app"),
    ],
)
def test_invalid_request_fails_before_approval_or_dependencies(
    field: str,
    value: str,
) -> None:
    request = replace(_request(), **{field: value})
    approvals = transport.HostedFoundryAgentSshTransportApprovals(
        approve_tunnel=lambda: pytest.fail("invalid request must stop"),
        approve_probes=lambda: pytest.fail("invalid request must stop"),
        approve_remote_check=lambda: pytest.fail("invalid request must stop"),
    )

    result = _service().run_live_tunnel(request, approvals=approvals)

    assert result.category == "configuration_invalid"
    assert result.tunnel_process_started is False


def test_result_schema_never_serializes_sensitive_or_command_values() -> None:
    payload = _service().check(
        transport.build_hosted_foundry_agent_ssh_transport_check_request()
    ).to_json_dict()
    serialized = json.dumps(payload)

    for forbidden in (
        "contract-subscription",
        "contract-rg",
        "contract-web-app",
        str(transport.LOCAL_PORT),
        "APP_PATH",
        "create-remote-connection",
        "root@",
        "known-hosts",
    ):
        assert forbidden not in serialized
