"""Owned lifecycle for a future supervised App Service TCP/SSH transport."""

from __future__ import annotations

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


TransportMode = Literal["check", "live-tunnel"]
TransportCategory = Literal[
    "check_passed",
    "success",
    "configuration_invalid",
    "cli_unsupported",
    "approval_denied",
    "port_unavailable",
    "tunnel_start_failed",
    "tunnel_unavailable",
    "tunnel_outcome_ambiguous",
    "interpreter_probe_failed",
    "module_probe_failed",
    "remote_check_failed",
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
PERMITTED_REMOTE_COMMANDS = (
    INTERPRETER_PROBE_COMMAND,
    MODULE_PROBE_COMMAND,
    REMOTE_CHECK_COMMAND,
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


@dataclass(frozen=True)
class HostedFoundryAgentSshTransportApprovals:
    approve_tunnel: Callable[[], bool]
    approve_probes: Callable[[], bool]
    approve_remote_check: Callable[[], bool]


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

    @classmethod
    def build(
        cls,
        *,
        ok: bool,
        category: TransportCategory,
        mode: str,
        **progress: bool,
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
            mode=mode if mode in {"check", "live-tunnel"} else "invalid",
            transport=TRANSPORT,
            **values,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
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


def build_ssh_command(command: str, known_hosts_path: str) -> tuple[str, ...]:
    if command not in PERMITTED_REMOTE_COMMANDS:
        raise ValueError("unsupported remote command")
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
    """Own exactly one tunnel process and three immutable remote commands."""

    def __init__(
        self,
        *,
        help_reader: Callable[[], AzureCliHelpSurface | None] | None = None,
    ) -> None:
        self._help_reader = help_reader or InstalledAzureCliHelpReader().read

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
        if not _request_valid(request, expected_mode="live-tunnel"):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="configuration_invalid",
                mode=request.mode,
            )
        if not self._cli_contract_valid() or not _fixed_contract_valid(request):
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="cli_unsupported",
                mode="live-tunnel",
            )
        progress = {
            "cli_help_contract_valid": True,
            "tunnel_command_valid": True,
            "remote_command_contract_valid": True,
            "sanitization_policy_valid": True,
            "cleanup_policy_valid": True,
        }
        try:
            if approvals.approve_tunnel() is not True:
                return HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="approval_denied",
                    mode="live-tunnel",
                    **progress,
                )
        except BaseException:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode="live-tunnel",
                **progress,
            )

        deps = dependencies or _default_dependencies()
        if deps.port_available(LOOPBACK_HOST, LOCAL_PORT) is not True:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="port_unavailable",
                mode="live-tunnel",
                **progress,
            )

        process: ProcessLike | None = None
        output_observer: TunnelOutputObserver | None = None
        known_hosts_path: str | None = None
        result = HostedFoundryAgentSshTransportResult.build(
            ok=False,
            category="unexpected_error",
            mode="live-tunnel",
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
                if not _observe_tunnel_ready(
                    process,
                    output_observer,
                    deadline,
                    deps,
                ):
                    category: TransportCategory = (
                        "tunnel_unavailable"
                        if process.poll() is not None or output_observer.failed()
                        else "tunnel_outcome_ambiguous"
                    )
                    result = HostedFoundryAgentSshTransportResult.build(
                        ok=False,
                        category=category,
                        mode="live-tunnel",
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
                    )
            except (KeyboardInterrupt, _TransportInterrupted):
                result = HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="interrupted",
                    mode="live-tunnel",
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
                    mode="live-tunnel",
                    **progress,
                )
            except BaseException:
                result = HostedFoundryAgentSshTransportResult.build(
                    ok=False,
                    category="unexpected_error",
                    mode="live-tunnel",
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
    ) -> HostedFoundryAgentSshTransportResult:
        if approvals.approve_probes() is not True:
            return HostedFoundryAgentSshTransportResult.build(
                ok=False,
                category="approval_denied",
                mode="live-tunnel",
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
                mode="live-tunnel",
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
                mode="live-tunnel",
                **progress,
            )
        progress["packaged_module_valid"] = True
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
        and len(PERMITTED_REMOTE_COMMANDS) == 3
        and PERMITTED_REMOTE_COMMANDS[-1].endswith("--check --json")
        and all("--live" not in remote for remote in PERMITTED_REMOTE_COMMANDS)
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
) -> bool:
    while deps.monotonic() < deadline:
        if process.poll() is not None:
            return False
        if output_observer.failed():
            return False
        if (
            output_observer.ready()
            and deps.tunnel_ready(LOOPBACK_HOST, LOCAL_PORT) is True
        ):
            return True
        remaining = deadline - deps.monotonic()
        if remaining <= 0:
            break
        deps.sleep(min(READINESS_INTERVAL_SECONDS, remaining))
    return False


def _run_ssh(
    deps: HostedFoundryAgentSshTransportDependencies,
    command: str,
    known_hosts_path: str,
    deadline: float,
) -> RemoteCommandResult:
    remaining = deadline - deps.monotonic()
    if remaining <= 0:
        return RemoteCommandResult(124, "", "")
    return deps.ssh_runner.run(
        build_ssh_command(command, known_hosts_path),
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
