import json
from datetime import datetime, timezone
import os
from pathlib import Path

import pytest

from src.app.services.hosted_foundry_agent_webjob_execution import (
    FileTriggerReceiptStore,
    TriggerReceipt,
)
from src.app.services.hosted_foundry_agent_webjob_state_recovery import (
    HostedWebJobStateRecoveryRequest,
    inspect_hosted_webjob_state,
    recover_hosted_webjob_state,
)
import src.app.services.hosted_foundry_agent_webjob_state_recovery as recovery_service


OLD_FINGERPRINT = "a" * 64
CURRENT_FINGERPRINT = "b" * 64


def _accepted(root: Path) -> Path:
    store = FileTriggerReceiptStore(root)
    store.write(
        TriggerReceipt(
            schema_version=2,
            state="accepted",
            trigger_not_before=datetime(2026, 7, 21, tzinfo=timezone.utc),
            resource_group="fictional-rg",
            web_app_name="fictional-web",
            webjob_name="verify-hosted-foundry-agent",
            environment_fingerprint=OLD_FINGERPRINT,
        )
    )
    return root / ".artifacts/hosted-foundry-agent-webjob"


def _request(root: Path, mode: str = "inspect", digest: str | None = None):
    return HostedWebJobStateRecoveryRequest(
        mode=mode,
        source_root=root,
        expected_environment_fingerprint=CURRENT_FINGERPRINT,
        manifest_digest=digest,
        reason="stale_environment_evidence",
    )


def test_inspection_is_offline_and_sanitizes_valid_prior_generation_state(
    tmp_path: Path,
) -> None:
    _accepted(tmp_path)

    result = inspect_hosted_webjob_state(_request(tmp_path))

    assert result.ok is True
    assert result.category == "success"
    assert result.state == "stale"
    assert len(result.manifest_digest or "") == 64
    assert result.azure_operation_attempted is False
    assert result.webjob_triggered is False
    assert result.daily_environment_ready is False
    serialized = json.dumps(result.to_json_dict())
    assert "fictional-rg" not in serialized
    assert OLD_FINGERPRINT not in serialized


@pytest.mark.parametrize("shape", ["malformed", "conflicting"])
def test_inspection_rejects_malformed_or_conflicting_state(
    tmp_path: Path, shape: str
) -> None:
    active = _accepted(tmp_path)
    if shape == "malformed":
        (active / "accepted-trigger.json").write_text("not-json")
    else:
        (active / "blocked-trigger.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "state": "accepted-uncorrelatable",
                    "trigger_not_before": "2026-07-21T00:00:00Z",
                    "resource_group": "fictional-rg",
                    "web_app_name": "fictional-web",
                    "webjob_name": "verify-hosted-foundry-agent",
                    "environment_fingerprint": OLD_FINGERPRINT,
                }
            )
        )

    result = inspect_hosted_webjob_state(_request(tmp_path))

    assert result.ok is False
    assert result.category == shape
    assert result.manifest_digest is not None


@pytest.mark.parametrize("target", ["active", "artifact"])
def test_inspection_rejects_symlinked_state_paths(
    tmp_path: Path, target: str
) -> None:
    active = _accepted(tmp_path)
    if target == "active":
        real = tmp_path / "real-state"
        active.rename(real)
        active.symlink_to(real, target_is_directory=True)
    else:
        artifact = active / "accepted-trigger.json"
        real = tmp_path / "real-receipt.json"
        artifact.rename(real)
        artifact.symlink_to(real)

    result = inspect_hosted_webjob_state(_request(tmp_path))

    assert result.ok is False
    assert result.category == "unsafe_path"


def test_archive_rejects_manifest_mismatch_or_changed_artifact(tmp_path: Path) -> None:
    active = _accepted(tmp_path)
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None

    mismatch = recover_hosted_webjob_state(_request(tmp_path, "archive", "c" * 64))
    assert mismatch.category == "manifest_mismatch"
    assert active.is_dir()

    payload = json.loads((active / "accepted-trigger.json").read_text())
    payload["trigger_not_before"] = "2026-07-21T00:00:01Z"
    (active / "accepted-trigger.json").write_text(json.dumps(payload))
    changed = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest)
    )
    assert changed.category == "manifest_mismatch"
    assert active.is_dir()


def test_replacement_before_quarantine_is_reinspected_and_restored_unapproved(
    tmp_path: Path,
) -> None:
    active = _accepted(tmp_path)
    original = (active / "accepted-trigger.json").read_bytes()
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    reviewed_elsewhere = active.with_name("reviewed-before-replacement")
    active.rename(reviewed_elsewhere)
    active.mkdir()
    (active / "unreviewed-replacement.json").write_text('{"unreviewed":true}')

    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.ok is False
    assert result.category == "manifest_mismatch"
    assert (active / "unreviewed-replacement.json").exists()
    assert (reviewed_elsewhere / "accepted-trigger.json").read_bytes() == original
    assert not list(
        (tmp_path / ".artifacts/hosted-foundry-agent-webjob-archive").glob(
            "*.retirement-receipt.json"
        )
    )


def test_malformed_quarantined_evidence_is_restored_without_success(tmp_path: Path) -> None:
    active = _accepted(tmp_path)
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    (active / "accepted-trigger.json").write_text("not-json")

    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.ok is False
    assert result.category == "manifest_mismatch"
    assert (active / "accepted-trigger.json").read_text() == "not-json"


def test_active_recreated_during_quarantine_inspection_blocks_finalization(
    monkeypatch, tmp_path: Path
) -> None:
    active = _accepted(tmp_path)
    original = (active / "accepted-trigger.json").read_bytes()
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    actual_inspect = recovery_service._inspect_open_directory

    def inspect_and_recreate(request, directory):
        result = actual_inspect(request, directory)
        active.mkdir()
        (active / "conflicting-new-state.json").write_text('{"new":true}')
        return result

    monkeypatch.setattr(
        recovery_service, "_inspect_open_directory", inspect_and_recreate
    )
    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.ok is False
    assert result.category == "recovery_blocked"
    assert (active / "conflicting-new-state.json").exists()
    assert result.archive_relative_path is not None
    blocked = tmp_path / result.archive_relative_path
    assert "blocked-quarantine" in blocked.name
    assert (blocked / "accepted-trigger.json").read_bytes() == original
    assert not list(blocked.parent.glob("*.retirement-receipt.json"))


def test_archive_rejects_directory_swapped_immediately_before_rename(
    monkeypatch, tmp_path: Path
) -> None:
    active = _accepted(tmp_path)
    original = (active / "accepted-trigger.json").read_bytes()
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    real_rename = os.rename
    swapped = False

    def swap_before_rename(source, destination, *args, **kwargs):
        nonlocal swapped
        if (
            not swapped
            and source == "hosted-foundry-agent-webjob"
            and kwargs.get("src_dir_fd") is not None
        ):
            swapped = True
            source_directory = kwargs["src_dir_fd"]
            real_rename(
                source,
                "reviewed-evidence-moved-elsewhere",
                src_dir_fd=source_directory,
                dst_dir_fd=source_directory,
            )
            os.mkdir(source, mode=0o700, dir_fd=source_directory)
            replacement_directory = os.open(
                source, os.O_RDONLY | os.O_DIRECTORY, dir_fd=source_directory
            )
            try:
                replacement = os.open(
                    "unreviewed-replacement.json",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=replacement_directory,
                )
                os.write(replacement, b'{"unreviewed":true}')
                os.close(replacement)
            finally:
                os.close(replacement_directory)
        return real_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", swap_before_rename)

    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert swapped is True
    assert result.ok is False
    assert result.category in {"manifest_mismatch", "recovery_blocked"}
    archive_root = tmp_path / ".artifacts/hosted-foundry-agent-webjob-archive"
    assert not list(archive_root.glob("*/retirement-receipt.json"))
    assert not list(archive_root.glob("*.retirement-receipt.json"))
    assert (
        tmp_path
        / ".artifacts/reviewed-evidence-moved-elsewhere/accepted-trigger.json"
    ).read_bytes() == original
    replacement_files = list(
        (tmp_path / ".artifacts").glob(
            "pending-quarantine-*/unreviewed-replacement.json"
        )
    )
    assert len(replacement_files) == 1
    assert replacement_files[0].read_bytes() == b'{"unreviewed":true}'
    assert (
        tmp_path / ".artifacts/.hosted-foundry-agent-webjob-recovery.lock"
    ).is_file()


@pytest.mark.parametrize("attack", ["directory-swap", "file-mutation"])
def test_archive_revalidates_evidence_at_final_archive_rename(
    monkeypatch, tmp_path: Path, attack: str
) -> None:
    active = _accepted(tmp_path)
    original = (active / "accepted-trigger.json").read_bytes()
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    real_rename = os.rename
    attacked = False

    def attack_final_rename(source, destination, *args, **kwargs):
        nonlocal attacked
        if not attacked and str(source).startswith("pending-quarantine-"):
            attacked = True
            source_directory = kwargs["src_dir_fd"]
            if attack == "directory-swap":
                real_rename(
                    source,
                    "reviewed-pending-moved-elsewhere",
                    src_dir_fd=source_directory,
                    dst_dir_fd=source_directory,
                )
                os.mkdir(source, mode=0o700, dir_fd=source_directory)
                pending = os.open(
                    source, os.O_RDONLY | os.O_DIRECTORY, dir_fd=source_directory
                )
                try:
                    replacement = os.open(
                        "unreviewed-replacement.json",
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=pending,
                    )
                    os.write(replacement, b'{"unreviewed":true}')
                    os.close(replacement)
                finally:
                    os.close(pending)
            else:
                pending = os.open(
                    source, os.O_RDONLY | os.O_DIRECTORY, dir_fd=source_directory
                )
                try:
                    receipt = os.open(
                        "accepted-trigger.json", os.O_WRONLY | os.O_TRUNC, dir_fd=pending
                    )
                    os.write(receipt, b'{"changed":true}')
                    os.close(receipt)
                finally:
                    os.close(pending)
        return real_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", attack_final_rename)
    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert attacked is True
    assert result.ok is False
    assert result.category == "recovery_blocked"
    archive_root = tmp_path / ".artifacts/hosted-foundry-agent-webjob-archive"
    assert not list(archive_root.glob("*.retirement-receipt.json"))
    if attack == "directory-swap":
        assert (
            tmp_path
            / ".artifacts/reviewed-pending-moved-elsewhere/accepted-trigger.json"
        ).read_bytes() == original
        assert result.archive_relative_path is not None
        assert "blocked-quarantine" in result.archive_relative_path.name
    else:
        assert result.archive_relative_path is not None
        blocked = tmp_path / result.archive_relative_path
        assert (blocked / "accepted-trigger.json").read_bytes() == b'{"changed":true}'

def test_archive_collision_fails_without_moving_active_state(tmp_path: Path) -> None:
    active = _accepted(tmp_path)
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    archive_root = tmp_path / ".artifacts/hosted-foundry-agent-webjob-archive"
    archive_root.mkdir()
    destination = archive_root / f"20260722T120000Z-{inspected.manifest_digest[:16]}"
    destination.mkdir()

    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.category == "archive_collision"
    assert active.is_dir()


def test_recovery_reservation_conflict_preserves_active_state(tmp_path: Path) -> None:
    active = _accepted(tmp_path)
    reservation = tmp_path / ".artifacts/.hosted-foundry-agent-webjob-recovery.lock"
    reservation.write_text('{"schema_version":1,"state":"recovery-in-progress"}')
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None

    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest)
    )

    assert result.ok is False
    assert result.category == "recovery_reservation_conflict"
    assert active.is_dir()
    assert reservation.exists()


@pytest.mark.parametrize("target", ["artifacts", "archive", "reservation", "pending"])
def test_archive_rejects_symlinked_recovery_paths(
    monkeypatch, tmp_path: Path, target: str
) -> None:
    active = _accepted(tmp_path)
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    artifacts = tmp_path / ".artifacts"
    external = tmp_path / f"external-{target}"
    if target == "artifacts":
        artifacts.rename(external)
        artifacts.symlink_to(external, target_is_directory=True)
    elif target == "archive":
        external.mkdir()
        (artifacts / "hosted-foundry-agent-webjob-archive").symlink_to(
            external, target_is_directory=True
        )
    elif target == "reservation":
        external.write_text("unsafe")
        (artifacts / ".hosted-foundry-agent-webjob-recovery.lock").symlink_to(
            external
        )
    else:
        external.mkdir()
        monkeypatch.setattr(recovery_service.secrets, "token_hex", lambda _size: "c" * 32)
        (artifacts / f"pending-quarantine-{'c' * 32}").symlink_to(
            external, target_is_directory=True
        )

    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.ok is False
    assert result.category == "unsafe_path"
    assert active.exists() or target == "artifacts"


def test_retirement_receipt_failure_restores_evidence_and_preserves_reservation(
    monkeypatch, tmp_path: Path
) -> None:
    active = _accepted(tmp_path)
    original = (active / "accepted-trigger.json").read_bytes()
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    write_record = recovery_service._write_recovery_record

    def fail_retirement(directory, name, payload):
        if name.endswith(recovery_service.RETIREMENT_RECEIPT_SUFFIX):
            raise OSError("raw persistence detail")
        return write_record(directory, name, payload)

    monkeypatch.setattr(recovery_service, "_write_recovery_record", fail_retirement)
    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.ok is False
    assert result.category == "archive_failed"
    assert (active / "accepted-trigger.json").read_bytes() == original
    assert (
        tmp_path / ".artifacts/.hosted-foundry-agent-webjob-recovery.lock"
    ).is_file()
    assert not list(
        (tmp_path / ".artifacts/hosted-foundry-agent-webjob-archive").glob(
            "*.retirement-receipt.json"
        )
    )


def test_atomic_archive_preserves_files_adds_receipt_and_allows_new_generation(
    tmp_path: Path,
) -> None:
    active = _accepted(tmp_path)
    original = (active / "accepted-trigger.json").read_bytes()
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None

    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.ok is True
    assert result.category == "archived"
    assert not active.exists()
    assert result.archive_relative_path is not None
    archived = tmp_path / result.archive_relative_path
    assert (archived / "accepted-trigger.json").read_bytes() == original
    assert not (archived / "retirement-receipt.json").exists()
    retirement = json.loads(
        (archived.parent / f"{archived.name}.retirement-receipt.json").read_text()
    )
    assert retirement["approved_manifest_digest"] == inspected.manifest_digest
    assert retirement["archived_manifest_digest"] == inspected.manifest_digest
    assert retirement["reason"] == "stale_environment_evidence"
    assert result.daily_environment_ready is False
    assert result.webjob_triggered is False
    FileTriggerReceiptStore(tmp_path).write(
        TriggerReceipt(
            2,
            "accepted",
            datetime(2026, 7, 22, tzinfo=timezone.utc),
            "new-rg",
            "new-web",
            "verify-hosted-foundry-agent",
            CURRENT_FINGERPRINT,
        )
    )
    assert active.is_dir()

    repeated = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )
    assert repeated.ok is False
    assert repeated.category in {"manifest_mismatch", "archive_collision"}


def test_success_never_unlinks_an_individual_lifecycle_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    _accepted(tmp_path)
    inspected = inspect_hosted_webjob_state(_request(tmp_path))
    assert inspected.manifest_digest is not None
    unlinked: list[str] = []
    real_unlink = os.unlink

    def record_unlink(path, *args, **kwargs):
        unlinked.append(str(path))
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", record_unlink)
    result = recover_hosted_webjob_state(
        _request(tmp_path, "archive", inspected.manifest_digest),
        now=lambda: datetime(2026, 7, 22, 12, tzinfo=timezone.utc),
    )

    assert result.ok is True
    assert not {
        "accepted-trigger.json",
        "blocked-trigger.json",
        "terminal-outcome.json",
    }.intersection(unlinked)
