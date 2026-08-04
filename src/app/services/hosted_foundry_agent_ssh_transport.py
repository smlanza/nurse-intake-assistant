"""Owned lifecycle for a future supervised App Service TCP/SSH transport."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from typing import Callable, Literal, Protocol

from src.app.services.hosted_foundry_agent_verification import (
    HostedFoundryAgentVerificationResult,
)
from src.app.services.web_app_configuration_verification import (
    WebAppConfigurationVerificationResult,
)
from src.app.services.web_app_hosting_contract import (
    HOSTED_VERIFIER_SETTING_NAMES,
    hosted_verifier_settings_valid,
)


TransportMode = Literal["check", "live-tunnel", "live-metadata-verification"]
TunnelReadinessOutcome = Literal["ready", "unavailable", "ambiguous"]
TunnelProcessState = Literal["alive", "unavailable", "ambiguous"]
TransportCategory = Literal[
    "check_passed",
    "success",
    "configuration_invalid",
    "hosted_verifier_configuration_invalid",
    "ssh_hosted_identity_execution_unsupported",
    "cli_unsupported",
    "approval_denied",
    "port_unavailable",
    "tunnel_start_failed",
    "tunnel_unavailable",
    "tunnel_outcome_ambiguous",
    "interpreter_probe_failed",
    "module_probe_failed",
    "remote_check_failed",
    "metadata_verification_failed",
    "remote_output_invalid",
    "interrupted",
    "cleanup_failed",
    "unexpected_error",
]

OPERATION = "run_hosted_foundry_agent_ssh_transport"
TRANSPORT = "app_service_tcp_tunnel"
LOOPBACK_HOST = "127.0.0.1"
LOCAL_PORT = 49221
TUNNEL_TIMEOUT_SECONDS = 900
READINESS_INTERVAL_SECONDS = 0.25
CLEANUP_WAIT_SECONDS = 2.0
REMOTE_TARGET = "root@127.0.0.1"
PACKAGED_MODULE = "src.app.operations.prove_hosted_foundry_agent"
METADATA_VERIFICATION_MODULE = "src.app.operations.verify_hosted_foundry_agent"

_INTERPRETER_PROGRAM = (
    "import json,os;"
    "value=os.environ.get('APP_PATH');"
    "valid=isinstance(value,str) and os.path.isabs(value) and '\\x00' not in value;"
    "print(json.dumps({'app_path_valid':valid,'interpreter_valid':True},"
    "separators=(',',':'),sort_keys=True))"
)
_MODULE_PROGRAM = (
    "import importlib,inspect,json,os,pathlib,sys;"
    "value=os.environ.get('APP_PATH');"
    "valid=isinstance(value,str) and os.path.isabs(value) and '\\x00' not in value;"
    "root=pathlib.Path(value).resolve() if valid else None;"
    "sys.path.insert(0,value) if valid else None;"
    f"module=importlib.import_module('{PACKAGED_MODULE}') if valid else None;"
    "entry=getattr(module,'run_hosted_foundry_agent_proof',None) if module else None;"
    "module_path=pathlib.Path(module.__file__).resolve() if module and "
    "getattr(module,'__file__',None) else None;"
    "entry_source=inspect.getsourcefile(entry) if callable(entry) else None;"
    "entry_path=pathlib.Path(entry_source).resolve() if entry_source else None;"
    f"ok=module is not None and module.__name__=='{PACKAGED_MODULE}' and "
    "callable(entry) and module_path is not None and entry_path is not None and "
    "(module_path==root or root in module_path.parents) and "
    "(entry_path==root or root in entry_path.parents);"
    "print(json.dumps({'packaged_module_valid':ok},"
    "separators=(',',':'),sort_keys=True))"
)
INTERPRETER_PROBE_COMMAND = f"python -c {shlex.quote(_INTERPRETER_PROGRAM)}"
MODULE_PROBE_COMMAND = f"python -c {shlex.quote(_MODULE_PROGRAM)}"
REMOTE_CHECK_COMMAND = (
    'cd "$APP_PATH" && python -m '
    f"{PACKAGED_MODULE} --check --json"
)
REMOTE_METADATA_VERIFICATION_COMMAND = (
    'cd "$APP_PATH" && python -m '
    f"{METADATA_VERIFICATION_MODULE} --live --json"
)
PERMITTED_REMOTE_COMMANDS = (
    INTERPRETER_PROBE_COMMAND,
    MODULE_PROBE_COMMAND,
    REMOTE_CHECK_COMMAND,
    REMOTE_METADATA_VERIFICATION_COMMAND,
)

_REQUIRED_CREATE_REMOTE_CONNECTION_OPTIONS = (
    "--subscription",
    "--resource-group",
    "--name",
    "--port",
    "--timeout",
    "--only-show-errors",
)
_TUNNEL_READY_MARKER = "Ctrl + C to close"
_TUNNEL_FAILURE_MARKERS = (
    "error:",
    "unavailable",
    "unreachable",
    "not enabled",
    "failed",
)
_SAFE_SUBSCRIPTION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()\-]{0,127}$")
_SAFE_RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()\-]{0,89}$")


@dataclass(frozen=True)
class AzureCliHelpSurface:
    create_remote_connection: str
    preview_ssh: str


@dataclass(frozen=True)
class HostedFoundryAgentSshTransportRequest:
    mode: str
    subscription: str
    resource_group: str
    web_app_name: str


@dataclass(frozen=True, repr=False, init=False)
class HostedVerifierRuntimeConfiguration:
    """Historical private settings contract for the retired SSH metadata path."""

    _ordered_values: tuple[str, ...]

    def __init__(self, values: Mapping[str, object]) -> None:
        try:
            if (
                not isinstance(values, Mapping)
                or not hosted_verifier_settings_valid(values)
            ):
                raise ValueError
            ordered_values = tuple(
                values[name] for name in HOSTED_VERIFIER_SETTING_NAMES
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError(
                "Hosted verifier runtime configuration is invalid."
            ) from None
        object.__setattr__(self, "_ordered_values", ordered_values)

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, object],
    ) -> "HostedVerifierRuntimeConfiguration":
        return cls(values)

    def _assignment_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(zip(HOSTED_VERIFIER_SETTING_NAMES, self._ordered_values))


def _deny_approval() -> bool:
    return False


@dataclass(frozen=True)
class HostedFoundryAgentSshTransportApprovals:
    approve_tunnel: Callable[[], bool]
    approve_probes: Callable[[], bool]
    approve_remote_check: Callable[[], bool]
    approve_metadata_verification: Callable[[], bool] = _deny_approval


@dataclass(frozen=True)
class RemoteCommandResult:
    return_code: int
    stdout: str
    stderr: str


class ProcessLike(Protocol):
    pid: int
    stdout: object
    stderr: object

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class TunnelOutputObserver(Protocol):
    def ready(self) -> bool: ...

    def failed(self) -> bool: ...

    def close(self) -> None: ...


class SshRunner(Protocol):
    def run(
        self,
        args: tuple[str, ...],
        timeout_seconds: float,
    ) -> RemoteCommandResult: ...


@dataclass(frozen=True)
class HostedFoundryAgentSshTransportDependencies:
    process_factory: Callable[[tuple[str, ...]], ProcessLike]
    port_available: Callable[[str, int], bool]
    tunnel_ready: Callable[[str, int], bool]
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    ssh_runner: SshRunner
    observe_tunnel_output: Callable[[ProcessLike], TunnelOutputObserver]
    create_known_hosts: Callable[[], str]
    remove_known_hosts: Callable[[str], None]
    send_interrupt: Callable[[ProcessLike], None]
    terminate: Callable[[ProcessLike], None]
    kill: Callable[[ProcessLike], None]
    install_signal_handlers: bool = False


@dataclass(frozen=True)
class HostedFoundryAgentSshTransportResult:
    ok: bool
    category: TransportCategory
    operation: str
    mode: str
    transport: str
    cli_help_contract_valid: bool
    tunnel_command_valid: bool
    remote_command_contract_valid: bool
    sanitization_policy_valid: bool
    cleanup_policy_valid: bool
    tunnel_process_started: bool
    tunnel_ready: bool
    ssh_command_attempted: bool
    interpreter_probe_attempted: bool
    interpreter_valid: bool
    module_probe_attempted: bool
    packaged_module_valid: bool
    remote_check_attempted: bool
    remote_check_valid: bool
    metadata_verification_valid: bool
    tunnel_interrupt_sent: bool
    tunnel_terminate_sent: bool
    tunnel_kill_sent: bool
    tunnel_process_reaped: bool
    private_known_hosts_created: bool
    private_known_hosts_removed: bool
    managed_identity_attempted: bool
    metadata_verification_attempted: bool
    agent_invocation_attempted: bool
    azure_call_made: bool
    azure_mutation_made: bool
    metadata_verifier_category: str | None = None

    @classmethod
    def build(
        cls,
        *,
        ok: bool,
        category: TransportCategory,
        mode: str,
        **progress: object,
    ) -> "HostedFoundryAgentSshTransportResult":
        values = {
            "cli_help_contract_valid": False,
            "tunnel_command_valid": False,
            "remote_command_contract_valid": False,
            "sanitization_policy_valid": False,
            "cleanup_policy_valid": False,
            "tunnel_process_started": False,
            "tunnel_ready": False,
            "ssh_command_attempted": False,
            "interpreter_probe_attempted": False,
            "interpreter_valid": False,
            "module_probe_attempted": False,
            "packaged_module_valid": False,
            "remote_check_attempted": False,
            "remote_check_valid": False,
            "metadata_verification_valid": False,
            "tunnel_interrupt_sent": False,
            "tunnel_terminate_sent": False,
            "tunnel_kill_sent": False,
            "tunnel_process_reaped": False,
            "private_known_hosts_created": False,
            "private_known_hosts_removed": False,
            "managed_identity_attempted": False,
            "metadata_verification_attempted": False,
            "agent_invocation_attempted": False,
            "azure_call_made": False,
            "azure_mutation_made": False,
        }
        values.update(progress)
        return cls(
            ok=ok,
            category=category,
            operation=OPERATION,
            mode=(
                mode
                if mode in {"check", "live-tunnel", "live-metadata-verification"}
                else "invalid"
            ),
            transport=TRANSPORT,
            **values,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
            if getattr(self, field) is not None
        }


class InstalledAzureCliHelpReader:
    """Read the installed CLI command declarations without starting the CLI."""

    def read(self) -> AzureCliHelpSurface | None:
        executable = shutil.which("az")
        if executable is None:
            return None
        try:
            resolved = Path(executable).resolve(strict=True)
        except OSError:
            return None
        roots = list(
            resolved.parents[1].glob(
                "libexec/lib/python*/site-packages/azure/cli/command_modules/appservice"
            )
        )
        if len(roots) != 1:
            return None
        try:
            commands = (roots[0] / "commands.py").read_text()
            parameters = (roots[0] / "_params.py").read_text()
            help_text = (roots[0] / "_help.py").read_text()
            custom = (roots[0] / "custom.py").read_text()
        except OSError:
            return None
        create_registered = (
            "create-remote-connection" in commands
            and "create_tunnel" in commands
            and "webapp create-remote-connection" in parameters
            and "webapp create-remote-connection" in help_text
        )
        ssh_registered = (
            "webapp ssh" in parameters
            and "webapp ssh" in help_text
            and "ssh_webapp" in commands
        )
        if (
            not create_registered
            or not ssh_registered
            or _TUNNEL_READY_MARKER not in custom
        ):
            return None
        create_surface = " ".join(
            (
                "webapp create-remote-connection",
                "--subscription",
                "--resource-group",
                "--name",
                "--port" if "c.argument('port'" in parameters else "",
                "--timeout" if "c.argument('timeout'" in parameters else "",
                "--only-show-errors",
                _TUNNEL_READY_MARKER,
            )
        )
        return AzureCliHelpSurface(
            create_remote_connection=create_surface,
            preview_ssh="webapp ssh preview",
        )


def build_hosted_foundry_agent_ssh_transport_check_request() -> (
    HostedFoundryAgentSshTransportRequest
):
    return HostedFoundryAgentSshTransportRequest(
        mode="check",
        subscription="contract-subscription",
        resource_group="contract-rg",
        web_app_name="contract-web-app",
    )


def build_tunnel_command(
    request: HostedFoundryAgentSshTransportRequest,
) -> tuple[str, ...]:
    return (
        "az",
        "webapp",
        "create-remote-connection",
        "--subscription",
        request.subscription,
        "--resource-group",
        request.resource_group,
        "--name",
        request.web_app_name,
        "--port",
        str(LOCAL_PORT),
        "--timeout",
        str(TUNNEL_TIMEOUT_SECONDS),
        "--only-show-errors",
    )


def _build_metadata_verification_command(
    configuration: HostedVerifierRuntimeConfiguration,
) -> str:
    if type(configuration) is not HostedVerifierRuntimeConfiguration:
        raise ValueError("Hosted verifier runtime configuration is invalid.")
    assignments = " ".join(
        shlex.quote(f"{name}={value}")
        for name, value in configuration._assignment_pairs()
    )
    return (
        'cd "$APP_PATH" && env '
        f"{assignments} python -m {METADATA_VERIFICATION_MODULE} --live --json"
    )


def build_ssh_command(
    command: str,
    known_hosts_path: str,
    *,
    hosted_verifier_runtime_configuration: (
        HostedVerifierRuntimeConfiguration | None
    ) = None,
) -> tuple[str, ...]:
    if command not in PERMITTED_REMOTE_COMMANDS:
        raise ValueError("unsupported remote command")
    if command == REMOTE_METADATA_VERIFICATION_COMMAND:
        command = _build_metadata_verification_command(
            hosted_verifier_runtime_configuration
        )
    elif hosted_verifier_runtime_configuration is not None:
        raise ValueError("unsupported remote configuration")
    if not isinstance(known_hosts_path, str) or not known_hosts_path:
        raise ValueError("invalid known-hosts path")
    return (
        "ssh",
        "-T",
        "-p",
        str(LOCAL_PORT),
        "-o",
        f"UserKnownHostsFile={known_hosts_path}",
        "-o",
        "GlobalKnownHostsFile=/dev/null",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "LogLevel=ERROR",
        REMOTE_TARGET,
        command,
    )


class HostedFoundryAgentSshTransport:
    """Own supported non-invoking SSH; retain retired metadata test evidence."""

    def __init__(
        self,
        *,
        help_reader: Callable[[], AzureCliHelpSurface | None] | None = None,
        hosted_verifier_configuration_proof: (
            WebAppConfigurationVerificationResult | None
        ) = None,
        hosted_verifier_runtime_configuration: (
            HostedVerifierRuntimeConfiguration | None
        ) = None,
    ) -> None:
        self._help_reader = help_reader or InstalledAzureCliHelpReader().read
        self._hosted_verifier_configuration_proof = (
            hosted_verifier_configuration_proof
        )
        self._hosted_verifier_runtime_configuration = (
            hosted_verifier_runtime_configuration
        )

    def permitted_remote_commands(self) -> tuple[str, ...]:
        return PERMITTED_REMOTE_COMMANDS

    def check(
        self,
        request: HostedFoundryAgentSshTransportRequest,
    ) -> HostedFoundryAgentSshTransportResult:
        if not _request_valid(request, expected_mode="check"):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="configuration_invalid",
                mode=request.mode,
            )
        if not self._cli_contract_valid():
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="cli_unsupported",
                mode="check",
            )
        if not _fixed_contract_valid(request):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="configuration_invalid",
                mode="check",
            )
        return HostedFoundryAgentSshTransportResult.build(
            ok=True,
            category="check_passed",
            mode="check",
            cli_help_contract_valid=True,
            tunnel_command_valid=True,
            remote_command_contract_valid=True,
            sanitization_policy_valid=True,
            cleanup_policy_valid=True,
        )

    def run_live_tunnel(
        self,
        request: HostedFoundryAgentSshTransportRequest,
        *,
        approvals: HostedFoundryAgentSshTransportApprovals,
        dependencies: HostedFoundryAgentSshTransportDependencies | None = None,
    ) -> HostedFoundryAgentSshTransportResult:
        if not any(
            _request_valid(request, expected_mode=mode)
            for mode in ("live-tunnel", "live-metadata-verification")
        ):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="configuration_invalid",
                mode=request.mode,
            )
        mode = request.mode
        if not self._cli_contract_valid() or not _fixed_contract_valid(request):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="cli_unsupported",
                mode=mode,
            )
        progress = {
            "cli_help_contract_valid": True,
            "tunnel_command_valid": True,
            "remote_command_contract_valid": True,
            "sanitization_policy_valid": True,
            "cleanup_policy_valid": True,
        }
        if mode == "live-metadata-verification":
            proof = self._hosted_verifier_configuration_proof
            runtime_configuration = self._hosted_verifier_runtime_configuration
            proof_attempted = bool(
                type(proof) is WebAppConfigurationVerificationResult
                and proof.azure_request_attempted is True
            )
            if (
                not _hosted_verifier_configuration_proof_valid(proof)
                or type(runtime_configuration)
                is not HostedVerifierRuntimeConfiguration
            ):
                return HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="hosted_verifier_configuration_invalid",
                    mode=mode,
                    azure_call_made=proof_attempted,
                    **progress,
                )
            progress["azure_call_made"] = True
        try:
            if approvals.approve_tunnel() is not True:
                return HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="approval_denied",
                    mode=mode,
                    **progress,
                )
        except BaseException:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode=mode,
                **progress,
            )

        deps = dependencies or _default_dependencies()
        if deps.port_available(LOOPBACK_HOST, LOCAL_PORT) is not True:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="port_unavailable",
                mode=mode,
                **progress,
            )

        process: ProcessLike | None = None
        output_observer: TunnelOutputObserver | None = None
        known_hosts_path: str | None = None
        result = HostedFoundryAgentSshTransportResult.build(
            ok=False,
            category="unexpected_error",
            mode=mode,
            **progress,
        )
        signal_context = (
            _temporary_signal_handlers()
            if deps.install_signal_handlers
            else nullcontext(_SignalInterruptionGuard())
        )
        with signal_context as interruption:
            try:
                known_hosts_path = deps.create_known_hosts()
                progress["private_known_hosts_created"] = True
                interruption.raise_if_pending()
                process = deps.process_factory(build_tunnel_command(request))
                progress.update(
                    tunnel_process_started=True,
                    azure_call_made=True,
                )
                interruption.arm()
                output_observer = deps.observe_tunnel_output(process)
                deadline = deps.monotonic() + TUNNEL_TIMEOUT_SECONDS
                readiness = _observe_tunnel_ready(
                    process,
                    output_observer,
                    deadline,
                    deps,
                )
                if readiness != "ready":
                    category: TransportCategory = (
                        "tunnel_outcome_ambiguous"
                        if readiness == "ambiguous"
                        else "tunnel_unavailable"
                    )
                    result = HostedFoundryAgentSshTransportResult.build(
                        ok=False,
                        category=category,
                        mode=mode,
                        **progress,
                    )
                else:
                    progress["tunnel_ready"] = True
                    result = self._run_remote_phases(
                        approvals,
                        deps,
                        known_hosts_path,
                        deadline,
                        progress,
                        mode,
                    )
            except (KeyboardInterrupt, _TransportInterrupted):
                result = HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="interrupted",
                    mode=mode,
                    **progress,
                )
            except OSError:
                result = HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category=(
                        "tunnel_start_failed"
                        if process is None
                        else "unexpected_error"
                    ),
                    mode=mode,
                    **progress,
                )
            except BaseException:
                result = HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="unexpected_error",
                    mode=mode,
                    **progress,
                )
            finally:
                interruption.begin_cleanup()
                cleanup = _cleanup(
                    process,
                    output_observer,
                    known_hosts_path,
                    deps,
                )
                result = replace(result, **cleanup)
                if result.ok is True and not (
                    result.tunnel_process_reaped is True
                    and result.private_known_hosts_removed is True
                ):
                    result = replace(result, ok=False, category="cleanup_failed")
        return result

    def _run_remote_phases(
        self,
        approvals: HostedFoundryAgentSshTransportApprovals,
        deps: HostedFoundryAgentSshTransportDependencies,
        known_hosts_path: str,
        deadline: float,
        progress: dict[str, bool],
        mode: str,
    ) -> HostedFoundryAgentSshTransportResult:
        if approvals.approve_probes() is not True:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode=mode,
                **progress,
            )
        progress.update(
            ssh_command_attempted=True,
            interpreter_probe_attempted=True,
        )
        interpreter = _run_ssh(
            deps,
            INTERPRETER_PROBE_COMMAND,
            known_hosts_path,
            deadline,
        )
        if not _exact_json_result(
            interpreter,
            {"app_path_valid": True, "interpreter_valid": True},
        ):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="interpreter_probe_failed",
                mode=mode,
                **progress,
            )
        progress.update(interpreter_valid=True, module_probe_attempted=True)
        module = _run_ssh(
            deps,
            MODULE_PROBE_COMMAND,
            known_hosts_path,
            deadline,
        )
        if not _exact_json_result(module, {"packaged_module_valid": True}):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="module_probe_failed",
                mode=mode,
                **progress,
            )
        progress["packaged_module_valid"] = True
        if mode == "live-metadata-verification":
            return self._run_metadata_verification(
                approvals,
                deps,
                known_hosts_path,
                deadline,
                progress,
            )
        if approvals.approve_remote_check() is not True:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode="live-tunnel",
                **progress,
            )
        progress["remote_check_attempted"] = True
        remote = _run_ssh(
            deps,
            REMOTE_CHECK_COMMAND,
            known_hosts_path,
            deadline,
        )
        if remote.return_code != 0:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="remote_check_failed",
                mode="live-tunnel",
                **progress,
            )
        if not _remote_check_result_valid(remote.stdout):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="remote_output_invalid",
                mode="live-tunnel",
                **progress,
            )
        progress["remote_check_valid"] = True
        return HostedFoundryAgentSshTransportResult.build(
            ok=True,
            category="success",
            mode="live-tunnel",
            **progress,
        )

    def _run_metadata_verification(
        self,
        approvals: HostedFoundryAgentSshTransportApprovals,
        deps: HostedFoundryAgentSshTransportDependencies,
        known_hosts_path: str,
        deadline: float,
        progress: dict[str, bool],
    ) -> HostedFoundryAgentSshTransportResult:
        try:
            approved = approvals.approve_metadata_verification() is True
        except (KeyboardInterrupt, _TransportInterrupted):
            raise
        except BaseException:
            approved = False
        if not approved:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode="live-metadata-verification",
                **progress,
            )
        progress["metadata_verification_attempted"] = True
        remote = _run_ssh(
            deps,
            REMOTE_METADATA_VERIFICATION_COMMAND,
            known_hosts_path,
            deadline,
            hosted_verifier_runtime_configuration=(
                self._hosted_verifier_runtime_configuration
            ),
        )
        if type(remote) is not RemoteCommandResult:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="metadata_verification_failed",
                mode="live-metadata-verification",
                **progress,
            )
        if remote.return_code != 0:
            failure = _recognized_metadata_verification_failure(remote)
            if failure is not None:
                verifier_category, managed_identity_attempted = failure
                progress["managed_identity_attempted"] = (
                    managed_identity_attempted
                )
                return HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="metadata_verification_failed",
                    mode="live-metadata-verification",
                    metadata_verifier_category=verifier_category,
                    **progress,
                )
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="metadata_verification_failed",
                mode="live-metadata-verification",
                **progress,
            )
        if not _metadata_verification_result_valid(remote):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="remote_output_invalid",
                mode="live-metadata-verification",
                **progress,
            )
        progress.update(
            managed_identity_attempted=True,
            metadata_verification_valid=True,
        )
        return HostedFoundryAgentSshTransportResult.build(
            ok=True,
            category="success",
            mode="live-metadata-verification",
            **progress,
        )

    def _cli_contract_valid(self) -> bool:
        try:
            surface = self._help_reader()
        except Exception:
            return False
        return bool(
            type(surface) is AzureCliHelpSurface
            and "webapp create-remote-connection"
            in surface.create_remote_connection
            and all(
                option in surface.create_remote_connection
                for option in _REQUIRED_CREATE_REMOTE_CONNECTION_OPTIONS
            )
            and _TUNNEL_READY_MARKER in surface.create_remote_connection
            and "webapp ssh" in surface.preview_ssh
        )


def _hosted_verifier_configuration_proof_valid(value: object) -> bool:
    return bool(
        type(value) is WebAppConfigurationVerificationResult
        and value
        == WebAppConfigurationVerificationResult.live_success(
            hosted_verifier_configuration_verified=True
        )
    )


def _request_valid(
    request: object,
    *,
    expected_mode: TransportMode,
) -> bool:
    return bool(
        type(request) is HostedFoundryAgentSshTransportRequest
        and request.mode == expected_mode
        and _SAFE_SUBSCRIPTION.fullmatch(request.subscription)
        and _SAFE_RESOURCE_NAME.fullmatch(request.resource_group)
        and _SAFE_RESOURCE_NAME.fullmatch(request.web_app_name)
    )


def _fixed_contract_valid(request: HostedFoundryAgentSshTransportRequest) -> bool:
    command = build_tunnel_command(request)
    return bool(
        1024 <= LOCAL_PORT <= 65535
        and TUNNEL_TIMEOUT_SECONDS > 0
        and CLEANUP_WAIT_SECONDS > 0
        and command.count("az") == 1
        and "ssh" not in command
        and "--slot" not in command
        and "--instance" not in command
        and "--debug" not in command
        and "--verbose" not in command
        and PERMITTED_REMOTE_COMMANDS
        == (
            INTERPRETER_PROBE_COMMAND,
            MODULE_PROBE_COMMAND,
            REMOTE_CHECK_COMMAND,
            REMOTE_METADATA_VERIFICATION_COMMAND,
        )
        and REMOTE_CHECK_COMMAND.endswith("--check --json")
        and REMOTE_METADATA_VERIFICATION_COMMAND.endswith("--live --json")
        and all(
            "--live" not in remote
            for remote in PERMITTED_REMOTE_COMMANDS[:-1]
        )
        and PACKAGED_MODULE not in REMOTE_METADATA_VERIFICATION_COMMAND
        and "invoke_hosted_foundry_agent"
        not in REMOTE_METADATA_VERIFICATION_COMMAND
        and "APP_PATH" in INTERPRETER_PROBE_COMMAND
        and "APP_PATH" in MODULE_PROBE_COMMAND
        and "APP_PATH" in REMOTE_CHECK_COMMAND
        and "/home/site/wwwroot" not in " ".join(PERMITTED_REMOTE_COMMANDS)
    )


def _observe_tunnel_ready(
    process: ProcessLike,
    output_observer: TunnelOutputObserver,
    deadline: float,
    deps: HostedFoundryAgentSshTransportDependencies,
) -> TunnelReadinessOutcome:
    while deps.monotonic() < deadline:
        process_state = _tunnel_process_state(process)
        if process_state != "alive":
            return process_state
        output_failed = _tunnel_output_failed(output_observer)
        if output_failed is None:
            return "ambiguous"
        if output_failed:
            return "unavailable"
        try:
            listener_ready = deps.tunnel_ready(LOOPBACK_HOST, LOCAL_PORT)
        except (KeyboardInterrupt, _TransportInterrupted):
            raise
        except BaseException:
            return "unavailable"
        if type(listener_ready) is not bool:
            return "ambiguous"
        if listener_ready:
            if deps.monotonic() >= deadline:
                return "unavailable"
            process_state = _tunnel_process_state(process)
            if process_state != "alive":
                return process_state
            output_failed = _tunnel_output_failed(output_observer)
            if output_failed is None:
                return "ambiguous"
            if output_failed or deps.monotonic() >= deadline:
                return "unavailable"
            return "ready"
        remaining = deadline - deps.monotonic()
        if remaining <= 0:
            break
        deps.sleep(min(READINESS_INTERVAL_SECONDS, remaining))
    return "unavailable"


def _tunnel_process_state(process: ProcessLike) -> TunnelProcessState:
    try:
        return_code = process.poll()
    except (KeyboardInterrupt, _TransportInterrupted):
        raise
    except BaseException:
        return "ambiguous"
    if return_code is None:
        return "alive"
    if type(return_code) is int:
        return "unavailable"
    return "ambiguous"


def _tunnel_output_failed(
    output_observer: TunnelOutputObserver,
) -> bool | None:
    try:
        failed = output_observer.failed()
    except (KeyboardInterrupt, _TransportInterrupted):
        raise
    except BaseException:
        return None
    return failed if type(failed) is bool else None


def _run_ssh(
    deps: HostedFoundryAgentSshTransportDependencies,
    command: str,
    known_hosts_path: str,
    deadline: float,
    *,
    hosted_verifier_runtime_configuration: (
        HostedVerifierRuntimeConfiguration | None
    ) = None,
) -> RemoteCommandResult:
    remaining = deadline - deps.monotonic()
    if remaining <= 0:
        return RemoteCommandResult(124, "", "")
    return deps.ssh_runner.run(
        build_ssh_command(
            command,
            known_hosts_path,
            hosted_verifier_runtime_configuration=(
                hosted_verifier_runtime_configuration
            ),
        ),
        remaining,
    )


def _exact_json_result(
    result: RemoteCommandResult,
    expected: dict[str, object],
) -> bool:
    if type(result) is not RemoteCommandResult or result.return_code != 0:
        return False
    if not _one_json_document(result.stdout):
        return False
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError):
        return False
    return bool(
        type(payload) is dict
        and payload.keys() == expected.keys()
        and all(_exact_value(payload[key], value) for key, value in expected.items())
    )


def _one_json_document(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value.endswith("\n")
        and value.count("\n") == 1
        and value.strip()
    )


def _remote_check_result_valid(value: object) -> bool:
    if not _one_json_document(value):
        return False
    try:
        payload = json.loads(value)
    except (TypeError, ValueError):
        return False
    expected = {
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
    return bool(
        type(payload) is dict
        and payload.keys() == expected.keys()
        and all(_exact_value(payload[key], value) for key, value in expected.items())
    )


def _metadata_verification_result_valid(result: RemoteCommandResult) -> bool:
    if (
        type(result) is not RemoteCommandResult
        or result.return_code != 0
        or result.stderr != ""
        or not _one_json_document(result.stdout)
    ):
        return False
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError):
        return False
    expected = {
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
    return bool(
        type(payload) is dict
        and payload.keys() == expected.keys()
        and all(_exact_value(payload[key], value) for key, value in expected.items())
    )


_FAILURE_STATE = tuple[bool, bool, bool, bool, bool, bool, bool]
_RECOGNIZED_METADATA_FAILURE_STATES: dict[str, tuple[_FAILURE_STATE, ...]] = {
    "missing_configuration": ((False, False, False, False, False, False, False),),
    "sdk_unavailable": (
        (True, False, False, False, False, False, False),
        (True, True, True, False, False, False, False),
    ),
    "not_running_in_hosted_environment": (
        (True, False, False, False, False, False, False),
    ),
    "managed_identity_unavailable": (
        (True, True, True, False, False, False, False),
    ),
    "authentication_or_authorization_failed": (
        (True, True, True, False, False, False, False),
        (True, True, True, True, True, True, False),
    ),
    "project_access_failed": (
        (True, True, True, False, False, False, False),
    ),
    "agent_not_found": (
        (True, True, True, True, True, False, False),
    ),
    "configured_version_not_found": (
        (True, True, True, True, True, True, False),
    ),
    "agent_contract_invalid": (
        (True, True, True, True, True, True, True),
    ),
    "azure_request_failed": (
        (True, True, True, False, False, False, False),
        (True, True, True, True, True, True, False),
        (True, True, True, True, True, True, True),
    ),
    "response_parse_failed": (
        (True, True, True, False, False, False, False),
        (True, True, True, True, True, False, False),
        (True, True, True, True, True, True, False),
    ),
    "unexpected_error": (
        (True, True, True, False, False, False, False),
    ),
}


def _recognized_metadata_verification_failure(
    result: RemoteCommandResult,
) -> tuple[str, bool] | None:
    if (
        type(result.return_code) is not int
        or result.return_code not in {1, 2}
        or result.stderr != ""
        or not _one_json_document(result.stdout)
    ):
        return None
    try:
        payload = json.loads(result.stdout)
    except (TypeError, ValueError):
        return None
    if type(payload) is not dict:
        return None
    category = payload.get("category")
    if type(category) is not str:
        return None
    states = _RECOGNIZED_METADATA_FAILURE_STATES.get(category)
    if states is None:
        return None
    for state in states:
        (
            local_contract_validated,
            hosted_environment_present,
            managed_identity_attempted,
            managed_identity_authenticated,
            project_access_verified,
            agent_present,
            configured_version_present,
        ) = state
        expected = HostedFoundryAgentVerificationResult.failure(
            "live",
            category,
            local_contract_validated=local_contract_validated,
            hosted_environment_present=hosted_environment_present,
            managed_identity_attempted=managed_identity_attempted,
            managed_identity_authenticated=managed_identity_authenticated,
            project_access_verified=project_access_verified,
            agent_present=agent_present,
            configured_version_present=configured_version_present,
        ).to_json_dict()
        expected_return_code = (
            2
            if category
            in {
                "missing_configuration",
                "sdk_unavailable",
                "not_running_in_hosted_environment",
            }
            else 1
        )
        if (
            result.return_code == expected_return_code
            and payload.keys() == expected.keys()
            and all(
                _exact_value(payload[key], value)
                for key, value in expected.items()
            )
        ):
            return category, managed_identity_attempted
    return None


def _exact_value(observed: object, expected: object) -> bool:
    if type(expected) is bool:
        return observed is expected
    return type(observed) is type(expected) and observed == expected


def _cleanup(
    process: ProcessLike | None,
    output_observer: TunnelOutputObserver | None,
    known_hosts_path: str | None,
    deps: HostedFoundryAgentSshTransportDependencies,
) -> dict[str, bool]:
    evidence = {
        "tunnel_interrupt_sent": False,
        "tunnel_terminate_sent": False,
        "tunnel_kill_sent": False,
        "tunnel_process_reaped": False,
        "private_known_hosts_removed": False,
    }
    if process is not None:
        active = True
        try:
            active = process.poll() is None
        except BaseException:
            pass
        if active:
            try:
                deps.send_interrupt(process)
                evidence["tunnel_interrupt_sent"] = True
            except BaseException:
                pass
        if not _bounded_reap(process):
            try:
                deps.terminate(process)
                evidence["tunnel_terminate_sent"] = True
            except BaseException:
                pass
            if not _bounded_reap(process):
                try:
                    deps.kill(process)
                    evidence["tunnel_kill_sent"] = True
                except BaseException:
                    pass
                evidence["tunnel_process_reaped"] = _reap_after_kill(process)
            else:
                evidence["tunnel_process_reaped"] = True
        else:
            evidence["tunnel_process_reaped"] = True
    if output_observer is not None:
        try:
            output_observer.close()
        except BaseException:
            pass
    if known_hosts_path is not None:
        try:
            deps.remove_known_hosts(known_hosts_path)
            evidence["private_known_hosts_removed"] = True
        except BaseException:
            pass
    return evidence


def _bounded_reap(process: ProcessLike) -> bool:
    try:
        process.wait(CLEANUP_WAIT_SECONDS)
        return True
    except (subprocess.TimeoutExpired, TimeoutError, InterruptedError):
        return False
    except BaseException:
        return False


def _reap_after_kill(process: ProcessLike) -> bool:
    while True:
        try:
            process.wait(None)
            return True
        except BaseException:
            try:
                if process.poll() is not None:
                    return True
            except BaseException:
                pass


class _TransportInterrupted(Exception):
    pass


class _SignalInterruptionGuard:
    def __init__(self) -> None:
        self._phase = "constructing"
        self._pending = False

    def receive(self) -> None:
        self._pending = True
        if self._phase == "running":
            raise _TransportInterrupted

    def raise_if_pending(self) -> None:
        if self._pending:
            raise _TransportInterrupted

    def arm(self) -> None:
        self._phase = "running"
        self.raise_if_pending()

    def begin_cleanup(self) -> None:
        self._phase = "cleanup"


@contextmanager
def _temporary_signal_handlers():
    guard = _SignalInterruptionGuard()
    if threading.current_thread() is not threading.main_thread():
        yield guard
        return
    previous = {
        number: signal.getsignal(number)
        for number in (signal.SIGINT, signal.SIGTERM)
    }

    def interrupt(_number, _frame):
        guard.receive()

    try:
        for number in previous:
            signal.signal(number, interrupt)
        yield guard
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


class _PrivateTunnelOutputObserver:
    """Drain tunnel output into booleans without retaining any raw line."""

    def __init__(self, process: ProcessLike) -> None:
        self._ready = threading.Event()
        self._failed = threading.Event()
        self._streams = tuple(
            stream
            for stream in (process.stdout, process.stderr)
            if stream is not None
        )
        self._threads = tuple(
            threading.Thread(
                target=self._drain,
                args=(stream,),
                daemon=True,
                name="nia-private-tunnel-output-drain",
            )
            for stream in self._streams
        )
        for thread in self._threads:
            thread.start()

    def _drain(self, stream: object) -> None:
        try:
            while True:
                line = stream.readline()
                if line == "":
                    return
                if _TUNNEL_READY_MARKER in line:
                    self._ready.set()
                folded = line.casefold()
                if any(marker in folded for marker in _TUNNEL_FAILURE_MARKERS):
                    self._failed.set()
        except BaseException:
            self._failed.set()

    def ready(self) -> bool:
        return self._ready.is_set()

    def failed(self) -> bool:
        return self._failed.is_set()

    def close(self) -> None:
        for stream in self._streams:
            try:
                stream.close()
            except BaseException:
                pass
        for thread in self._threads:
            thread.join(CLEANUP_WAIT_SECONDS)


def _default_dependencies() -> HostedFoundryAgentSshTransportDependencies:
    return HostedFoundryAgentSshTransportDependencies(
        process_factory=_start_tunnel_process,
        port_available=_port_available,
        tunnel_ready=_tunnel_ready,
        monotonic=time.monotonic,
        sleep=time.sleep,
        ssh_runner=_SystemSshRunner(),
        observe_tunnel_output=_PrivateTunnelOutputObserver,
        create_known_hosts=_create_private_known_hosts,
        remove_known_hosts=_remove_private_known_hosts,
        send_interrupt=lambda process: _signal_process(process, signal.SIGINT),
        terminate=lambda process: _signal_process(process, signal.SIGTERM),
        kill=lambda process: _signal_process(process, signal.SIGKILL),
        install_signal_handlers=True,
    )


def _start_tunnel_process(args: tuple[str, ...]) -> ProcessLike:
    return subprocess.Popen(
        list(args),
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=os.name == "posix",
    )


def _port_available(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
            candidate.bind((host, port))
        return True
    except OSError:
        return False


def _tunnel_ready(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.2):
            return True
    except OSError:
        return False


class _SystemSshRunner:
    def run(
        self,
        args: tuple[str, ...],
        timeout_seconds: float,
    ) -> RemoteCommandResult:
        try:
            completed = subprocess.run(
                list(args),
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return RemoteCommandResult(124, "", "")
        return RemoteCommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


def _create_private_known_hosts() -> str:
    descriptor, path = tempfile.mkstemp(prefix="nia-ssh-known-hosts-")
    try:
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return path


def _remove_private_known_hosts(path: str) -> None:
    Path(path).unlink(missing_ok=True)


def _signal_process(process: ProcessLike, signal_number: int) -> None:
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal_number)
        else:
            os.kill(process.pid, signal_number)
    except (OSError, ProcessLookupError):
        pass
