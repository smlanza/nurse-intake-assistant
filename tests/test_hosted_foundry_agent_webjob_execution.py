from dataclasses import replace
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc)


def _service():
    return importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_execution"
    )


def _request(mode: str = "check", *, source_root: Path = ROOT):
    return _service().HostedFoundryAgentWebJobExecutionRequest(
        mode=mode,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        source_root=source_root,
    )


def _receipt(*, state: str = "accepted", started: datetime = NOW):
    service = _service()
    return service.TriggerReceipt(
        schema_version=service.TRIGGER_RECEIPT_SCHEMA_VERSION,
        state=state,
        trigger_not_before=started,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        webjob_name=service.WEBJOB_NAME,
    )


def _outcome(*, succeeded: bool = True, started: datetime = NOW):
    service = _service()
    return service.TerminalOutcome(
        schema_version=service.TERMINAL_OUTCOME_SCHEMA_VERSION,
        state="terminal-success" if succeeded else "terminal-failure",
        trigger_not_before=started,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        webjob_name=service.WEBJOB_NAME,
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
    )


class MemoryStore:
    def __init__(
        self,
        receipt=None,
        *,
        blocked=None,
        outcome=None,
        reservation=False,
        read_error=False,
        write_error=False,
        blocked_write_error=False,
        outcome_write_error=False,
    ) -> None:
        self.receipt = receipt
        self.blocked = blocked
        self.outcome = outcome
        self.reservation = reservation
        self.read_error = read_error
        self.write_error = write_error
        self.blocked_write_error = blocked_write_error
        self.outcome_write_error = outcome_write_error
        self.writes = []
        self.blocked_writes = []
        self.outcome_writes = []

    def acquire_reservation(self):
        if self.reservation:
            return None
        self.reservation = True
        return _service().TriggerReservation(1, 1)

    def release_reservation(self, reservation) -> None:
        assert reservation == _service().TriggerReservation(1, 1)
        self.reservation = False

    def reservation_exists(self) -> bool:
        return self.reservation

    def read(self):
        if self.read_error:
            raise RuntimeError("sensitive receipt failure")
        return self.receipt

    def write(self, receipt) -> None:
        if self.write_error:
            raise RuntimeError("sensitive receipt failure")
        if self.receipt is not None:
            raise RuntimeError("immutable receipt exists")
        self.receipt = receipt
        self.writes.append(receipt)

    def read_blocked(self):
        if self.read_error:
            raise RuntimeError("sensitive blocked failure")
        return self.blocked

    def write_blocked(self, blocked) -> None:
        if self.blocked_write_error:
            raise RuntimeError("sensitive blocked failure")
        if self.blocked is not None:
            raise RuntimeError("immutable blocked state exists")
        self.blocked = blocked
        self.blocked_writes.append(blocked)

    def read_outcome(self):
        if self.read_error:
            raise RuntimeError("sensitive outcome failure")
        return self.outcome

    def write_outcome(self, outcome) -> None:
        if self.outcome_write_error:
            raise RuntimeError("sensitive outcome failure")
        if self.outcome is not None:
            raise RuntimeError("immutable outcome exists")
        self.outcome = outcome
        self.outcome_writes.append(outcome)


class FakeRunner:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self.result = result or _service().CommandResult(0, "{}", "")
        self.error = error
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.result


def _execute(mode: str, runner: FakeRunner, store: MemoryStore | None = None):
    return _service().execute_hosted_foundry_agent_webjob(
        _request(mode),
        runner=runner,
        receipt_store=store or MemoryStore(),
        clock=lambda: NOW,
    )


def _status_payload(*rows: tuple[str, datetime]) -> str:
    return json.dumps(
        [
            {
                "status": status,
                "start_time": started.isoformat().replace("+00:00", "Z"),
            }
            for status, started in rows
        ]
    )


def test_check_proves_only_local_contract_without_runner_or_remote_claim() -> None:
    runner = FakeRunner(error=AssertionError("check must stay offline"))

    result = _execute("check", runner)

    assert result.ok is True
    assert result.local_entrypoint_present is True
    assert result.remote_webjob_discovered is False
    assert result.configuration_contract_valid is True
    assert result.package_contract_valid is True
    assert result.azure_operation_attempted is False
    assert result.trigger_request_accepted is False
    assert result.trigger_receipt_valid is False
    assert result.correlated_run_observed is False
    assert result.metadata_verification_proven is False
    assert result.invocation_attempted is False
    assert runner.calls == []


def test_discovery_uses_exactly_one_narrow_read_and_ignores_unrelated_jobs() -> None:
    service = _service()
    runner = FakeRunner(
        service.CommandResult(
            0,
            json.dumps(
                [{"name": "unrelated"}, {"name": service.WEBJOB_NAME}]
            ),
            "raw stderr",
        )
    )

    result = _execute("live-discover", runner)

    assert runner.calls == [[
        "az", "webapp", "webjob", "triggered", "list",
        "--resource-group", "fictional-rg",
        "--name", "fictional-web-app",
        "--query", "[].{name:name}",
        "--only-show-errors", "--output", "json",
    ]]
    assert result.ok is True
    assert result.remote_webjob_discovered is True
    assert result.trigger_request_accepted is False


@pytest.mark.parametrize(
    ("payload", "category"),
    [
        ("not-json", "response_parse_failed"),
        ("{}", "response_parse_failed"),
        ("[]", "remote_webjob_missing"),
        ('[{"name":"other"}]', "remote_webjob_missing"),
        (
            '[{"name":"verify-hosted-foundry-agent"},'
            '{"name":"verify-hosted-foundry-agent"}]',
            "remote_webjob_ambiguous",
        ),
        ('[{"name":"verify-hosted-foundry-agent","extra":true}]', "response_parse_failed"),
    ],
)
def test_discovery_fails_closed_for_missing_ambiguous_or_malformed_results(
    payload: str,
    category: str,
) -> None:
    result = _execute(
        "live-discover",
        FakeRunner(_service().CommandResult(0, payload, "secret")),
    )

    assert result.ok is False
    assert result.category == category
    assert result.remote_webjob_discovered is False


def test_trigger_acceptance_writes_exact_contextual_utc_receipt_atomically_bounded() -> None:
    service = _service()
    store = MemoryStore()
    runner = FakeRunner(service.CommandResult(0, "{}", ""))

    result = _execute("live-trigger", runner, store)

    assert runner.calls == [[
        "az", "webapp", "webjob", "triggered", "run",
        "--resource-group", "fictional-rg",
        "--name", "fictional-web-app",
        "--webjob-name", service.WEBJOB_NAME,
        "--only-show-errors", "--output", "json",
    ]]
    assert result.ok is True
    assert result.trigger_request_accepted is True
    assert result.trigger_receipt_valid is True
    assert result.correlated_run_observed is False
    assert result.metadata_verification_proven is False
    assert store.writes == [_receipt()]


def test_generic_nonzero_trigger_result_creates_blocked_state_and_prevents_retry() -> None:
    service = _service()
    store = MemoryStore()
    first = _execute(
        "live-trigger",
        FakeRunner(
            service.CommandResult(
                1,
                "sensitive raw response",
                "connection reset after request submission",
            )
        ),
        store,
    )
    created: list[bool] = []
    second = service.execute_hosted_foundry_agent_webjob(
        _request("live-trigger"),
        runner_factory=lambda: created.append(True),
        receipt_store=store,
        clock=lambda: NOW,
    )

    assert first.category == "trigger_acceptance_ambiguous"
    assert first.trigger_request_accepted is False
    assert first.trigger_blocked is True
    assert first.metadata_verification_proven is False
    assert store.writes == []
    assert store.reservation is False
    assert store.blocked == _blocked()
    assert second.category == "trigger_blocked"
    assert second.trigger_request_accepted is False
    assert created == []


@pytest.mark.parametrize(
    "runner",
    [
        FakeRunner(error=TimeoutError("sensitive timeout")),
        FakeRunner(error=RuntimeError("sensitive runner failure")),
        FakeRunner(_service().CommandResult(0, "", "sensitive stderr")),
        FakeRunner(_service().CommandResult(0, "not-json", "sensitive stderr")),
        FakeRunner(
            _service().CommandResult(
                0,
                '{"unknown":"response-shape"}',
                "sensitive stderr",
            )
        ),
    ],
)
def test_every_unvalidated_post_run_trigger_result_creates_sanitized_blocked_state(
    runner: FakeRunner,
) -> None:
    store = MemoryStore()

    result = _execute("live-trigger", runner, store)

    assert result.category == "trigger_acceptance_ambiguous"
    assert result.trigger_request_accepted is False
    assert result.trigger_blocked is True
    assert result.trigger_receipt_valid is False
    assert result.metadata_verification_proven is False
    assert store.blocked == _blocked()
    assert store.reservation is False
    rendered = json.dumps(result.to_json_dict())
    for forbidden in (
        "sensitive",
        "timeout",
        "runner failure",
        "response-shape",
        "fictional-rg",
        "fictional-web-app",
        "2026-07-19",
        "blocked-trigger.json",
        "return_code",
    ):
        assert forbidden not in rendered


def test_ambiguous_trigger_blocked_write_failure_preserves_reservation() -> None:
    store = MemoryStore(blocked_write_error=True)

    first = _execute(
        "live-trigger",
        FakeRunner(_service().CommandResult(1, "", "sensitive failure")),
        store,
    )
    retry_runner = FakeRunner()
    second = _execute("live-trigger", retry_runner, store)

    assert first.category == "trigger_lifecycle_critical"
    assert first.trigger_request_accepted is False
    assert first.trigger_reservation_active is True
    assert first.trigger_blocked is False
    assert store.reservation is True
    assert second.category == "trigger_reservation_active"
    assert retry_runner.calls == []


def test_proven_process_not_started_releases_reservation_for_later_explicit_attempt() -> None:
    service = _service()
    store = MemoryStore()

    first = _execute(
        "live-trigger",
        FakeRunner(error=service.AzureCliProcessNotStarted()),
        store,
    )
    second = _execute("live-trigger", FakeRunner(), store)

    assert first.category == "azure_cli_unavailable"
    assert first.trigger_request_accepted is False
    assert first.trigger_blocked is False
    assert first.trigger_reservation_active is False
    assert store.blocked is None
    assert second.trigger_request_accepted is True
    assert len(store.writes) == 1


def test_trigger_receipt_write_failure_preserves_accepted_request_distinction() -> None:
    store = MemoryStore(write_error=True)
    result = _execute(
        "live-trigger",
        FakeRunner(_service().CommandResult(0, "{}", "")),
        store,
    )

    assert result.category == "trigger_receipt_persistence_failed"
    assert result.trigger_request_accepted is True
    assert result.trigger_receipt_valid is False
    assert result.trigger_blocked is True
    assert result.metadata_verification_proven is False
    assert store.blocked is not None
    assert store.reservation is False


def test_receipt_and_blocked_write_failure_preserves_exclusive_reservation() -> None:
    store = MemoryStore(write_error=True, blocked_write_error=True)

    first = _execute(
        "live-trigger",
        FakeRunner(_service().CommandResult(0, "{}", "")),
        store,
    )
    second_runner = FakeRunner()
    second = _execute("live-trigger", second_runner, store)

    assert first.category == "trigger_lifecycle_critical"
    assert first.trigger_request_accepted is True
    assert first.trigger_reservation_active is True
    assert store.reservation is True
    assert second.category == "trigger_reservation_active"
    assert second_runner.calls == []


def test_existing_blocked_marker_stops_trigger_before_runner_construction() -> None:
    created: list[bool] = []
    result = _service().execute_hosted_foundry_agent_webjob(
        _request("live-trigger"),
        runner_factory=lambda: created.append(True),
        receipt_store=MemoryStore(blocked=_blocked()),
    )

    assert result.category == "trigger_blocked"
    assert result.trigger_blocked is True
    assert result.azure_operation_attempted is False
    assert created == []


def test_unresolved_receipt_blocks_retrigger_before_runner_construction() -> None:
    created: list[bool] = []
    service = _service()

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-trigger"),
        runner_factory=lambda: created.append(True),
        receipt_store=MemoryStore(_receipt()),
        clock=lambda: NOW,
    )

    assert result.category == "trigger_receipt_unresolved"
    assert result.trigger_receipt_valid is True
    assert result.azure_operation_attempted is False
    assert created == []


def test_terminal_outcome_does_not_allow_retrigger_or_overwrite_evidence() -> None:
    receipt = _receipt(started=NOW - timedelta(days=1))
    outcome = _outcome(started=NOW - timedelta(days=1))
    store = MemoryStore(receipt, outcome=outcome)

    result = _execute(
        "live-trigger",
        FakeRunner(_service().CommandResult(0, "{}", "")),
        store,
    )

    assert result.category == "trigger_receipt_unresolved"
    assert result.azure_operation_attempted is False
    assert store.receipt == receipt
    assert store.outcome == outcome
    assert store.writes == []


def test_status_uses_receipt_lower_bound_and_records_separate_terminal_success() -> None:
    service = _service()
    store = MemoryStore(_receipt())
    runner = FakeRunner(
        service.CommandResult(
            0,
            _status_payload(
                ("Failed", NOW - timedelta(seconds=1)),
                ("Success", NOW + timedelta(seconds=1)),
            ),
            "raw stderr",
        )
    )

    result = _execute("live-status", runner, store)

    assert runner.calls == [[
        "az", "webapp", "webjob", "triggered", "log",
        "--resource-group", "fictional-rg",
        "--name", "fictional-web-app",
        "--webjob-name", service.WEBJOB_NAME,
        "--query", "[].runs[] | [].{status:status,start_time:startTime}",
        "--only-show-errors", "--output", "json",
    ]]
    assert result.ok is True
    assert result.trigger_request_accepted is False
    assert result.trigger_receipt_valid is True
    assert result.correlated_run_observed is True
    assert result.correlated_run_terminal is True
    assert result.correlated_run_succeeded is True
    assert result.metadata_verification_proven is True
    assert store.receipt == _receipt()
    assert store.outcome == _outcome()
    assert result.terminal_outcome_recorded is True


@pytest.mark.parametrize(
    ("payload", "category", "observed", "terminal", "succeeded"),
    [
        (_status_payload(("Success", datetime(2020, 1, 1, tzinfo=timezone.utc))), "correlated_run_not_observed", False, False, False),
        (_status_payload(("Success", NOW - timedelta(microseconds=1))), "correlated_run_not_observed", False, False, False),
        ("[]", "correlated_run_not_observed", False, False, False),
        (_status_payload(("Running", NOW)), "correlated_run_nonterminal", True, False, False),
        (_status_payload(("Failed", NOW)), "correlated_run_failed", True, True, False),
        (_status_payload(("Success", NOW), ("Failed", NOW + timedelta(seconds=1))), "correlated_run_ambiguous", False, False, False),
        ("not-json", "response_parse_failed", False, False, False),
        ('[{"status":"Future","start_time":"2026-07-19T10:00:00Z"}]', "response_parse_failed", False, False, False),
        ('[{"status":"Success","start_time":"not-a-time"}]', "response_parse_failed", False, False, False),
    ],
)
def test_status_correlation_fails_closed(
    payload: str,
    category: str,
    observed: bool,
    terminal: bool,
    succeeded: bool,
) -> None:
    store = MemoryStore(_receipt())

    result = _execute(
        "live-status",
        FakeRunner(_service().CommandResult(0, payload, "secret")),
        store,
    )

    assert result.ok is False
    assert result.category == category
    assert result.correlated_run_observed is observed
    assert result.correlated_run_terminal is terminal
    assert result.correlated_run_succeeded is succeeded
    assert result.metadata_verification_proven is False
    assert store.receipt == _receipt()
    assert store.outcome == (_outcome(succeeded=succeeded) if terminal else None)


@pytest.mark.parametrize(
    ("store", "category"),
    [
        (MemoryStore(), "trigger_receipt_missing"),
        (MemoryStore(read_error=True), "trigger_receipt_invalid"),
        (MemoryStore(_receipt(state="resolved")), "trigger_receipt_invalid"),
        (MemoryStore(outcome=_outcome()), "terminal_outcome_invalid"),
        (
            MemoryStore(
                _receipt(),
                outcome=replace(_outcome(), web_app_name="different-app"),
            ),
            "terminal_outcome_invalid",
        ),
        (
            MemoryStore(replace(_receipt(), web_app_name="different-app")),
            "trigger_receipt_invalid",
        ),
        (
            MemoryStore(replace(_receipt(), resource_group="different-rg")),
            "trigger_receipt_invalid",
        ),
    ],
)
def test_missing_malformed_resolved_or_mismatched_receipt_stops_before_runner(
    store: MemoryStore,
    category: str,
) -> None:
    created: list[bool] = []
    service = _service()

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner_factory=lambda: created.append(True),
        receipt_store=store,
    )

    assert result.category == category
    assert result.azure_operation_attempted is False
    assert created == []


def test_terminal_status_outcome_write_failure_fails_safe_without_success_proof() -> None:
    result = _execute(
        "live-status",
        FakeRunner(_service().CommandResult(0, _status_payload(("Success", NOW)), "")),
        MemoryStore(_receipt(), outcome_write_error=True),
    )

    assert result.category == "terminal_outcome_persistence_failed"
    assert result.correlated_run_observed is True
    assert result.correlated_run_terminal is True
    assert result.correlated_run_succeeded is False
    assert result.metadata_verification_proven is False


def test_conflicting_terminal_outcome_creation_fails_closed_without_overwrite() -> None:
    class ConflictingStore(MemoryStore):
        def write_outcome(self, outcome) -> None:
            self.outcome = _outcome(succeeded=False)
            raise _service().ImmutableLifecycleStateExists()

    store = ConflictingStore(_receipt())
    result = _execute(
        "live-status",
        FakeRunner(_service().CommandResult(0, _status_payload(("Success", NOW)), "")),
        store,
    )

    assert result.category == "terminal_outcome_conflict"
    assert result.metadata_verification_proven is False
    assert store.receipt == _receipt()
    assert store.outcome == _outcome(succeeded=False)


def test_file_receipt_store_uses_fixed_path_strict_schema_and_atomic_permissions(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)

    store.write(_receipt())

    path = tmp_path / service.TRIGGER_RECEIPT_RELATIVE_PATH
    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o600
    assert json.loads(path.read_text()) == _receipt().to_json_dict()
    assert list(path.parent.glob("*.tmp")) == []
    assert store.read() == _receipt()


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2},
        {"state": "unknown"},
        {"trigger_not_before": "2026-07-19T10:00:00"},
        {"web_app_name": "/unsafe"},
        {"webjob_name": "other-job"},
        {"extra": True},
    ],
)
def test_file_receipt_store_rejects_malformed_receipts(
    tmp_path: Path,
    mutation: dict[str, object],
) -> None:
    service = _service()
    path = tmp_path / service.TRIGGER_RECEIPT_RELATIVE_PATH
    path.parent.mkdir(parents=True)
    payload = _receipt().to_json_dict()
    payload.update(mutation)
    path.write_text(json.dumps(payload))

    with pytest.raises(service.TriggerReceiptError):
        service.FileTriggerReceiptStore(tmp_path).read()


def test_failures_are_sanitized_never_retry_and_result_projection_is_unambiguous() -> None:
    runner = FakeRunner(error=RuntimeError("secret token path"))

    result = _execute("live-discover", runner)

    assert len(runner.calls) == 1
    rendered = json.dumps(result.to_json_dict())
    assert "secret" not in rendered
    assert "fictional-rg" not in rendered
    assert "fictional-web-app" not in rendered
    assert "webjob_present" not in rendered
    assert set(result.to_json_dict()) == {
        "ok", "mode", "category", "message", "local_entrypoint_present",
        "remote_webjob_discovered", "configuration_contract_valid",
        "package_contract_valid", "azure_operation_attempted",
        "trigger_request_accepted", "trigger_reservation_active",
        "trigger_receipt_valid", "trigger_blocked",
        "correlated_run_observed", "correlated_run_terminal",
        "correlated_run_succeeded", "terminal_outcome_recorded",
        "metadata_verification_proven",
        "invocation_attempted", "recommended_next_step",
    }
