import ast
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Literal, Protocol

from src.app.services.web_app_configuration_verification import (
    check_web_app_configuration_contract,
)
from src.app.services.web_app_hosting_contract import (
    HOSTED_VERIFIER_SETTING_NAMES,
)
from src.app.services.web_app_infra_deployment import (
    web_app_infrastructure_local_contract_valid,
)
from src.app.services.web_app_package import (
    HOSTED_VERIFIER_WEBJOB_ENTRYPOINT,
    PackageSafetyError,
    plan_web_app_package,
)


WEBJOB_NAME = "verify-hosted-foundry-agent"
DISCOVERY_QUERY = "[].{name:name}"
STATUS_QUERY = "[].runs[] | [].{status:status,start_time:startTime}"
TRIGGER_STATE_DIRECTORY = Path(".artifacts/hosted-foundry-agent-webjob")
TRIGGER_RECEIPT_RELATIVE_PATH = TRIGGER_STATE_DIRECTORY / "accepted-trigger.json"
TRIGGER_BLOCKED_RELATIVE_PATH = TRIGGER_STATE_DIRECTORY / "blocked-trigger.json"
TERMINAL_OUTCOME_RELATIVE_PATH = TRIGGER_STATE_DIRECTORY / "terminal-outcome.json"
TRIGGER_RESERVATION_RELATIVE_PATH = TRIGGER_STATE_DIRECTORY / "trigger-reservation.lock"
TRIGGER_RECEIPT_SCHEMA_VERSION = 1
TRIGGER_BLOCKED_SCHEMA_VERSION = 1
TERMINAL_OUTCOME_SCHEMA_VERSION = 1
WebJobMode = Literal["check", "live-discover", "live-trigger", "live-status"]
WebJobCategory = Literal[
    "success",
    "invalid_arguments",
    "local_contract_invalid",
    "azure_cli_unavailable",
    "authentication_or_authorization_failed",
    "azure_request_failed",
    "response_parse_failed",
    "remote_webjob_missing",
    "remote_webjob_ambiguous",
    "trigger_receipt_missing",
    "trigger_receipt_invalid",
    "trigger_receipt_unresolved",
    "trigger_receipt_persistence_failed",
    "trigger_acceptance_ambiguous",
    "trigger_reservation_active",
    "trigger_blocked",
    "trigger_lifecycle_critical",
    "terminal_outcome_invalid",
    "terminal_outcome_conflict",
    "terminal_outcome_persistence_failed",
    "correlated_run_not_observed",
    "correlated_run_ambiguous",
    "correlated_run_nonterminal",
    "correlated_run_failed",
    "unexpected_error",
]


MESSAGES: dict[WebJobCategory, str] = {
    "success": "The hosted verifier WebJob boundary completed its requested stage.",
    "invalid_arguments": "The WebJob execution arguments are invalid.",
    "local_contract_invalid": "The local hosted verifier WebJob contract is invalid.",
    "azure_cli_unavailable": "Azure CLI is unavailable.",
    "authentication_or_authorization_failed": (
        "Azure authentication or authorization failed."
    ),
    "azure_request_failed": "The Azure WebJob request failed.",
    "response_parse_failed": "The WebJob response was not safely usable.",
    "remote_webjob_missing": "The fixed triggered WebJob was not discovered.",
    "remote_webjob_ambiguous": "The fixed triggered WebJob discovery was ambiguous.",
    "trigger_receipt_missing": "No current trigger receipt is available.",
    "trigger_receipt_invalid": "The current trigger receipt is invalid.",
    "trigger_receipt_unresolved": "A prior trigger receipt is still unresolved.",
    "trigger_receipt_persistence_failed": (
        "The trigger correlation receipt could not be persisted safely."
    ),
    "trigger_acceptance_ambiguous": (
        "The trigger request may have been accepted without a validated response."
    ),
    "trigger_reservation_active": "Another local trigger lifecycle is reserved.",
    "trigger_blocked": "A prior trigger may have been accepted without usable correlation evidence.",
    "trigger_lifecycle_critical": "Trigger lifecycle evidence could not be made durable safely.",
    "terminal_outcome_invalid": "The terminal WebJob outcome evidence is invalid.",
    "terminal_outcome_conflict": "The terminal WebJob outcome evidence conflicts.",
    "terminal_outcome_persistence_failed": "The terminal WebJob outcome could not be persisted safely.",
    "correlated_run_not_observed": "The correlated WebJob run is not yet observable.",
    "correlated_run_ambiguous": "The correlated WebJob execution is ambiguous.",
    "correlated_run_nonterminal": "The correlated WebJob run is not terminal.",
    "correlated_run_failed": "The correlated WebJob run did not succeed.",
    "unexpected_error": "The WebJob boundary did not complete.",
}

NEXT_STEPS: dict[WebJobCategory, str] = {
    "success": "Review the sanitized result before the next separately approved stage.",
    "invalid_arguments": "Supply the exact approved resource group and Web App names.",
    "local_contract_invalid": "Restore the repository-owned WebJob, package, and configuration contracts.",
    "azure_cli_unavailable": "Install Azure CLI before an explicitly authorized live stage.",
    "authentication_or_authorization_failed": "Confirm the approved operator account before a new attempt.",
    "azure_request_failed": "Review the sanitized category before a new explicit request.",
    "response_parse_failed": "Stop and review the current Azure CLI response contract.",
    "remote_webjob_missing": "Stop until the fixed triggered WebJob is deployed and discoverable.",
    "remote_webjob_ambiguous": "Stop; do not infer which remote WebJob is authoritative.",
    "trigger_receipt_missing": "Stop until one explicitly authorized trigger has a local receipt.",
    "trigger_receipt_invalid": "Stop and restore the repository-owned trigger correlation contract.",
    "trigger_receipt_unresolved": "Resolve the prior trigger through a separate status stage before triggering again.",
    "trigger_receipt_persistence_failed": "Do not trigger again; execution may have been requested without usable correlation evidence.",
    "trigger_acceptance_ambiguous": "Stop and investigate the blocked trigger; do not retry automatically.",
    "trigger_reservation_active": "Stop and investigate the existing local trigger reservation; do not retry or remove it automatically.",
    "trigger_blocked": "Stop and investigate the accepted but uncorrelatable trigger before any future trigger.",
    "trigger_lifecycle_critical": "Stop immediately; execution may have been requested and the remaining reservation must be investigated manually.",
    "terminal_outcome_invalid": "Stop and restore the immutable terminal-outcome contract before another status read.",
    "terminal_outcome_conflict": "Stop; do not replace or infer between conflicting terminal outcomes.",
    "terminal_outcome_persistence_failed": "Stop; preserve the accepted receipt and investigate outcome persistence before another stage.",
    "correlated_run_not_observed": "Stop; a later status read requires separate authorization.",
    "correlated_run_ambiguous": "Stop; do not infer which execution is authoritative.",
    "correlated_run_nonterminal": "Stop; a later status read requires separate authorization.",
    "correlated_run_failed": "Review the fail-closed WebJob outcome without retrying automatically.",
    "unexpected_error": "Review the local contract and sanitized category.",
}


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class AzureCliProcessNotStarted(Exception):
    """Proves that local process creation failed before Azure CLI could run."""


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class HostedFoundryAgentWebJobExecutionRequest:
    mode: str
    resource_group: str
    web_app_name: str
    source_root: Path


@dataclass(frozen=True)
class TriggerReceipt:
    schema_version: int
    state: Literal["accepted"]
    trigger_not_before: datetime
    resource_group: str
    web_app_name: str
    webjob_name: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "trigger_not_before": _format_utc(self.trigger_not_before),
            "resource_group": self.resource_group,
            "web_app_name": self.web_app_name,
            "webjob_name": self.webjob_name,
        }


class TriggerReceiptError(Exception):
    pass


class ImmutableLifecycleStateExists(TriggerReceiptError):
    pass


@dataclass(frozen=True)
class BlockedTrigger:
    schema_version: int
    state: Literal["accepted-uncorrelatable"]
    trigger_not_before: datetime
    resource_group: str
    web_app_name: str
    webjob_name: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "trigger_not_before": _format_utc(self.trigger_not_before),
            "resource_group": self.resource_group,
            "web_app_name": self.web_app_name,
            "webjob_name": self.webjob_name,
        }


@dataclass(frozen=True)
class TerminalOutcome:
    schema_version: int
    state: Literal["terminal-success", "terminal-failure"]
    trigger_not_before: datetime
    resource_group: str
    web_app_name: str
    webjob_name: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "state": self.state,
            "trigger_not_before": _format_utc(self.trigger_not_before),
            "resource_group": self.resource_group,
            "web_app_name": self.web_app_name,
            "webjob_name": self.webjob_name,
        }


@dataclass(frozen=True)
class TriggerReservation:
    device: int
    inode: int


class TriggerReceiptStore(Protocol):
    def acquire_reservation(self) -> TriggerReservation | None: ...

    def release_reservation(self, reservation: TriggerReservation) -> None: ...

    def reservation_exists(self) -> bool: ...

    def read(self) -> TriggerReceipt | None: ...

    def write(self, receipt: TriggerReceipt) -> None: ...

    def read_blocked(self) -> BlockedTrigger | None: ...

    def write_blocked(self, blocked: BlockedTrigger) -> None: ...

    def read_outcome(self) -> TerminalOutcome | None: ...

    def write_outcome(self, outcome: TerminalOutcome) -> None: ...


class FileTriggerReceiptStore:
    def __init__(self, source_root: Path) -> None:
        self._source_root = source_root

    @staticmethod
    def _directory_flags() -> int:
        required = ("O_DIRECTORY", "O_NOFOLLOW")
        if any(not hasattr(os, name) for name in required):
            raise TriggerReceiptError()
        return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)

    def _open_state_directory(self, *, create: bool) -> int:
        descriptor: int | None = None
        try:
            descriptor = os.open(self._source_root, self._directory_flags())
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise TriggerReceiptError()
            for part in TRIGGER_STATE_DIRECTORY.parts:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                next_descriptor = os.open(
                    part,
                    self._directory_flags(),
                    dir_fd=descriptor,
                )
                os.close(descriptor)
                descriptor = next_descriptor
            return descriptor
        except FileNotFoundError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except TriggerReceiptError:
            if descriptor is not None:
                os.close(descriptor)
            raise
        except Exception as error:
            if descriptor is not None:
                os.close(descriptor)
            raise TriggerReceiptError() from error

    @staticmethod
    def _read_json_file(directory: int, name: str) -> object | None:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory,
            )
        except FileNotFoundError:
            return None
        except Exception as error:
            raise TriggerReceiptError() from error
        try:
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_size > 16384:
                raise TriggerReceiptError()
            chunks: list[bytes] = []
            remaining = 16385
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > 16384:
                raise TriggerReceiptError()
            return json.loads(payload.decode("utf-8"))
        except TriggerReceiptError:
            raise
        except Exception as error:
            raise TriggerReceiptError() from error
        finally:
            os.close(descriptor)

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise TriggerReceiptError()
            offset += written

    def _write_immutable(self, name: str, payload: dict[str, object]) -> None:
        directory = self._open_state_directory(create=True)
        temporary_name = f".lifecycle-{secrets.token_hex(16)}.tmp"
        temporary_descriptor: int | None = None
        try:
            serialized = json.dumps(
                payload, separators=(",", ":"), sort_keys=True
            ).encode("utf-8")
            temporary_descriptor = os.open(
                temporary_name,
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | os.O_NOFOLLOW
                | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=directory,
            )
            self._write_all(temporary_descriptor, serialized)
            os.fsync(temporary_descriptor)
            os.close(temporary_descriptor)
            temporary_descriptor = None
            try:
                os.link(
                    temporary_name,
                    name,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            except FileExistsError as error:
                raise ImmutableLifecycleStateExists() from error
            os.fsync(directory)
        except ImmutableLifecycleStateExists:
            raise
        except Exception as error:
            raise TriggerReceiptError() from error
        finally:
            if temporary_descriptor is not None:
                os.close(temporary_descriptor)
            try:
                os.unlink(temporary_name, dir_fd=directory)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            os.close(directory)

    def _read_state(self, name: str) -> object | None:
        try:
            directory = self._open_state_directory(create=False)
        except FileNotFoundError:
            return None
        try:
            return self._read_json_file(directory, name)
        finally:
            os.close(directory)

    @staticmethod
    def _regular_file_exists(directory: int, name: str) -> bool:
        descriptor: int | None = None
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY
                | os.O_NOFOLLOW
                | os.O_NONBLOCK
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory,
            )
        except FileNotFoundError:
            return False
        except Exception as error:
            raise TriggerReceiptError() from error
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise TriggerReceiptError()
            return True
        finally:
            os.close(descriptor)

    def read(self) -> TriggerReceipt | None:
        payload = self._read_state(TRIGGER_RECEIPT_RELATIVE_PATH.name)
        if payload is None:
            return None
        receipt = _parse_receipt(payload)
        if receipt is None:
            raise TriggerReceiptError()
        return receipt

    def write(self, receipt: TriggerReceipt) -> None:
        self._write_immutable(
            TRIGGER_RECEIPT_RELATIVE_PATH.name,
            receipt.to_json_dict(),
        )

    def read_blocked(self) -> BlockedTrigger | None:
        payload = self._read_state(TRIGGER_BLOCKED_RELATIVE_PATH.name)
        if payload is None:
            return None
        blocked = _parse_blocked(payload)
        if blocked is None:
            raise TriggerReceiptError()
        return blocked

    def write_blocked(self, blocked: BlockedTrigger) -> None:
        self._write_immutable(
            TRIGGER_BLOCKED_RELATIVE_PATH.name,
            blocked.to_json_dict(),
        )

    def read_outcome(self) -> TerminalOutcome | None:
        payload = self._read_state(TERMINAL_OUTCOME_RELATIVE_PATH.name)
        if payload is None:
            return None
        outcome = _parse_outcome(payload)
        if outcome is None:
            raise TriggerReceiptError()
        return outcome

    def write_outcome(self, outcome: TerminalOutcome) -> None:
        self._write_immutable(
            TERMINAL_OUTCOME_RELATIVE_PATH.name,
            outcome.to_json_dict(),
        )

    def reservation_exists(self) -> bool:
        try:
            directory = self._open_state_directory(create=False)
        except FileNotFoundError:
            return False
        try:
            return self._regular_file_exists(
                directory, TRIGGER_RESERVATION_RELATIVE_PATH.name
            )
        finally:
            os.close(directory)

    def acquire_reservation(self) -> TriggerReservation | None:
        directory = self._open_state_directory(create=True)
        descriptor: int | None = None
        try:
            try:
                descriptor = os.open(
                    TRIGGER_RESERVATION_RELATIVE_PATH.name,
                    os.O_WRONLY
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    0o600,
                    dir_fd=directory,
                )
            except FileExistsError:
                if not self.reservation_exists():
                    raise TriggerReceiptError()
                return None
            self._write_all(
                descriptor,
                b'{"schema_version":1,"state":"in-progress"}',
            )
            os.fsync(descriptor)
            details = os.fstat(descriptor)
            os.fsync(directory)
            return TriggerReservation(details.st_dev, details.st_ino)
        except Exception as error:
            raise TriggerReceiptError() from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            os.close(directory)

    def release_reservation(self, reservation: TriggerReservation) -> None:
        directory = self._open_state_directory(create=False)
        try:
            details = os.stat(
                TRIGGER_RESERVATION_RELATIVE_PATH.name,
                dir_fd=directory,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(details.st_mode)
                or details.st_dev != reservation.device
                or details.st_ino != reservation.inode
            ):
                raise TriggerReceiptError()
            os.unlink(TRIGGER_RESERVATION_RELATIVE_PATH.name, dir_fd=directory)
            os.fsync(directory)
        except Exception as error:
            raise TriggerReceiptError() from error
        finally:
            os.close(directory)


@dataclass(frozen=True)
class HostedFoundryAgentWebJobExecutionResult:
    ok: bool
    mode: str
    category: WebJobCategory
    message: str
    local_entrypoint_present: bool
    remote_webjob_discovered: bool
    configuration_contract_valid: bool
    package_contract_valid: bool
    azure_operation_attempted: bool
    trigger_request_accepted: bool
    trigger_reservation_active: bool
    trigger_receipt_valid: bool
    trigger_blocked: bool
    correlated_run_observed: bool
    correlated_run_terminal: bool
    correlated_run_succeeded: bool
    terminal_outcome_recorded: bool
    metadata_verification_proven: bool
    invocation_attempted: bool
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "category": self.category,
            "message": self.message,
            "local_entrypoint_present": self.local_entrypoint_present,
            "remote_webjob_discovered": self.remote_webjob_discovered,
            "configuration_contract_valid": self.configuration_contract_valid,
            "package_contract_valid": self.package_contract_valid,
            "azure_operation_attempted": self.azure_operation_attempted,
            "trigger_request_accepted": self.trigger_request_accepted,
            "trigger_reservation_active": self.trigger_reservation_active,
            "trigger_receipt_valid": self.trigger_receipt_valid,
            "trigger_blocked": self.trigger_blocked,
            "correlated_run_observed": self.correlated_run_observed,
            "correlated_run_terminal": self.correlated_run_terminal,
            "correlated_run_succeeded": self.correlated_run_succeeded,
            "terminal_outcome_recorded": self.terminal_outcome_recorded,
            "metadata_verification_proven": self.metadata_verification_proven,
            "invocation_attempted": self.invocation_attempted,
            "recommended_next_step": self.recommended_next_step,
        }


def _result(
    request: HostedFoundryAgentWebJobExecutionRequest,
    category: WebJobCategory,
    *,
    ok: bool = False,
    local_entrypoint_present: bool = False,
    remote_webjob_discovered: bool = False,
    configuration_contract_valid: bool = False,
    package_contract_valid: bool = False,
    azure_operation_attempted: bool = False,
    trigger_request_accepted: bool = False,
    trigger_reservation_active: bool = False,
    trigger_receipt_valid: bool = False,
    trigger_blocked: bool = False,
    correlated_run_observed: bool = False,
    correlated_run_terminal: bool = False,
    correlated_run_succeeded: bool = False,
    terminal_outcome_recorded: bool = False,
    metadata_verification_proven: bool = False,
    recommended_next_step: str | None = None,
) -> HostedFoundryAgentWebJobExecutionResult:
    valid_modes = {"check", "live-discover", "live-trigger", "live-status"}
    return HostedFoundryAgentWebJobExecutionResult(
        ok=ok,
        mode=request.mode if request.mode in valid_modes else "invalid",
        category=category,
        message=MESSAGES[category],
        local_entrypoint_present=local_entrypoint_present,
        remote_webjob_discovered=remote_webjob_discovered,
        configuration_contract_valid=configuration_contract_valid,
        package_contract_valid=package_contract_valid,
        azure_operation_attempted=azure_operation_attempted,
        trigger_request_accepted=trigger_request_accepted,
        trigger_reservation_active=trigger_reservation_active,
        trigger_receipt_valid=trigger_receipt_valid,
        trigger_blocked=trigger_blocked,
        correlated_run_observed=correlated_run_observed,
        correlated_run_terminal=correlated_run_terminal,
        correlated_run_succeeded=correlated_run_succeeded,
        terminal_outcome_recorded=terminal_outcome_recorded,
        metadata_verification_proven=metadata_verification_proven,
        invocation_attempted=False,
        recommended_next_step=recommended_next_step or NEXT_STEPS[category],
    )


def _safe_resource_group(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and 1 <= len(value) <= 90
        and not value.endswith(".")
        and re.fullmatch(r"[A-Za-z0-9_.()\-]+", value)
    )


def _safe_web_app_name(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and 2 <= len(value) <= 60
        and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", value)
    )


def _entrypoint_contract_valid(source_root: Path) -> bool:
    path = source_root / HOSTED_VERIFIER_WEBJOB_ENTRYPOINT
    try:
        if path.is_symlink() or not path.is_file():
            return False
        source = path.read_text()
        tree = ast.parse(source)
    except (OSError, SyntaxError, UnicodeError):
        return False
    if any(
        forbidden in source
        for forbidden in (
            "invoke_hosted_foundry_agent",
            "WEBJOBS_PATH",
            "Path(__file__)",
            "sys.argv",
        )
    ):
        return False
    if not all(
        marker in source
        for marker in (
            'os.environ.get("HOME")',
            '"site" / "wwwroot"',
            "src/app/operations/verify_hosted_foundry_agent.py",
        )
    ):
        return False
    imports_metadata_operation = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "src.app.operations"
        and [(alias.name, alias.asname) for alias in node.names]
        == [("verify_hosted_foundry_agent", None)]
        for node in ast.walk(tree)
    )
    fixed_call = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "verify_hosted_foundry_agent"
        and node.func.attr == "main"
        and not node.keywords
        and len(node.args) == 1
        and isinstance(node.args[0], ast.List)
        and [
            element.value
            for element in node.args[0].elts
            if isinstance(element, ast.Constant)
        ]
        == ["--live", "--json"]
        and len(node.args[0].elts) == 2
        for node in ast.walk(tree)
    )
    return imports_metadata_operation and fixed_call


def _hosted_sdk_imports_lazy(source_root: Path) -> bool:
    path = source_root / "src/app/services/hosted_foundry_agent_verification.py"
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeError):
        return False
    top_level_azure_import = any(
        (
            isinstance(node, ast.ImportFrom)
            and isinstance(node.module, str)
            and node.module.startswith("azure")
        )
        or (
            isinstance(node, ast.Import)
            and any(alias.name.startswith("azure") for alias in node.names)
        )
        for node in tree.body
    )
    nested_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and isinstance(node.module, str)
        and node.module.startswith("azure")
    }
    return not top_level_azure_import and {
        "azure.identity",
        "azure.ai.projects",
    } <= nested_modules


def _local_contract(
    request: HostedFoundryAgentWebJobExecutionRequest,
) -> tuple[bool, bool, bool]:
    local_entrypoint_present = _entrypoint_contract_valid(request.source_root)
    configuration_valid = bool(
        tuple(HOSTED_VERIFIER_SETTING_NAMES)
        == (
            "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
            "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
            "AZURE_AI_FOUNDRY_AGENT_NAME",
            "AZURE_AI_FOUNDRY_AGENT_VERSION",
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        )
        and check_web_app_configuration_contract().ok
        and web_app_infrastructure_local_contract_valid(
            request.source_root / "infra/main.bicep"
        )
    )
    try:
        package = plan_web_app_package(request.source_root)
        package_valid = (
            HOSTED_VERIFIER_WEBJOB_ENTRYPOINT in package.member_names
            and all(
                not name.startswith("App_Data/")
                or name == HOSTED_VERIFIER_WEBJOB_ENTRYPOINT
                for name in package.member_names
            )
        )
    except PackageSafetyError:
        package_valid = False
    package_valid = package_valid and _hosted_sdk_imports_lazy(request.source_root)
    return local_entrypoint_present, configuration_valid, package_valid


def _discovery_command(request: HostedFoundryAgentWebJobExecutionRequest) -> list[str]:
    return [
        "az",
        "webapp",
        "webjob",
        "triggered",
        "list",
        "--resource-group",
        request.resource_group,
        "--name",
        request.web_app_name,
        "--query",
        DISCOVERY_QUERY,
        "--only-show-errors",
        "--output",
        "json",
    ]


def _trigger_command(request: HostedFoundryAgentWebJobExecutionRequest) -> list[str]:
    return [
        "az",
        "webapp",
        "webjob",
        "triggered",
        "run",
        "--resource-group",
        request.resource_group,
        "--name",
        request.web_app_name,
        "--webjob-name",
        WEBJOB_NAME,
        "--only-show-errors",
        "--output",
        "json",
    ]


def _status_command(request: HostedFoundryAgentWebJobExecutionRequest) -> list[str]:
    return [
        "az",
        "webapp",
        "webjob",
        "triggered",
        "log",
        "--resource-group",
        request.resource_group,
        "--name",
        request.web_app_name,
        "--webjob-name",
        WEBJOB_NAME,
        "--query",
        STATUS_QUERY,
        "--only-show-errors",
        "--output",
        "json",
    ]


def _failure_category(outcome: CommandResult) -> WebJobCategory:
    if outcome.return_code == 127:
        return "azure_cli_unavailable"
    lowered = outcome.stderr.casefold()
    if any(
        marker in lowered
        for marker in (
            "az login",
            "authentication",
            "authorization",
            "unauthorized",
            "forbidden",
            "credential",
        )
    ):
        return "authentication_or_authorization_failed"
    return "azure_request_failed"


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _utc_time(value: datetime) -> datetime | None:
    if not isinstance(value, datetime) or value.tzinfo is None:
        return None
    try:
        utc = value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        return None
    return utc if value.utcoffset() == timezone.utc.utcoffset(value) else None


def _format_utc(value: datetime) -> str:
    utc = _utc_time(value)
    if utc is None:
        raise TriggerReceiptError()
    return utc.isoformat().replace("+00:00", "Z")


def _parse_receipt(payload: object) -> TriggerReceipt | None:
    expected = {
        "schema_version",
        "state",
        "trigger_not_before",
        "resource_group",
        "web_app_name",
        "webjob_name",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        return None
    started = _parse_time(payload.get("trigger_not_before"))
    if started is None or _utc_time(started) is None:
        return None
    if (
        payload.get("schema_version") != TRIGGER_RECEIPT_SCHEMA_VERSION
        or payload.get("state") != "accepted"
        or not _safe_resource_group(payload.get("resource_group"))
        or not _safe_web_app_name(payload.get("web_app_name"))
        or payload.get("webjob_name") != WEBJOB_NAME
    ):
        return None
    return TriggerReceipt(
        schema_version=TRIGGER_RECEIPT_SCHEMA_VERSION,
        state=payload["state"],
        trigger_not_before=started,
        resource_group=payload["resource_group"],
        web_app_name=payload["web_app_name"],
        webjob_name=WEBJOB_NAME,
    )


def _parse_blocked(payload: object) -> BlockedTrigger | None:
    receipt = _parse_local_context(
        payload,
        schema_version=TRIGGER_BLOCKED_SCHEMA_VERSION,
        states={"accepted-uncorrelatable"},
    )
    if receipt is None:
        return None
    return BlockedTrigger(
        schema_version=TRIGGER_BLOCKED_SCHEMA_VERSION,
        state="accepted-uncorrelatable",
        trigger_not_before=receipt[1],
        resource_group=receipt[2],
        web_app_name=receipt[3],
        webjob_name=WEBJOB_NAME,
    )


def _parse_outcome(payload: object) -> TerminalOutcome | None:
    outcome = _parse_local_context(
        payload,
        schema_version=TERMINAL_OUTCOME_SCHEMA_VERSION,
        states={"terminal-success", "terminal-failure"},
    )
    if outcome is None:
        return None
    return TerminalOutcome(
        schema_version=TERMINAL_OUTCOME_SCHEMA_VERSION,
        state=outcome[0],
        trigger_not_before=outcome[1],
        resource_group=outcome[2],
        web_app_name=outcome[3],
        webjob_name=WEBJOB_NAME,
    )


def _parse_local_context(
    payload: object,
    *,
    schema_version: int,
    states: set[str],
) -> tuple[str, datetime, str, str] | None:
    expected = {
        "schema_version",
        "state",
        "trigger_not_before",
        "resource_group",
        "web_app_name",
        "webjob_name",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        return None
    started = _parse_time(payload.get("trigger_not_before"))
    state = payload.get("state")
    resource_group = payload.get("resource_group")
    web_app_name = payload.get("web_app_name")
    if (
        payload.get("schema_version") != schema_version
        or not isinstance(state, str)
        or state not in states
        or started is None
        or _utc_time(started) is None
        or not _safe_resource_group(resource_group)
        or not _safe_web_app_name(web_app_name)
        or payload.get("webjob_name") != WEBJOB_NAME
    ):
        return None
    assert isinstance(resource_group, str)
    assert isinstance(web_app_name, str)
    return state, started, resource_group, web_app_name


def _same_context(
    receipt: TriggerReceipt,
    evidence: BlockedTrigger | TerminalOutcome,
) -> bool:
    return bool(
        receipt.trigger_not_before == evidence.trigger_not_before
        and receipt.resource_group == evidence.resource_group
        and receipt.web_app_name == evidence.web_app_name
        and receipt.webjob_name == evidence.webjob_name
    )


def _discovery_result(stdout: str) -> WebJobCategory:
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return "response_parse_failed"
    if not isinstance(payload, list):
        return "response_parse_failed"
    matches = 0
    for item in payload:
        if (
            not isinstance(item, dict)
            or set(item) != {"name"}
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
            or item["name"] != item["name"].strip()
        ):
            return "response_parse_failed"
        if item["name"] == WEBJOB_NAME:
            matches += 1
    if matches == 0:
        return "remote_webjob_missing"
    if matches != 1:
        return "remote_webjob_ambiguous"
    return "success"


def _correlated_status(
    stdout: str,
    lower_bound: datetime | None,
) -> tuple[WebJobCategory, bool, bool, bool]:
    if lower_bound is None or _utc_time(lower_bound) is None:
        return "trigger_receipt_invalid", False, False, False
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        return "response_parse_failed", False, False, False
    if not isinstance(payload, list):
        return "response_parse_failed", False, False, False

    eligible: list[tuple[datetime, str]] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"status", "start_time"}:
            return "response_parse_failed", False, False, False
        status = item.get("status")
        started = _parse_time(item.get("start_time"))
        if not isinstance(status, str) or not status or started is None:
            return "response_parse_failed", False, False, False
        if status not in {"Success", "Failed", "Error", "Aborted", "Running"}:
            return "response_parse_failed", False, False, False
        if started >= lower_bound:
            eligible.append((started, status))

    if not eligible:
        return "correlated_run_not_observed", False, False, False
    if len(eligible) != 1:
        return "correlated_run_ambiguous", False, False, False
    status = eligible[0][1]
    if status == "Success":
        return "success", True, True, True
    if status in {"Failed", "Error", "Aborted"}:
        return "correlated_run_failed", True, True, False
    return "correlated_run_nonterminal", True, False, False


def _receipt_for_request(
    store: TriggerReceiptStore,
    request: HostedFoundryAgentWebJobExecutionRequest,
) -> tuple[TriggerReceipt | None, TerminalOutcome | None, WebJobCategory | None]:
    try:
        if store.reservation_exists():
            return None, None, "trigger_reservation_active"
        blocked = store.read_blocked()
        if blocked is not None:
            return None, None, "trigger_blocked"
        receipt = store.read()
        outcome = store.read_outcome()
    except Exception:
        return None, None, "trigger_receipt_invalid"
    if receipt is None:
        if outcome is not None:
            return None, None, "terminal_outcome_invalid"
        return None, None, "trigger_receipt_missing"
    if (
        receipt.schema_version != TRIGGER_RECEIPT_SCHEMA_VERSION
        or receipt.state != "accepted"
        or receipt.resource_group != request.resource_group
        or receipt.web_app_name != request.web_app_name
        or receipt.webjob_name != WEBJOB_NAME
        or _utc_time(receipt.trigger_not_before) is None
    ):
        return None, None, "trigger_receipt_invalid"
    if outcome is not None and not _same_context(receipt, outcome):
        return None, None, "terminal_outcome_invalid"
    return receipt, outcome, None


def _release_reservation(
    store: TriggerReceiptStore,
    reservation: TriggerReservation,
) -> bool:
    try:
        store.release_reservation(reservation)
    except Exception:
        return False
    return True


def _new_blocked(
    request: HostedFoundryAgentWebJobExecutionRequest,
    lower_bound: datetime,
) -> BlockedTrigger:
    return BlockedTrigger(
        schema_version=TRIGGER_BLOCKED_SCHEMA_VERSION,
        state="accepted-uncorrelatable",
        trigger_not_before=lower_bound,
        resource_group=request.resource_group,
        web_app_name=request.web_app_name,
        webjob_name=WEBJOB_NAME,
    )


def _trigger_acceptance_response_valid(stdout: object) -> bool:
    if not isinstance(stdout, str) or not stdout:
        return False
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        return False
    return isinstance(payload, dict) and not payload


def _record_ambiguous_trigger(
    store: TriggerReceiptStore,
    reservation: TriggerReservation,
    request: HostedFoundryAgentWebJobExecutionRequest,
    lower_bound: datetime,
    common: dict[str, bool],
) -> HostedFoundryAgentWebJobExecutionResult:
    try:
        store.write_blocked(_new_blocked(request, lower_bound))
    except Exception:
        return _result(
            request,
            "trigger_lifecycle_critical",
            azure_operation_attempted=True,
            trigger_reservation_active=True,
            **common,
        )
    if not _release_reservation(store, reservation):
        return _result(
            request,
            "trigger_lifecycle_critical",
            azure_operation_attempted=True,
            trigger_reservation_active=True,
            trigger_blocked=True,
            **common,
        )
    return _result(
        request,
        "trigger_acceptance_ambiguous",
        azure_operation_attempted=True,
        trigger_blocked=True,
        **common,
    )


def _persisted_outcome_matches(
    store: TriggerReceiptStore,
    expected: TerminalOutcome,
) -> bool:
    try:
        return store.read_outcome() == expected
    except Exception:
        return False


def _get_runner(
    runner: AzureCliRunner | None,
    runner_factory: Callable[[], AzureCliRunner] | None,
) -> AzureCliRunner | None:
    if runner is not None:
        return runner
    if runner_factory is None:
        return None
    try:
        return runner_factory()
    except Exception:
        return None


def execute_hosted_foundry_agent_webjob(
    request: HostedFoundryAgentWebJobExecutionRequest,
    *,
    runner: AzureCliRunner | None = None,
    runner_factory: Callable[[], AzureCliRunner] | None = None,
    receipt_store: TriggerReceiptStore | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> HostedFoundryAgentWebJobExecutionResult:
    valid_modes = {"check", "live-discover", "live-trigger", "live-status"}
    if (
        request.mode not in valid_modes
        or not _safe_resource_group(request.resource_group)
        or not _safe_web_app_name(request.web_app_name)
    ):
        return _result(request, "invalid_arguments")

    local_entrypoint, configuration_valid, package_valid = _local_contract(request)
    common = {
        "local_entrypoint_present": local_entrypoint,
        "configuration_contract_valid": configuration_valid,
        "package_contract_valid": package_valid,
    }
    if not all(common.values()):
        return _result(request, "local_contract_invalid", **common)
    if request.mode == "check":
        return _result(request, "success", ok=True, **common)

    store = receipt_store or FileTriggerReceiptStore(request.source_root)
    receipt: TriggerReceipt | None = None
    existing_outcome: TerminalOutcome | None = None
    reservation: TriggerReservation | None = None

    if request.mode == "live-trigger":
        try:
            reservation = store.acquire_reservation()
        except Exception:
            return _result(request, "trigger_receipt_invalid", **common)
        if reservation is None:
            return _result(
                request,
                "trigger_reservation_active",
                trigger_reservation_active=True,
                **common,
            )
        try:
            existing_receipt = store.read()
            blocked = store.read_blocked()
            existing_outcome = store.read_outcome()
        except Exception:
            return _result(
                request,
                "trigger_lifecycle_critical",
                trigger_reservation_active=True,
                **common,
            )
        if blocked is not None:
            if not _release_reservation(store, reservation):
                return _result(
                    request,
                    "trigger_lifecycle_critical",
                    trigger_reservation_active=True,
                    trigger_blocked=True,
                    **common,
                )
            return _result(request, "trigger_blocked", trigger_blocked=True, **common)
        if existing_outcome is not None and (
            existing_receipt is None
            or not _same_context(existing_receipt, existing_outcome)
        ):
            return _result(
                request,
                "trigger_lifecycle_critical",
                trigger_reservation_active=True,
                **common,
            )
        if existing_receipt is not None:
            valid_receipt = bool(
                existing_receipt.state == "accepted"
                and existing_receipt.resource_group == request.resource_group
                and existing_receipt.web_app_name == request.web_app_name
                and existing_receipt.webjob_name == WEBJOB_NAME
            )
            if not _release_reservation(store, reservation):
                return _result(
                    request,
                    "trigger_lifecycle_critical",
                    trigger_reservation_active=True,
                    trigger_receipt_valid=valid_receipt,
                    terminal_outcome_recorded=existing_outcome is not None,
                    **common,
                )
            return _result(
                request,
                "trigger_receipt_unresolved" if valid_receipt else "trigger_receipt_invalid",
                trigger_receipt_valid=valid_receipt,
                terminal_outcome_recorded=existing_outcome is not None,
                **common,
            )
    elif request.mode == "live-status":
        receipt, existing_outcome, receipt_failure = _receipt_for_request(
            store, request
        )
        if receipt_failure is not None:
            return _result(
                request,
                receipt_failure,
                trigger_reservation_active=receipt_failure == "trigger_reservation_active",
                trigger_blocked=receipt_failure == "trigger_blocked",
                **common,
            )
        assert receipt is not None
        if existing_outcome is not None:
            succeeded = existing_outcome.state == "terminal-success"
            return _result(
                request,
                "success" if succeeded else "correlated_run_failed",
                ok=succeeded,
                trigger_receipt_valid=True,
                correlated_run_observed=True,
                correlated_run_terminal=True,
                correlated_run_succeeded=succeeded,
                terminal_outcome_recorded=True,
                metadata_verification_proven=succeeded,
                **common,
            )

    lower_bound: datetime | None = None
    if request.mode == "live-trigger":
        assert reservation is not None
        try:
            lower_bound = _utc_time(clock())
        except Exception:
            lower_bound = None
        if lower_bound is None:
            if not _release_reservation(store, reservation):
                return _result(
                    request,
                    "trigger_lifecycle_critical",
                    trigger_reservation_active=True,
                    **common,
                )
            return _result(request, "unexpected_error", **common)

    selected_runner = _get_runner(runner, runner_factory)
    if selected_runner is None:
        if reservation is not None and not _release_reservation(store, reservation):
            return _result(
                request,
                "trigger_lifecycle_critical",
                trigger_reservation_active=True,
                **common,
            )
        return _result(
            request,
            "unexpected_error",
            trigger_receipt_valid=receipt is not None,
            **common,
        )

    if request.mode == "live-discover":
        command = _discovery_command(request)
    elif request.mode == "live-trigger":
        command = _trigger_command(request)
    else:
        command = _status_command(request)

    try:
        outcome = selected_runner.run(command)
    except AzureCliProcessNotStarted:
        if reservation is not None:
            if not _release_reservation(store, reservation):
                return _result(
                    request,
                    "trigger_lifecycle_critical",
                    trigger_reservation_active=True,
                    **common,
                )
            return _result(request, "azure_cli_unavailable", **common)
        return _result(request, "azure_cli_unavailable", **common)
    except Exception:
        if reservation is not None:
            assert lower_bound is not None
            return _record_ambiguous_trigger(
                store,
                reservation,
                request,
                lower_bound,
                common,
            )
        return _result(
            request,
            "unexpected_error",
            azure_operation_attempted=True,
            trigger_receipt_valid=receipt is not None,
            **common,
        )
    if not isinstance(outcome, CommandResult):
        if reservation is not None:
            assert lower_bound is not None
            return _record_ambiguous_trigger(
                store,
                reservation,
                request,
                lower_bound,
                common,
            )
        return _result(
            request,
            "unexpected_error",
            azure_operation_attempted=True,
            trigger_receipt_valid=receipt is not None,
            **common,
        )
    if outcome.return_code != 0:
        if reservation is not None:
            assert lower_bound is not None
            return _record_ambiguous_trigger(
                store,
                reservation,
                request,
                lower_bound,
                common,
            )
        return _result(
            request,
            _failure_category(outcome),
            azure_operation_attempted=True,
            trigger_receipt_valid=receipt is not None,
            **common,
        )

    if request.mode == "live-discover":
        category = _discovery_result(outcome.stdout)
        return _result(
            request,
            category,
            ok=category == "success",
            remote_webjob_discovered=category == "success",
            azure_operation_attempted=True,
            **common,
        )

    if request.mode == "live-trigger":
        assert lower_bound is not None
        assert reservation is not None
        if not _trigger_acceptance_response_valid(outcome.stdout):
            return _record_ambiguous_trigger(
                store,
                reservation,
                request,
                lower_bound,
                common,
            )
        new_receipt = TriggerReceipt(
            schema_version=TRIGGER_RECEIPT_SCHEMA_VERSION,
            state="accepted",
            trigger_not_before=lower_bound,
            resource_group=request.resource_group,
            web_app_name=request.web_app_name,
            webjob_name=WEBJOB_NAME,
        )
        try:
            store.write(new_receipt)
        except Exception:
            blocked = _new_blocked(request, lower_bound)
            try:
                store.write_blocked(blocked)
            except Exception:
                return _result(
                    request,
                    "trigger_lifecycle_critical",
                    azure_operation_attempted=True,
                    trigger_request_accepted=True,
                    trigger_reservation_active=True,
                    **common,
                )
            if not _release_reservation(store, reservation):
                return _result(
                    request,
                    "trigger_lifecycle_critical",
                    azure_operation_attempted=True,
                    trigger_request_accepted=True,
                    trigger_reservation_active=True,
                    trigger_blocked=True,
                    **common,
                )
            return _result(
                request,
                "trigger_receipt_persistence_failed",
                azure_operation_attempted=True,
                trigger_request_accepted=True,
                trigger_blocked=True,
                **common,
            )
        if not _release_reservation(store, reservation):
            return _result(
                request,
                "trigger_lifecycle_critical",
                azure_operation_attempted=True,
                trigger_request_accepted=True,
                trigger_reservation_active=True,
                trigger_receipt_valid=True,
                **common,
            )
        return _result(
            request,
            "success",
            ok=True,
            azure_operation_attempted=True,
            trigger_request_accepted=True,
            trigger_receipt_valid=True,
            recommended_next_step=(
                "Trigger acceptance is not verification success; authorize one separate receipt-correlated status read."
            ),
            **common,
        )

    assert receipt is not None
    category, observed, terminal, succeeded = _correlated_status(
        outcome.stdout,
        receipt.trigger_not_before,
    )
    if terminal:
        terminal_outcome = TerminalOutcome(
            schema_version=TERMINAL_OUTCOME_SCHEMA_VERSION,
            state="terminal-success" if succeeded else "terminal-failure",
            trigger_not_before=receipt.trigger_not_before,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
            webjob_name=receipt.webjob_name,
        )
        try:
            store.write_outcome(terminal_outcome)
        except ImmutableLifecycleStateExists:
            if not _persisted_outcome_matches(store, terminal_outcome):
                try:
                    conflicting = store.read_outcome()
                except Exception:
                    conflicting = None
                return _result(
                    request,
                    "terminal_outcome_conflict"
                    if conflicting is not None
                    else "terminal_outcome_persistence_failed",
                    azure_operation_attempted=True,
                    trigger_receipt_valid=True,
                    correlated_run_observed=observed,
                    correlated_run_terminal=terminal,
                    **common,
                )
        except Exception:
            return _result(
                request,
                "terminal_outcome_persistence_failed",
                azure_operation_attempted=True,
                trigger_receipt_valid=True,
                correlated_run_observed=observed,
                correlated_run_terminal=terminal,
                **common,
            )
        return _result(
            request,
            category,
            ok=category == "success",
            azure_operation_attempted=True,
            trigger_receipt_valid=True,
            correlated_run_observed=observed,
            correlated_run_terminal=True,
            correlated_run_succeeded=succeeded,
            terminal_outcome_recorded=True,
            metadata_verification_proven=category == "success",
            **common,
        )
    return _result(
        request,
        category,
        ok=category == "success",
        azure_operation_attempted=True,
        trigger_receipt_valid=True,
        correlated_run_observed=observed,
        correlated_run_terminal=terminal,
        correlated_run_succeeded=succeeded,
        **common,
    )
