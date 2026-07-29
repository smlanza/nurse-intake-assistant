from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Callable, Literal
import zipfile

from src.app.services.hosted_foundry_agent_webjob_execution import (
    RECONCILIATION_RECEIPT_RELATIVE_PATH,
    TERMINAL_OUTCOME_RELATIVE_PATH,
    TRIGGER_BLOCKED_RELATIVE_PATH,
    TRIGGER_RECEIPT_RELATIVE_PATH,
    TRIGGER_RESERVATION_RELATIVE_PATH,
    TRIGGER_STATE_DIRECTORY,
    _parse_blocked,
    _parse_outcome,
    _parse_reconciliation_receipt,
    _parse_receipt,
    _reconciliation_matches_blocked,
)
from src.app.services.hosted_foundry_agent_webjob_handoff import (
    GENERATION_HANDOFF_RELATIVE_PATH,
    GENERATION_HANDOFF_SCHEMA_VERSION,
    HostedFoundryAgentWebJobGenerationHandoff,
)
from src.app.services.hosted_foundry_agent_webjob_package import (
    FIXED_ZIP_TIMESTAMP,
    MAX_ENTRYPOINT_SIZE,
    MAX_PACKAGE_SIZE,
    WEBJOB_ARCHIVE_MEMBER,
    WEBJOB_PACKAGE_FILENAME,
)


ARTIFACT_DIRECTORY_NAME = ".artifacts"
ARCHIVE_DIRECTORY = Path(".artifacts/hosted-foundry-agent-webjob-archive")
RECOVERY_RESERVATION_NAME = ".hosted-foundry-agent-webjob-recovery.lock"
PENDING_DIRECTORY_PREFIX = "pending-quarantine-"
BLOCKED_DIRECTORY_PREFIX = "blocked-quarantine-"
RETIREMENT_RECEIPT_SUFFIX = ".retirement-receipt.json"
RECOVERY_OUTCOME_SUFFIX = ".recovery-outcome.json"
RECOVERY_SCHEMA_VERSION = 1
RecoveryState = Literal[
    "empty",
    "prepared",
    "accepted",
    "blocked",
    "terminal-success",
    "terminal-failure",
    "stale",
    "legacy-package-conflict",
    "malformed",
    "conflicting",
    "unsafe",
    "archived",
    "quarantined",
]
RecoveryCategory = Literal[
    "success",
    "archived",
    "invalid_request",
    "unsafe_path",
    "malformed",
    "conflicting",
    "manifest_mismatch",
    "archive_collision",
    "cross_device_unsafe",
    "recovery_reservation_conflict",
    "recovery_blocked",
    "archive_failed",
]

_ALLOWED_FILES = frozenset(
    {
        TRIGGER_RECEIPT_RELATIVE_PATH.name,
        TRIGGER_BLOCKED_RELATIVE_PATH.name,
        RECONCILIATION_RECEIPT_RELATIVE_PATH.name,
        TERMINAL_OUTCOME_RELATIVE_PATH.name,
        TRIGGER_RESERVATION_RELATIVE_PATH.name,
        GENERATION_HANDOFF_RELATIVE_PATH.name,
    }
)
_ARCHIVABLE_STATES = frozenset(
    {
        "prepared",
        "accepted",
        "blocked",
        "terminal-success",
        "terminal-failure",
        "stale",
        "legacy-package-conflict",
    }
)
_REASONS = frozenset(
    {"stale_environment_evidence", "completed_generation_retirement"}
)


@dataclass(frozen=True)
class HostedWebJobStateRecoveryRequest:
    mode: str
    source_root: Path
    expected_environment_fingerprint: str | None = None
    manifest_digest: str | None = None
    reason: str | None = None
    legacy_package_conflict: bool = False


@dataclass(frozen=True)
class RecoveryFileEvidence:
    name: str
    size: int
    sha256: str | None
    schema_version: int | None
    state: str | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "size": self.size,
            "sha256": self.sha256,
            "schema_version": self.schema_version,
            "state": self.state,
        }


@dataclass(frozen=True)
class HostedWebJobStateRecoveryResult:
    ok: bool
    mode: str
    category: RecoveryCategory
    state: RecoveryState
    manifest_digest: str | None
    environment_fingerprint_digest: str | None
    files: tuple[RecoveryFileEvidence, ...] = ()
    archive_relative_path: Path | None = None
    retirement_receipt_relative_path: Path | None = None
    azure_operation_attempted: bool = False
    webjob_triggered: bool = False
    daily_environment_ready: bool = False
    recommended_next_step: str = (
        "Review the sanitized manifest before a separate explicit action."
    )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "category": self.category,
            "state": self.state,
            "manifest_digest": self.manifest_digest,
            "environment_fingerprint_digest": (
                self.environment_fingerprint_digest
            ),
            "files": [item.to_json_dict() for item in self.files],
            "archive_relative_path": (
                str(self.archive_relative_path)
                if self.archive_relative_path is not None
                else None
            ),
            "retirement_receipt_relative_path": (
                str(self.retirement_receipt_relative_path)
                if self.retirement_receipt_relative_path is not None
                else None
            ),
            "azure_operation_attempted": False,
            "webjob_triggered": False,
            "daily_environment_ready": False,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class _FilesystemIdentity:
    device: int
    inode: int


class _UnsafeState(Exception):
    pass


class _ReservationConflict(Exception):
    pass


def _result(
    request: HostedWebJobStateRecoveryRequest,
    category: RecoveryCategory,
    state: RecoveryState,
    *,
    ok: bool = False,
    manifest_digest: str | None = None,
    fingerprint_digest: str | None = None,
    files: tuple[RecoveryFileEvidence, ...] = (),
    archive_relative_path: Path | None = None,
    retirement_receipt_relative_path: Path | None = None,
    next_step: str | None = None,
) -> HostedWebJobStateRecoveryResult:
    return HostedWebJobStateRecoveryResult(
        ok=ok,
        mode=request.mode if request.mode in {"check", "inspect", "archive"} else "invalid",
        category=category,
        state=state,
        manifest_digest=manifest_digest,
        environment_fingerprint_digest=fingerprint_digest,
        files=files,
        archive_relative_path=archive_relative_path,
        retirement_receipt_relative_path=retirement_receipt_relative_path,
        recommended_next_step=next_step
        or "Review the sanitized manifest before a separate explicit action.",
    )


def _directory_flags() -> int:
    if not hasattr(os, "O_DIRECTORY") or not hasattr(os, "O_NOFOLLOW"):
        raise _UnsafeState()
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)


def _open_source_root(source_root: Path) -> int:
    if not source_root.is_absolute() or any(part in {".", ".."} for part in source_root.parts):
        raise _UnsafeState()
    descriptor: int | None = None
    try:
        descriptor = os.open(os.path.sep, _directory_flags())
        for part in source_root.parts[1:]:
            next_descriptor = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise _UnsafeState()
        return descriptor
    except _UnsafeState:
        if descriptor is not None:
            os.close(descriptor)
        raise
    except Exception as error:
        if descriptor is not None:
            os.close(descriptor)
        raise _UnsafeState() from error


def _open_active(source_root: Path) -> int | None:
    source_descriptor: int | None = None
    artifacts_descriptor: int | None = None
    try:
        source_descriptor = _open_source_root(source_root)
        try:
            artifacts_descriptor = os.open(
                ARTIFACT_DIRECTORY_NAME, _directory_flags(), dir_fd=source_descriptor
            )
        except FileNotFoundError:
            raise
        except Exception as error:
            raise _UnsafeState() from error
        return os.open(
            TRIGGER_STATE_DIRECTORY.name,
            _directory_flags(),
            dir_fd=artifacts_descriptor,
        )
    except FileNotFoundError:
        return None
    except _UnsafeState:
        raise
    except Exception as error:
        raise _UnsafeState() from error
    finally:
        if artifacts_descriptor is not None:
            os.close(artifacts_descriptor)
        if source_descriptor is not None:
            os.close(source_descriptor)


def _read_regular(directory: int, name: str) -> bytes:
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
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > 16384:
            raise _UnsafeState()
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
            raise _UnsafeState()
        return payload
    except _UnsafeState:
        raise
    except Exception as error:
        raise _UnsafeState() from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _valid_fingerprint(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _parse_generation_handoff(
    payload: object,
) -> HostedFoundryAgentWebJobGenerationHandoff | None:
    expected = {
        field
        for field in HostedFoundryAgentWebJobGenerationHandoff.__dataclass_fields__
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        return None
    try:
        handoff = HostedFoundryAgentWebJobGenerationHandoff(**payload)
    except TypeError:
        return None
    if (
        handoff.schema_version != GENERATION_HANDOFF_SCHEMA_VERSION
        or handoff.state != "prepared"
        or not _valid_fingerprint(handoff.readiness_configuration_fingerprint)
        or not _valid_fingerprint(handoff.readiness_correlation_fingerprint)
        or not _valid_fingerprint(handoff.environment_fingerprint)
        or not isinstance(handoff.readiness_run_epoch, str)
        or not handoff.readiness_run_epoch
        or not isinstance(handoff.resource_group, str)
        or not handoff.resource_group
        or not isinstance(handoff.web_app_name, str)
        or not handoff.web_app_name
    ):
        return None
    return handoff


def _manifest(
    state: RecoveryState,
    files: tuple[RecoveryFileEvidence, ...],
    fingerprint_digest: str | None,
    *,
    legacy_package_digest: str | None = None,
) -> str:
    payload = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "state": state,
        "environment_fingerprint_digest": fingerprint_digest,
        "files": [item.to_json_dict() for item in files],
    }
    if legacy_package_digest is not None:
        payload["legacy_package_digest"] = legacy_package_digest
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()


def _read_exact_regular(
    directory: int,
    name: str,
    *,
    maximum_size: int,
    required_mode: int,
    required_owner: int,
) -> bytes:
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
        details = os.fstat(descriptor)
        if (
            not stat.S_ISREG(details.st_mode)
            or stat.S_IMODE(details.st_mode) != required_mode
            or details.st_uid != required_owner
            or details.st_size <= 0
            or details.st_size > maximum_size
        ):
            raise _UnsafeState()
        chunks: list[bytes] = []
        remaining = maximum_size + 1
        while remaining:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != details.st_size or len(payload) > maximum_size:
            raise _UnsafeState()
        return payload
    except _UnsafeState:
        raise
    except Exception as error:
        raise _UnsafeState() from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _inspect_legacy_package_conflict(
    request: HostedWebJobStateRecoveryRequest,
    directory: int,
) -> HostedWebJobStateRecoveryResult:
    active_details = os.fstat(directory)
    if (
        stat.S_IMODE(active_details.st_mode) != 0o700
        or sorted(os.listdir(directory))
        != [GENERATION_HANDOFF_RELATIVE_PATH.name, "package"]
    ):
        raise _UnsafeState()
    owner = active_details.st_uid
    handoff_raw = _read_exact_regular(
        directory,
        GENERATION_HANDOFF_RELATIVE_PATH.name,
        maximum_size=16384,
        required_mode=0o600,
        required_owner=owner,
    )
    try:
        handoff_payload = json.loads(handoff_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise _UnsafeState() from error
    handoff = _parse_generation_handoff(handoff_payload)
    if handoff is None:
        raise _UnsafeState()
    package_descriptor: int | None = None
    try:
        package_descriptor = os.open(
            "package",
            _directory_flags(),
            dir_fd=directory,
        )
        package_details = os.fstat(package_descriptor)
        if (
            stat.S_IMODE(package_details.st_mode) != 0o700
            or package_details.st_uid != owner
            or os.listdir(package_descriptor) != [WEBJOB_PACKAGE_FILENAME]
        ):
            raise _UnsafeState()
        package_raw = _read_exact_regular(
            package_descriptor,
            WEBJOB_PACKAGE_FILENAME,
            maximum_size=MAX_PACKAGE_SIZE,
            required_mode=0o600,
            required_owner=owner,
        )
    finally:
        if package_descriptor is not None:
            os.close(package_descriptor)
    try:
        with zipfile.ZipFile(BytesIO(package_raw)) as archive:
            if archive.namelist() != [WEBJOB_ARCHIVE_MEMBER]:
                raise _UnsafeState()
            entry = archive.getinfo(WEBJOB_ARCHIVE_MEMBER)
            entrypoint = archive.read(WEBJOB_ARCHIVE_MEMBER)
            if (
                entry.date_time != FIXED_ZIP_TIMESTAMP
                or entry.is_dir()
                or entry.compress_type != zipfile.ZIP_DEFLATED
                or entry.create_system != 3
                or entry.flag_bits != 0
                or entry.extra != b""
                or entry.comment != b""
                or archive.comment != b""
                or entry.file_size != len(entrypoint)
                or not entrypoint
                or len(entrypoint) > MAX_ENTRYPOINT_SIZE
                or entry.external_attr >> 16 != 0o100644
            ):
                raise _UnsafeState()
    except _UnsafeState:
        raise
    except Exception as error:
        raise _UnsafeState() from error
    fingerprint_digest = hashlib.sha256(
        handoff.environment_fingerprint.encode()
    ).hexdigest()
    package_digest = hashlib.sha256(package_raw).hexdigest()
    files = (
        RecoveryFileEvidence(
            name=GENERATION_HANDOFF_RELATIVE_PATH.name,
            size=len(handoff_raw),
            sha256=hashlib.sha256(handoff_raw).hexdigest(),
            schema_version=handoff.schema_version,
            state=handoff.state,
        ),
        RecoveryFileEvidence(
            name=WEBJOB_PACKAGE_FILENAME,
            size=len(package_raw),
            sha256=None,
            schema_version=None,
            state="legacy-package",
        ),
    )
    state: RecoveryState = "legacy-package-conflict"
    return _result(
        request,
        "success",
        state,
        ok=True,
        manifest_digest=_manifest(
            state,
            files,
            fingerprint_digest,
            legacy_package_digest=package_digest,
        ),
        fingerprint_digest=fingerprint_digest,
        files=files,
        next_step=(
            "Use the exact manifest digest in a separate default-no "
            "transitional archive command."
        ),
    )


def _inspect_open_directory(
    request: HostedWebJobStateRecoveryRequest,
    directory: int,
) -> HostedWebJobStateRecoveryResult:
    if request.legacy_package_conflict:
        return _inspect_legacy_package_conflict(request, directory)
    names = sorted(os.listdir(directory))
    unexpected = [name for name in names if name not in _ALLOWED_FILES]
    payloads: dict[str, object] = {}
    evidence: list[RecoveryFileEvidence] = []
    malformed = False
    for name in names:
        raw = _read_regular(directory, name)
        if name in _ALLOWED_FILES:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                payload = None
            payloads[name] = payload
        else:
            payload = None
        schema = payload.get("schema_version") if isinstance(payload, dict) else None
        item_state = payload.get("state") if isinstance(payload, dict) else None
        if not isinstance(schema, int) or not isinstance(item_state, str):
            malformed = malformed or name in _ALLOWED_FILES
        evidence.append(
            RecoveryFileEvidence(
                name=name if name in _ALLOWED_FILES else "unexpected-file",
                size=len(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
                schema_version=schema if isinstance(schema, int) else None,
                state=item_state if isinstance(item_state, str) else None,
            )
        )
    files = tuple(evidence)
    if unexpected:
        state: RecoveryState = "conflicting"
        return _result(
            request,
            "conflicting",
            state,
            manifest_digest=_manifest(state, files, None),
            files=files,
            next_step="Preserve the directory and investigate unexpected state files.",
        )
    receipt = _parse_receipt(payloads.get(TRIGGER_RECEIPT_RELATIVE_PATH.name))
    blocked = _parse_blocked(payloads.get(TRIGGER_BLOCKED_RELATIVE_PATH.name))
    reconciliation = _parse_reconciliation_receipt(
        payloads.get(RECONCILIATION_RECEIPT_RELATIVE_PATH.name)
    )
    outcome = _parse_outcome(payloads.get(TERMINAL_OUTCOME_RELATIVE_PATH.name))
    handoff = _parse_generation_handoff(
        payloads.get(GENERATION_HANDOFF_RELATIVE_PATH.name)
    )
    if TRIGGER_RECEIPT_RELATIVE_PATH.name in payloads and receipt is None:
        malformed = True
    if TRIGGER_BLOCKED_RELATIVE_PATH.name in payloads and blocked is None:
        malformed = True
    if (
        RECONCILIATION_RECEIPT_RELATIVE_PATH.name in payloads
        and reconciliation is None
    ):
        malformed = True
    if TERMINAL_OUTCOME_RELATIVE_PATH.name in payloads and outcome is None:
        malformed = True
    if GENERATION_HANDOFF_RELATIVE_PATH.name in payloads and handoff is None:
        malformed = True
    if TRIGGER_RESERVATION_RELATIVE_PATH.name in payloads:
        malformed = malformed or payloads[TRIGGER_RESERVATION_RELATIVE_PATH.name] != {
            "schema_version": 1,
            "state": "in-progress",
        }
    fingerprint = (
        handoff.environment_fingerprint
        if handoff is not None
        else receipt.environment_fingerprint
        if receipt is not None
        else blocked.environment_fingerprint
        if blocked is not None
        else reconciliation.environment_fingerprint
        if reconciliation is not None
        else outcome.environment_fingerprint
        if outcome is not None
        else None
    )
    fingerprint_digest = (
        hashlib.sha256(fingerprint.encode()).hexdigest()
        if _valid_fingerprint(fingerprint)
        else None
    )
    if malformed:
        state = "malformed"
        return _result(
            request,
            "malformed",
            state,
            manifest_digest=_manifest(state, files, fingerprint_digest),
            fingerprint_digest=fingerprint_digest,
            files=files,
        )
    same_context = bool(
        receipt is not None
        and outcome is not None
        and receipt.trigger_not_before == outcome.trigger_not_before
        and receipt.resource_group == outcome.resource_group
        and receipt.web_app_name == outcome.web_app_name
        and receipt.webjob_name == outcome.webjob_name
        and receipt.environment_fingerprint == outcome.environment_fingerprint
    )
    handoff_matches_receipt = bool(
        handoff is not None
        and receipt is not None
        and handoff.resource_group == receipt.resource_group
        and handoff.web_app_name == receipt.web_app_name
        and handoff.environment_fingerprint == receipt.environment_fingerprint
    )
    handoff_matches_blocked = bool(
        handoff is not None
        and blocked is not None
        and handoff.resource_group == blocked.resource_group
        and handoff.web_app_name == blocked.web_app_name
        and handoff.environment_fingerprint == blocked.environment_fingerprint
    )
    reconciliation_matches_blocked = bool(
        reconciliation is not None
        and blocked is not None
        and _reconciliation_matches_blocked(reconciliation, blocked)
    )
    reconciliation_matches_outcome = bool(
        reconciliation is not None
        and outcome is not None
        and reconciliation.trigger_not_before == outcome.trigger_not_before
        and reconciliation.resource_group == outcome.resource_group
        and reconciliation.web_app_name == outcome.web_app_name
        and reconciliation.webjob_name == outcome.webjob_name
        and reconciliation.environment_fingerprint
        == outcome.environment_fingerprint
    )
    if (
        handoff is not None
        and receipt is None
        and blocked is None
        and outcome is None
        and len(names) == 1
    ):
        state = "prepared"
    elif (
        blocked is not None
        and receipt is None
        and outcome is None
        and (
            reconciliation is None
            and (
                len(names) == 1
                or len(names) == 2 and handoff_matches_blocked
            )
            or reconciliation_matches_blocked
            and (
                len(names) == 2
                or len(names) == 3 and handoff_matches_blocked
            )
        )
    ):
        state = "blocked"
    elif receipt is not None and blocked is None and outcome is None and (
        len(names) == 1
        or len(names) == 2 and handoff_matches_receipt
    ):
        state = "accepted"
    elif (
        receipt is not None
        and blocked is None
        and outcome is not None
        and (
            len(names) == 2
            or len(names) == 3 and handoff_matches_receipt
        )
        and same_context
    ):
        state = outcome.state
    elif (
        receipt is None
        and blocked is not None
        and reconciliation_matches_blocked
        and outcome is not None
        and reconciliation_matches_outcome
        and (
            len(names) == 3
            or len(names) == 4 and handoff_matches_blocked
        )
    ):
        state = outcome.state
    else:
        state = "conflicting"
    expected = request.expected_environment_fingerprint
    if state in _ARCHIVABLE_STATES and expected is not None:
        if not _valid_fingerprint(expected):
            return _result(request, "invalid_request", "unsafe")
        if fingerprint != expected:
            state = "stale"
    digest = _manifest(state, files, fingerprint_digest)
    return _result(
        request,
        "success" if state in _ARCHIVABLE_STATES else "conflicting",
        state,
        ok=state in _ARCHIVABLE_STATES,
        manifest_digest=digest,
        fingerprint_digest=fingerprint_digest,
        files=files,
        next_step=(
            "Use the exact manifest digest in a separate default-no archive command."
            if state in _ARCHIVABLE_STATES
            else "Preserve the directory and investigate conflicting lifecycle evidence."
        ),
    )


def inspect_hosted_webjob_state(
    request: HostedWebJobStateRecoveryRequest,
) -> HostedWebJobStateRecoveryResult:
    if (
        request.mode not in {"check", "inspect", "archive"}
        or not request.source_root.is_absolute()
        or not isinstance(request.legacy_package_conflict, bool)
        or (
            request.legacy_package_conflict
            and request.mode not in {"inspect", "archive"}
        )
    ):
        return _result(request, "invalid_request", "unsafe")
    try:
        if request.mode == "check":
            descriptor = _open_source_root(request.source_root)
            os.close(descriptor)
            return _result(
                request,
                "success",
                "empty",
                ok=True,
                next_step="Run a separate offline inspection before any retirement.",
            )
        directory = _open_active(request.source_root)
        if directory is None:
            digest = _manifest("empty", (), None)
            return _result(
                request,
                "success",
                "empty",
                ok=True,
                manifest_digest=digest,
                next_step="No active immutable WebJob evidence requires retirement.",
            )
        try:
            return _inspect_open_directory(request, directory)
        finally:
            os.close(directory)
    except _UnsafeState:
        return _result(
            request,
            "unsafe_path",
            "unsafe",
            next_step="Preserve the path and remove no files; investigate the unsafe filesystem shape.",
        )


def _identity(details: os.stat_result) -> _FilesystemIdentity:
    return _FilesystemIdentity(details.st_dev, details.st_ino)


def _entry_identity(directory: int, name: str) -> _FilesystemIdentity | None:
    try:
        details = os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(details.st_mode):
        raise _UnsafeState()
    return _identity(details)


def _entry_exists(directory: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _rename_verified(
    source_directory: int,
    source_name: str,
    destination_directory: int,
    destination_name: str,
    expected_identity: _FilesystemIdentity,
) -> bool:
    if _entry_identity(source_directory, source_name) != expected_identity:
        return False
    if _entry_identity(destination_directory, destination_name) is not None:
        return False
    os.rename(
        source_name,
        destination_name,
        src_dir_fd=source_directory,
        dst_dir_fd=destination_directory,
    )
    return (
        _entry_identity(source_directory, source_name) is None
        and _entry_identity(destination_directory, destination_name)
        == expected_identity
    )


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError()
        offset += written


def _acquire_recovery_reservation(artifacts_directory: int) -> _FilesystemIdentity:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            RECOVERY_RESERVATION_NAME,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=artifacts_directory,
        )
        _write_all(
            descriptor,
            b'{"schema_version":1,"state":"recovery-in-progress"}',
        )
        os.fsync(descriptor)
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise _UnsafeState()
        os.fsync(artifacts_directory)
        return _identity(details)
    except FileExistsError as error:
        existing: int | None = None
        try:
            existing = os.open(
                RECOVERY_RESERVATION_NAME,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=artifacts_directory,
            )
            if not stat.S_ISREG(os.fstat(existing).st_mode):
                raise _UnsafeState()
        except _UnsafeState:
            raise
        except Exception as unsafe_error:
            raise _UnsafeState() from unsafe_error
        finally:
            if existing is not None:
                os.close(existing)
        raise _ReservationConflict() from error
    except (_UnsafeState, _ReservationConflict):
        raise
    except Exception as error:
        raise _UnsafeState() from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _release_recovery_reservation(
    artifacts_directory: int,
    reservation: _FilesystemIdentity,
) -> bool:
    try:
        details = os.stat(
            RECOVERY_RESERVATION_NAME,
            dir_fd=artifacts_directory,
            follow_symlinks=False,
        )
        if not stat.S_ISREG(details.st_mode) or _identity(details) != reservation:
            return False
        os.unlink(RECOVERY_RESERVATION_NAME, dir_fd=artifacts_directory)
        os.fsync(artifacts_directory)
        return True
    except Exception:
        return False


def _write_recovery_record(
    directory: int,
    name: str,
    payload: dict[str, object],
) -> None:
    temporary_name = f".{name}.{secrets.token_hex(16)}.tmp"
    descriptor: int | None = None
    published = False
    try:
        serialized = json.dumps(
            payload, separators=(",", ":"), sort_keys=True
        ).encode()
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
            0o400,
            dir_fd=directory,
        )
        _write_all(descriptor, serialized)
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.link(
            temporary_name,
            name,
            src_dir_fd=directory,
            dst_dir_fd=directory,
            follow_symlinks=False,
        )
        published = True
        os.fsync(directory)
    except Exception:
        if published:
            try:
                os.unlink(name, dir_fd=directory)
                os.fsync(directory)
            except OSError:
                pass
        raise
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary_name, dir_fd=directory)
            os.fsync(directory)
        except OSError:
            pass


def _blocked_record_payload(
    request: HostedWebJobStateRecoveryRequest,
    *,
    timestamp: str,
    archived_manifest: str | None,
    disposition: str,
    quarantine_relative_path: Path | None,
) -> dict[str, object]:
    return {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "state": "recovery-blocked",
        "approved_manifest_digest": request.manifest_digest,
        "quarantined_manifest_digest": archived_manifest,
        "recorded_at": timestamp,
        "reason": request.reason,
        "disposition": disposition,
        "quarantine_relative_path": (
            str(quarantine_relative_path)
            if quarantine_relative_path is not None
            else None
        ),
    }


def recover_hosted_webjob_state(
    request: HostedWebJobStateRecoveryRequest,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> HostedWebJobStateRecoveryResult:
    if (
        request.mode != "archive"
        or not request.source_root.is_absolute()
        or request.reason not in _REASONS
        or not isinstance(request.manifest_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", request.manifest_digest) is None
        or (
            request.expected_environment_fingerprint is not None
            and not _valid_fingerprint(request.expected_environment_fingerprint)
        )
        or not isinstance(request.legacy_package_conflict, bool)
    ):
        return _result(request, "invalid_request", "unsafe")

    source_descriptor: int | None = None
    artifacts_descriptor: int | None = None
    archive_descriptor: int | None = None
    pending_descriptor: int | None = None
    final_descriptor: int | None = None
    reservation: _FilesystemIdentity | None = None
    reservation_must_remain = False
    mutation_started = False
    quarantined_identity: _FilesystemIdentity | None = None
    pending_name: str | None = None
    inspected: HostedWebJobStateRecoveryResult | None = None
    try:
        timestamp_value = now().astimezone(timezone.utc)
        timestamp_name = timestamp_value.strftime("%Y%m%dT%H%M%SZ")
        timestamp = timestamp_value.isoformat().replace("+00:00", "Z")
        operation_token = secrets.token_hex(16)
        destination_name = f"{timestamp_name}-{request.manifest_digest[:16]}"
        receipt_name = f"{destination_name}{RETIREMENT_RECEIPT_SUFFIX}"
        pending_name = f"{PENDING_DIRECTORY_PREFIX}{operation_token}"
        blocked_name = (
            f"{BLOCKED_DIRECTORY_PREFIX}{timestamp_name}-"
            f"{request.manifest_digest[:16]}-{operation_token}"
        )
        outcome_name = f"{blocked_name}{RECOVERY_OUTCOME_SUFFIX}"

        source_descriptor = _open_source_root(request.source_root)
        try:
            artifacts_descriptor = os.open(
                ARTIFACT_DIRECTORY_NAME,
                _directory_flags(),
                dir_fd=source_descriptor,
            )
        except Exception as error:
            raise _UnsafeState() from error
        try:
            reservation = _acquire_recovery_reservation(artifacts_descriptor)
        except _ReservationConflict:
            return _result(
                request,
                "recovery_reservation_conflict",
                "unsafe",
                next_step="Preserve the existing recovery reservation and investigate it manually.",
            )
        try:
            os.mkdir(ARCHIVE_DIRECTORY.name, mode=0o700, dir_fd=artifacts_descriptor)
        except FileExistsError:
            pass
        try:
            archive_descriptor = os.open(
                ARCHIVE_DIRECTORY.name,
                _directory_flags(),
                dir_fd=artifacts_descriptor,
            )
        except Exception as error:
            raise _UnsafeState() from error
        active_identity = _entry_identity(
            artifacts_descriptor, TRIGGER_STATE_DIRECTORY.name
        )
        if active_identity is None:
            return _result(
                request,
                "manifest_mismatch",
                "empty",
                next_step="No active evidence was quarantined; inspect again before another request.",
            )
        if active_identity.device != os.fstat(archive_descriptor).st_dev:
            return _result(request, "cross_device_unsafe", "unsafe")
        if (
            _entry_identity(archive_descriptor, destination_name) is not None
            or _entry_exists(archive_descriptor, receipt_name)
        ):
            return _result(request, "archive_collision", "unsafe")

        mutation_started = True
        if not _rename_verified(
            artifacts_descriptor,
            TRIGGER_STATE_DIRECTORY.name,
            artifacts_descriptor,
            pending_name,
            active_identity,
        ):
            reservation_must_remain = True
            pending_identity = _entry_identity(artifacts_descriptor, pending_name)
            relative = (
                Path(ARTIFACT_DIRECTORY_NAME) / pending_name
                if pending_identity is not None
                else None
            )
            return _result(
                request,
                "recovery_blocked",
                "quarantined",
                archive_relative_path=relative,
                next_step="Preserve the recovery reservation and quarantine path for manual investigation.",
            )
        quarantined_identity = active_identity
        try:
            pending_descriptor = os.open(
                pending_name, _directory_flags(), dir_fd=artifacts_descriptor
            )
        except Exception as error:
            reservation_must_remain = True
            raise _UnsafeState() from error
        if _identity(os.fstat(pending_descriptor)) != quarantined_identity:
            reservation_must_remain = True
            return _result(request, "recovery_blocked", "quarantined")
        try:
            inspected = _inspect_open_directory(request, pending_descriptor)
        except _UnsafeState:
            inspected = _result(request, "unsafe_path", "unsafe")

        active_conflict = (
            _entry_identity(artifacts_descriptor, TRIGGER_STATE_DIRECTORY.name)
            is not None
        )
        exact_manifest = bool(
            inspected.ok
            and inspected.state in _ARCHIVABLE_STATES
            and inspected.manifest_digest == request.manifest_digest
            and not active_conflict
        )
        if not exact_manifest:
            restored = False
            if _entry_identity(artifacts_descriptor, TRIGGER_STATE_DIRECTORY.name) is None:
                restored = _rename_verified(
                    artifacts_descriptor,
                    pending_name,
                    artifacts_descriptor,
                    TRIGGER_STATE_DIRECTORY.name,
                    quarantined_identity,
                )
            quarantine_relative: Path | None = None
            disposition = "restored-active" if restored else "retained-quarantine"
            if not restored:
                if _rename_verified(
                    artifacts_descriptor,
                    pending_name,
                    archive_descriptor,
                    blocked_name,
                    quarantined_identity,
                ):
                    quarantine_relative = ARCHIVE_DIRECTORY / blocked_name
                else:
                    reservation_must_remain = True
                    quarantine_relative = Path(ARTIFACT_DIRECTORY_NAME) / pending_name
            try:
                _write_recovery_record(
                    archive_descriptor,
                    outcome_name,
                    _blocked_record_payload(
                        request,
                        timestamp=timestamp,
                        archived_manifest=inspected.manifest_digest,
                        disposition=disposition,
                        quarantine_relative_path=quarantine_relative,
                    ),
                )
            except Exception:
                reservation_must_remain = True
            if reservation_must_remain:
                return _result(
                    request,
                    "recovery_blocked",
                    "quarantined" if not restored else inspected.state,
                    manifest_digest=inspected.manifest_digest,
                    fingerprint_digest=inspected.environment_fingerprint_digest,
                    files=inspected.files,
                    archive_relative_path=quarantine_relative,
                    next_step="Preserve the recovery reservation and retained evidence for manual investigation.",
                )
            if not _release_recovery_reservation(artifacts_descriptor, reservation):
                reservation_must_remain = True
                return _result(
                    request,
                    "recovery_blocked",
                    "quarantined" if not restored else inspected.state,
                    manifest_digest=inspected.manifest_digest,
                    fingerprint_digest=inspected.environment_fingerprint_digest,
                    files=inspected.files,
                    archive_relative_path=quarantine_relative,
                    next_step="The terminal recovery record is durable but reservation release failed; investigate manually.",
                )
            reservation = None
            return _result(
                request,
                "manifest_mismatch" if restored else "recovery_blocked",
                inspected.state if restored else "quarantined",
                manifest_digest=inspected.manifest_digest,
                fingerprint_digest=inspected.environment_fingerprint_digest,
                files=inspected.files,
                archive_relative_path=quarantine_relative,
                next_step=(
                    "The quarantined evidence was restored unchanged; inspect it again."
                    if restored
                    else "A conflicting active path exists; preserve the blocked quarantine and investigate."
                ),
            )

        if not _rename_verified(
            artifacts_descriptor,
            pending_name,
            archive_descriptor,
            destination_name,
            quarantined_identity,
        ):
            reservation_must_remain = True
            final_identity = _entry_identity(archive_descriptor, destination_name)
            quarantine_relative: Path | None = None
            if final_identity is not None and _rename_verified(
                archive_descriptor,
                destination_name,
                archive_descriptor,
                blocked_name,
                final_identity,
            ):
                quarantine_relative = ARCHIVE_DIRECTORY / blocked_name
            return _result(
                request,
                "recovery_blocked",
                "quarantined",
                manifest_digest=inspected.manifest_digest,
                fingerprint_digest=inspected.environment_fingerprint_digest,
                files=inspected.files,
                archive_relative_path=quarantine_relative,
                next_step="Final archive identity verification failed; preserve the reservation and both paths.",
            )
        os.fsync(artifacts_descriptor)
        os.fsync(archive_descriptor)
        archive_relative = ARCHIVE_DIRECTORY / destination_name
        receipt_relative = ARCHIVE_DIRECTORY / receipt_name
        try:
            final_descriptor = os.open(
                destination_name, _directory_flags(), dir_fd=archive_descriptor
            )
        except Exception as error:
            reservation_must_remain = True
            raise _UnsafeState() from error
        if _identity(os.fstat(final_descriptor)) != quarantined_identity:
            reservation_must_remain = True
            return _result(request, "recovery_blocked", "quarantined")
        try:
            finalized_inspection = _inspect_open_directory(request, final_descriptor)
        except _UnsafeState:
            finalized_inspection = _result(request, "unsafe_path", "unsafe")
        finalized_manifest_matches = bool(
            finalized_inspection.ok
            and finalized_inspection.state in _ARCHIVABLE_STATES
            and finalized_inspection.manifest_digest == request.manifest_digest
            and _entry_identity(
                artifacts_descriptor, TRIGGER_STATE_DIRECTORY.name
            )
            is None
        )
        if not finalized_manifest_matches:
            blocked = _rename_verified(
                archive_descriptor,
                destination_name,
                archive_descriptor,
                blocked_name,
                quarantined_identity,
            )
            quarantine_relative = (
                ARCHIVE_DIRECTORY / blocked_name if blocked else archive_relative
            )
            try:
                _write_recovery_record(
                    archive_descriptor,
                    outcome_name,
                    _blocked_record_payload(
                        request,
                        timestamp=timestamp,
                        archived_manifest=finalized_inspection.manifest_digest,
                        disposition="retained-quarantine",
                        quarantine_relative_path=quarantine_relative,
                    ),
                )
            except Exception:
                reservation_must_remain = True
            if not blocked:
                reservation_must_remain = True
            if not reservation_must_remain:
                if _release_recovery_reservation(
                    artifacts_descriptor, reservation
                ):
                    reservation = None
                else:
                    reservation_must_remain = True
            return _result(
                request,
                "recovery_blocked",
                "quarantined",
                manifest_digest=finalized_inspection.manifest_digest,
                fingerprint_digest=(
                    finalized_inspection.environment_fingerprint_digest
                ),
                files=finalized_inspection.files,
                archive_relative_path=quarantine_relative,
                next_step="Final archived evidence did not match approval; preserve the blocked quarantine and investigate.",
            )
        inspected = finalized_inspection
        try:
            _write_recovery_record(
                archive_descriptor,
                receipt_name,
                {
                    "schema_version": RECOVERY_SCHEMA_VERSION,
                    "state": "retired",
                    "approved_manifest_digest": request.manifest_digest,
                    "archived_manifest_digest": inspected.manifest_digest,
                    "archive_relative_path": str(archive_relative),
                    "retired_at": timestamp,
                    "reason": request.reason,
                    "files": [item.to_json_dict() for item in inspected.files],
                },
            )
        except Exception:
            restored = False
            retained_relative: Path | None = archive_relative
            if (
                _entry_identity(artifacts_descriptor, TRIGGER_STATE_DIRECTORY.name)
                is None
            ):
                restored = _rename_verified(
                    archive_descriptor,
                    destination_name,
                    artifacts_descriptor,
                    TRIGGER_STATE_DIRECTORY.name,
                    quarantined_identity,
                )
            if restored:
                retained_relative = None
            elif _rename_verified(
                archive_descriptor,
                destination_name,
                archive_descriptor,
                blocked_name,
                quarantined_identity,
            ):
                retained_relative = ARCHIVE_DIRECTORY / blocked_name
            reservation_must_remain = True
            return _result(
                request,
                "archive_failed",
                inspected.state if restored else "quarantined",
                manifest_digest=inspected.manifest_digest,
                fingerprint_digest=inspected.environment_fingerprint_digest,
                files=inspected.files,
                archive_relative_path=retained_relative,
                next_step="Retirement receipt persistence failed; preserve the reservation and investigate manually.",
            )
        if not _release_recovery_reservation(artifacts_descriptor, reservation):
            reservation_must_remain = True
            return _result(
                request,
                "archive_failed",
                "archived",
                manifest_digest=inspected.manifest_digest,
                fingerprint_digest=inspected.environment_fingerprint_digest,
                files=inspected.files,
                archive_relative_path=archive_relative,
                retirement_receipt_relative_path=receipt_relative,
                next_step="The archive is durable but reservation release failed; investigate before another recovery.",
            )
        reservation = None
        return _result(
            request,
            "archived",
            "archived",
            ok=True,
            manifest_digest=inspected.manifest_digest,
            fingerprint_digest=inspected.environment_fingerprint_digest,
            files=inspected.files,
            archive_relative_path=archive_relative,
            retirement_receipt_relative_path=receipt_relative,
            next_step="Verify the archived evidence and external receipt, then rerun the daily coordinator from the beginning.",
        )
    except _UnsafeState:
        if mutation_started:
            reservation_must_remain = True
        return _result(request, "unsafe_path", "unsafe")
    except Exception:
        if mutation_started:
            reservation_must_remain = True
        return _result(
            request,
            "archive_failed",
            "quarantined" if mutation_started else "unsafe",
            next_step="Preserve the recovery reservation and all evidence paths for manual investigation.",
        )
    finally:
        if (
            reservation is not None
            and artifacts_descriptor is not None
            and not reservation_must_remain
        ):
            _release_recovery_reservation(artifacts_descriptor, reservation)
        for descriptor in (
            final_descriptor,
            pending_descriptor,
            archive_descriptor,
            artifacts_descriptor,
            source_descriptor,
        ):
            if descriptor is not None:
                os.close(descriptor)
