from dataclasses import replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64
RUN_ID = "private-run-1"


def _service():
    return importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_execution"
    )


def _request(mode: str):
    service = _service()
    return service.HostedFoundryAgentWebJobExecutionRequest(
        mode=mode,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        source_root=ROOT,
        environment_fingerprint=FINGERPRINT,
    )


def _blocked():
    service = _service()
    return service.BlockedTrigger(
        schema_version=service.TRIGGER_BLOCKED_SCHEMA_VERSION,
        state="accepted-uncorrelatable",
        trigger_not_before=NOW,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        webjob_name=service.WEBJOB_NAME,
        environment_fingerprint=FINGERPRINT,
    )


def _accepted():
    service = _service()
    return service.TriggerReceipt(
        schema_version=service.TRIGGER_RECEIPT_SCHEMA_VERSION,
        state="accepted",
        trigger_not_before=NOW,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        webjob_name=service.WEBJOB_NAME,
        environment_fingerprint=FINGERPRINT,
    )


def _reconciliation(*, status: str = "Running"):
    return _service().ReconciliationReceipt.from_blocked_trigger(
        _blocked(),
        run_id=RUN_ID,
        run_start_time=NOW,
        observed_status=status,
    )


def _outcome(*, succeeded: bool):
    service = _service()
    return service.TerminalOutcome(
        schema_version=service.TERMINAL_OUTCOME_SCHEMA_VERSION,
        state="terminal-success" if succeeded else "terminal-failure",
        trigger_not_before=NOW,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        webjob_name=service.WEBJOB_NAME,
        environment_fingerprint=FINGERPRINT,
    )


class MemoryStore:
    def __init__(
        self,
        *,
        accepted=None,
        blocked=None,
        reconciliation=None,
        outcome=None,
        read_error=False,
        reconciliation_write_error=False,
        outcome_write_error=False,
    ) -> None:
        self.accepted = accepted
        self.blocked = blocked
        self.reconciliation = reconciliation
        self.outcome = outcome
        self.read_error = read_error
        self.reconciliation_write_error = reconciliation_write_error
        self.outcome_write_error = outcome_write_error
        self.reconciliation_writes = []
        self.outcome_writes = []

    def reservation_exists(self) -> bool:
        return False

    def read(self):
        if self.read_error:
            raise RuntimeError("private read failure")
        return self.accepted

    def read_blocked(self):
        if self.read_error:
            raise RuntimeError("private read failure")
        return self.blocked

    def read_reconciliation(self):
        if self.read_error:
            raise RuntimeError("private read failure")
        return self.reconciliation

    def write_reconciliation(self, receipt) -> None:
        if self.reconciliation_write_error:
            raise RuntimeError("private write failure")
        if self.reconciliation is not None:
            raise _service().ImmutableLifecycleStateExists()
        self.reconciliation = receipt
        self.reconciliation_writes.append(receipt)

    def read_outcome(self):
        if self.read_error:
            raise RuntimeError("private read failure")
        return self.outcome

    def write_outcome(self, outcome) -> None:
        if self.outcome_write_error:
            raise RuntimeError("private write failure")
        if self.outcome is not None:
            raise _service().ImmutableLifecycleStateExists()
        self.outcome = outcome
        self.outcome_writes.append(outcome)


class Runner:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        return _service().CommandResult(0, json.dumps(self.payload), "")


def _history(status: str) -> list[dict[str, str]]:
    return [
        {
            "id": RUN_ID,
            "status": status,
            "start_time": "2026-07-19T10:00:00Z",
        }
    ]


def test_cli_exposes_mutually_exclusive_live_reconcile_blocked_trigger() -> None:
    script = importlib.import_module(
        "scripts.run_hosted_foundry_agent_verification"
    )

    args = script._parse_args(
        [
            "--live-reconcile-blocked-trigger",
            "--resource-group",
            "fictional-rg",
            "--web-app-name",
            "fictional-web-app",
            "--config",
            ".env.daily-azure.local",
            "--readiness-receipt",
            ".artifacts/daily-azure-rebuild/readiness-receipt.json",
            "--json",
        ]
    )

    assert args.live_reconcile_blocked_trigger is True


def test_valid_current_blocked_context_can_enter_reconciliation() -> None:
    store = MemoryStore(blocked=_blocked())
    runner = Runner([])

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=runner,
        receipt_store=store,
    )

    assert result.category == "correlated_run_not_observed"
    assert result.blocked_trigger_valid is True
    assert result.reconciliation_attempted is True


def test_reconciliation_constructs_only_one_history_runner_and_reads_once() -> None:
    store = MemoryStore(blocked=_blocked())
    runner = Runner([])
    constructed = []

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner_factory=lambda: constructed.append("history") or runner,
        receipt_store=store,
    )

    assert result.category == "correlated_run_not_observed"
    assert constructed == ["history"]
    assert len(runner.calls) == 1
    assert "log" in runner.calls[0]
    assert "run" not in runner.calls[0]


def test_one_nonterminal_run_persists_private_reconciliation_receipt() -> None:
    service = _service()
    store = MemoryStore(blocked=_blocked())

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=Runner(_history("Running")),
        receipt_store=store,
    )

    assert result.category == "correlated_run_nonterminal"
    assert result.reconciliation_receipt_valid is True
    assert len(store.reconciliation_writes) == 1
    assert store.reconciliation.run_id == RUN_ID


def test_one_terminal_run_persists_reconciliation_before_terminal_outcome() -> None:
    service = _service()
    store = MemoryStore(blocked=_blocked())

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=Runner(_history("Success")),
        receipt_store=store,
    )

    assert result.category == "success"
    assert result.reconciliation_receipt_valid is True
    assert result.terminal_outcome_recorded is True
    assert len(store.reconciliation_writes) == 1
    assert len(store.outcome_writes) == 1


def test_status_can_continue_from_exact_reconciled_run_without_accepted_receipt() -> None:
    service = _service()
    blocked = _blocked()
    reconciliation = service.ReconciliationReceipt.from_blocked_trigger(
        blocked,
        run_id=RUN_ID,
        run_start_time=NOW,
    )
    store = MemoryStore(blocked=blocked, reconciliation=reconciliation)
    runner = Runner(
        [
            {
                "id": "unrelated-later-run",
                "status": "Success",
                "start_time": "2026-07-19T10:00:01Z",
            },
            *_history("Running"),
        ]
    )

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner=runner,
        receipt_store=store,
    )

    assert result.category == "correlated_run_nonterminal"
    assert result.reconciliation_receipt_valid is True
    assert len(runner.calls) == 1


@pytest.mark.parametrize(
    ("store", "execution_request", "category"),
    [
        (MemoryStore(), _request("live-reconcile-blocked-trigger"), "blocked_trigger_invalid"),
        (
            MemoryStore(blocked=replace(_blocked(), schema_version=1)),
            _request("live-reconcile-blocked-trigger"),
            "blocked_trigger_invalid",
        ),
        (
            MemoryStore(blocked=replace(_blocked(), state="unknown")),
            _request("live-reconcile-blocked-trigger"),
            "blocked_trigger_invalid",
        ),
        (
            MemoryStore(blocked=replace(_blocked(), resource_group="other-rg")),
            _request("live-reconcile-blocked-trigger"),
            "blocked_trigger_invalid",
        ),
        (
            MemoryStore(blocked=replace(_blocked(), web_app_name="other-app")),
            _request("live-reconcile-blocked-trigger"),
            "blocked_trigger_invalid",
        ),
        (
            MemoryStore(blocked=replace(_blocked(), webjob_name="other-job")),
            _request("live-reconcile-blocked-trigger"),
            "blocked_trigger_invalid",
        ),
        (
            MemoryStore(
                blocked=replace(_blocked(), environment_fingerprint="b" * 64)
            ),
            _request("live-reconcile-blocked-trigger"),
            "environment_evidence_stale",
        ),
        (
            MemoryStore(accepted=_accepted(), blocked=_blocked()),
            _request("live-reconcile-blocked-trigger"),
            "reconciliation_receipt_conflict",
        ),
        (
            MemoryStore(outcome=_outcome(succeeded=True), blocked=_blocked()),
            _request("live-reconcile-blocked-trigger"),
            "terminal_outcome_invalid",
        ),
        (
            MemoryStore(read_error=True),
            _request("live-reconcile-blocked-trigger"),
            "blocked_trigger_invalid",
        ),
    ],
)
def test_local_reconciliation_failures_stop_before_runner_construction(
    store: MemoryStore,
    execution_request,
    category: str,
) -> None:
    constructed = []

    result = _service().execute_hosted_foundry_agent_webjob(
        execution_request,
        runner_factory=lambda: constructed.append(True),
        receipt_store=store,
    )

    assert result.category == category
    assert result.azure_operation_attempted is False
    assert result.reconciliation_attempted is False
    assert constructed == []


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        ([], "correlated_run_not_observed"),
        (
            [
                {
                    "id": "old-run",
                    "status": "Success",
                    "start_time": "2026-07-19T09:59:59Z",
                }
            ],
            "correlated_run_not_observed",
        ),
        (
            [
                *_history("Running"),
                {
                    "id": "second-run",
                    "status": "Success",
                    "start_time": "2026-07-19T10:00:01Z",
                },
            ],
            "correlated_run_ambiguous",
        ),
        (
            [
                {
                    "id": RUN_ID,
                    "status": "Future",
                    "start_time": "2026-07-19T10:00:00Z",
                }
            ],
            "response_parse_failed",
        ),
        ({"runs": []}, "response_parse_failed"),
        (
            [
                {
                    "id": RUN_ID,
                    "status": "Running",
                    "start_time": "not-a-time",
                }
            ],
            "response_parse_failed",
        ),
    ],
)
def test_unresolved_ambiguous_and_malformed_history_persists_no_evidence(
    payload: object,
    category: str,
) -> None:
    store = MemoryStore(blocked=_blocked())
    runner = Runner(payload)

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=runner,
        receipt_store=store,
    )

    assert result.category == category
    assert result.reconciliation_attempted is True
    assert result.reconciliation_receipt_valid is False
    assert store.reconciliation is None
    assert store.outcome is None
    assert len(runner.calls) == 1
    assert "triggered" in runner.calls[0]
    assert "log" in runner.calls[0]
    assert "run" not in runner.calls[0]
    if category == "correlated_run_not_observed":
        assert "reconciliation read" in result.recommended_next_step
        assert "Do not trigger again" in result.recommended_next_step


def test_runs_before_lower_bound_are_ignored_when_one_eligible_run_exists() -> None:
    store = MemoryStore(blocked=_blocked())
    runner = Runner(
        [
            {
                "id": "old-run",
                "status": "Success",
                "start_time": "2026-07-19T09:59:59Z",
            },
            *_history("Running"),
        ]
    )

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=runner,
        receipt_store=store,
    )

    assert result.category == "correlated_run_nonterminal"
    assert store.reconciliation.run_id == RUN_ID


@pytest.mark.parametrize(
    ("status", "category", "succeeded"),
    [
        ("Success", "success", True),
        ("Failed", "correlated_run_failed", False),
        ("Error", "correlated_run_failed", False),
        ("Aborted", "correlated_run_failed", False),
    ],
)
def test_terminal_reconciliation_records_matching_immutable_outcome(
    status: str,
    category: str,
    succeeded: bool,
) -> None:
    store = MemoryStore(blocked=_blocked())

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=Runner(_history(status)),
        receipt_store=store,
    )

    assert result.category == category
    assert result.reconciled_run_terminal is True
    assert result.reconciled_run_succeeded is succeeded
    assert result.terminal_outcome_recorded is True
    assert store.outcome == _outcome(succeeded=succeeded)
    assert result.metadata_verification_proven is False
    assert result.invocation_attempted is False


def test_reconciliation_persistence_failure_is_sanitized_and_preserves_blocked() -> None:
    blocked = _blocked()
    store = MemoryStore(
        blocked=blocked,
        reconciliation_write_error=True,
    )

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=Runner(_history("Running")),
        receipt_store=store,
    )

    assert result.category == "reconciliation_receipt_persistence_failed"
    assert store.blocked == blocked
    assert store.reconciliation is None
    rendered = json.dumps(result.to_json_dict())
    for forbidden in (
        RUN_ID,
        "fictional-rg",
        "fictional-web-app",
        FINGERPRINT,
        "private write failure",
        "2026-07-19",
    ):
        assert forbidden not in rendered


def test_conflicting_reconciliation_is_not_overwritten_or_read_remotely() -> None:
    conflicting = replace(
        _reconciliation(), blocked_trigger_digest="b" * 64
    )
    store = MemoryStore(
        blocked=_blocked(),
        reconciliation=conflicting,
    )
    constructed = []

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=store,
    )

    assert result.category == "reconciliation_receipt_conflict"
    assert store.reconciliation == conflicting
    assert constructed == []


def test_repeated_reconciliation_reuses_nonterminal_receipt_without_history_read() -> None:
    receipt = _reconciliation(status="Running")
    store = MemoryStore(blocked=_blocked(), reconciliation=receipt)
    constructed = []

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=store,
    )

    assert result.category == "correlated_run_nonterminal"
    assert result.reconciliation_receipt_valid is True
    assert result.azure_operation_attempted is False
    assert constructed == []
    assert store.reconciliation == receipt


def test_repeated_terminal_reconciliation_reuses_receipt_and_outcome_without_read() -> None:
    receipt = _reconciliation(status="Success")
    store = MemoryStore(
        blocked=_blocked(),
        reconciliation=receipt,
        outcome=_outcome(succeeded=True),
    )
    constructed = []

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=store,
    )

    assert result.category == "success"
    assert result.terminal_outcome_recorded is True
    assert result.azure_operation_attempted is False
    assert constructed == []


def test_status_rejects_reconciliation_without_original_blocked_trigger() -> None:
    constructed = []
    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=MemoryStore(reconciliation=_reconciliation()),
    )

    assert result.category == "reconciliation_receipt_invalid"
    assert constructed == []


def test_status_rejects_both_accepted_and_reconciliation_receipts() -> None:
    constructed = []
    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=MemoryStore(
            accepted=_accepted(),
            blocked=_blocked(),
            reconciliation=_reconciliation(),
        ),
    )

    assert result.category == "reconciliation_receipt_conflict"
    assert constructed == []


def test_status_selects_only_exact_reconciled_run_and_records_terminal_once() -> None:
    store = MemoryStore(
        blocked=_blocked(),
        reconciliation=_reconciliation(),
    )
    runner = Runner(
        [
            {
                "id": "unrelated-later-run",
                "status": "Failed",
                "start_time": "2026-07-19T10:00:01Z",
            },
            *_history("Success"),
        ]
    )

    first = _service().execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner=runner,
        receipt_store=store,
    )
    constructed = []
    repeated = _service().execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=store,
    )

    assert first.category == "success"
    assert first.terminal_outcome_recorded is True
    assert repeated.category == "success"
    assert repeated.azure_operation_attempted is False
    assert constructed == []
    assert len(store.outcome_writes) == 1
    assert first.metadata_verification_proven is False
    assert first.invocation_attempted is False


def test_file_reconciliation_receipt_is_private_atomic_and_immutable(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)
    blocked = _blocked()
    receipt = _reconciliation()
    store.write_blocked(blocked)
    blocked_path = tmp_path / service.TRIGGER_BLOCKED_RELATIVE_PATH
    blocked_before = blocked_path.read_bytes()

    store.write_reconciliation(receipt)

    path = tmp_path / service.RECONCILIATION_RECEIPT_RELATIVE_PATH
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert store.read_reconciliation() == receipt
    assert blocked_path.read_bytes() == blocked_before
    assert list(path.parent.glob("*.tmp")) == []
    with pytest.raises(service.ImmutableLifecycleStateExists):
        store.write_reconciliation(receipt)


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2},
        {"state": "unknown"},
        {"run_id": ""},
        {"run_start_time": "2026-07-19T09:59:59Z"},
        {"observed_status": "Future"},
        {"blocked_trigger_digest": "not-a-digest"},
        {"extra": True},
    ],
)
def test_file_store_rejects_malformed_reconciliation_receipt(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    service = _service()
    path = tmp_path / service.RECONCILIATION_RECEIPT_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    payload = _reconciliation().to_json_dict()
    payload.update(mutation)
    path.write_text(json.dumps(payload))

    with pytest.raises(service.TriggerReceiptError):
        service.FileTriggerReceiptStore(tmp_path).read_reconciliation()


def test_malformed_reconciliation_receipt_stops_before_history_runner(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)
    store.write_blocked(_blocked())
    path = tmp_path / service.RECONCILIATION_RECEIPT_RELATIVE_PATH
    path.write_text("{not-json")
    constructed = []

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=store,
    )

    assert result.category == "reconciliation_receipt_invalid"
    assert constructed == []


def test_file_store_rejects_symlinked_reconciliation_target(
    tmp_path: Path,
) -> None:
    service = _service()
    state = tmp_path / service.TRIGGER_STATE_DIRECTORY
    state.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(_reconciliation().to_json_dict()))
    (tmp_path / service.RECONCILIATION_RECEIPT_RELATIVE_PATH).symlink_to(
        outside
    )

    with pytest.raises(service.TriggerReceiptError):
        service.FileTriggerReceiptStore(tmp_path).read_reconciliation()


def test_file_store_rejects_nonregular_reconciliation_target(
    tmp_path: Path,
) -> None:
    service = _service()
    (tmp_path / service.RECONCILIATION_RECEIPT_RELATIVE_PATH).mkdir(
        parents=True
    )

    with pytest.raises(service.TriggerReceiptError):
        service.FileTriggerReceiptStore(tmp_path).read_reconciliation()


@pytest.mark.parametrize("evidence_kind", ["malformed", "symlink", "nonregular"])
def test_malformed_symlinked_or_nonregular_blocked_evidence_stops_before_runner(
    tmp_path: Path,
    evidence_kind: str,
) -> None:
    service = _service()
    path = tmp_path / service.TRIGGER_BLOCKED_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    if evidence_kind == "malformed":
        path.write_text("{not-json")
    elif evidence_kind == "symlink":
        outside = tmp_path / "outside-blocked.json"
        outside.write_text(json.dumps(_blocked().to_json_dict()))
        path.symlink_to(outside)
    else:
        path.mkdir()
    constructed = []

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=service.FileTriggerReceiptStore(tmp_path),
    )

    assert result.category == "blocked_trigger_invalid"
    assert result.azure_operation_attempted is False
    assert constructed == []


def test_symlinked_state_directory_stops_reconciliation_before_runner(
    tmp_path: Path,
) -> None:
    service = _service()
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".artifacts").mkdir()
    (tmp_path / service.TRIGGER_STATE_DIRECTORY).symlink_to(
        outside, target_is_directory=True
    )
    constructed = []

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=service.FileTriggerReceiptStore(tmp_path),
    )

    assert result.category == "blocked_trigger_invalid"
    assert constructed == []


def test_terminal_outcome_persistence_failure_keeps_reconciliation_receipt() -> None:
    store = MemoryStore(
        blocked=_blocked(),
        outcome_write_error=True,
    )

    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=Runner(_history("Success")),
        receipt_store=store,
    )

    assert result.category == "terminal_outcome_persistence_failed"
    assert result.reconciliation_receipt_valid is True
    assert store.reconciliation == _reconciliation(status="Success")
    assert store.outcome is None


def test_status_records_reconciled_terminal_failure_once() -> None:
    store = MemoryStore(
        blocked=_blocked(),
        reconciliation=_reconciliation(),
    )

    first = _service().execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner=Runner(_history("Failed")),
        receipt_store=store,
    )
    constructed = []
    repeated = _service().execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner_factory=lambda: constructed.append(True),
        receipt_store=store,
    )

    assert first.category == "correlated_run_failed"
    assert first.terminal_outcome_recorded is True
    assert repeated.category == "correlated_run_failed"
    assert repeated.azure_operation_attempted is False
    assert len(store.outcome_writes) == 1
    assert constructed == []


def test_reconciliation_never_changes_blocked_evidence_or_authorizes_retrigger(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)
    store.write_blocked(_blocked())
    blocked_path = tmp_path / service.TRIGGER_BLOCKED_RELATIVE_PATH
    before = blocked_path.read_bytes()

    reconciled = service.execute_hosted_foundry_agent_webjob(
        _request("live-reconcile-blocked-trigger"),
        runner=Runner(_history("Running")),
        receipt_store=store,
    )
    trigger_constructed = []
    retrigger = service.execute_hosted_foundry_agent_webjob(
        _request("live-trigger"),
        runner_factory=lambda: trigger_constructed.append(True),
        receipt_store=store,
    )

    assert reconciled.reconciliation_receipt_valid is True
    assert blocked_path.read_bytes() == before
    assert retrigger.category == "trigger_blocked"
    assert trigger_constructed == []


def test_offline_recovery_recognizes_and_archives_reconciled_terminal_state(
    tmp_path: Path,
) -> None:
    service = _service()
    recovery = importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_state_recovery"
    )
    store = service.FileTriggerReceiptStore(tmp_path)
    store.write_blocked(_blocked())
    store.write_reconciliation(_reconciliation(status="Success"))
    store.write_outcome(_outcome(succeeded=True))
    inspect_request = recovery.HostedWebJobStateRecoveryRequest(
        mode="inspect",
        source_root=tmp_path,
        expected_environment_fingerprint=FINGERPRINT,
    )

    inspected = recovery.inspect_hosted_webjob_state(inspect_request)
    assert inspected.ok is True
    assert inspected.state == "terminal-success"
    assert inspected.manifest_digest is not None
    archived = recovery.recover_hosted_webjob_state(
        recovery.HostedWebJobStateRecoveryRequest(
            mode="archive",
            source_root=tmp_path,
            expected_environment_fingerprint=FINGERPRINT,
            manifest_digest=inspected.manifest_digest,
            reason="completed_generation_retirement",
        ),
        now=lambda: datetime(2026, 7, 29, 12, tzinfo=timezone.utc),
    )

    assert archived.ok is True
    assert archived.state == "archived"
    assert not (tmp_path / service.TRIGGER_STATE_DIRECTORY).exists()
