from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import threading

import pytest

from tests.test_web_app_bicep import _compile


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc)
FINGERPRINT = "a" * 64


def _service():
    return importlib.import_module(
        "src.app.services.hosted_foundry_agent_webjob_execution"
    )


def _request(mode: str):
    return _service().HostedFoundryAgentWebJobExecutionRequest(
        mode=mode,
        resource_group="fictional-rg",
        web_app_name="fictional-web-app",
        source_root=ROOT,
        environment_fingerprint=None if mode == "check" else FINGERPRINT,
    )


def _receipt():
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


def _outcome(*, succeeded: bool = True):
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


def test_concurrent_trigger_attempts_share_one_exclusive_filesystem_reservation(
    tmp_path: Path,
) -> None:
    service = _service()
    first_runner_entered = threading.Event()
    release_runner = threading.Event()
    call_lock = threading.Lock()
    calls: list[list[str]] = []
    results: list[object] = []

    class BlockingRunner:
        def run(self, args: list[str]):
            with call_lock:
                calls.append(args)
                first_runner_entered.set()
            assert release_runner.wait(timeout=5)
            return service.CommandResult(0, "{}", "")

    def execute() -> None:
        results.append(
            service.execute_hosted_foundry_agent_webjob(
                _request("live-trigger"),
                runner=BlockingRunner(),
                receipt_store=service.FileTriggerReceiptStore(tmp_path),
                clock=lambda: NOW,
            )
        )

    first = threading.Thread(target=execute)
    second = threading.Thread(target=execute)
    first.start()
    assert first_runner_entered.wait(timeout=5)
    second.start()
    second.join(timeout=1)
    release_runner.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert len(calls) == 1
    assert len(results) == 2
    assert sum(result.trigger_request_accepted for result in results) == 1


def test_terminal_status_keeps_accepted_receipt_byte_for_byte_immutable(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)
    store.write(_receipt())
    receipt_path = tmp_path / service.TRIGGER_RECEIPT_RELATIVE_PATH
    before = receipt_path.read_bytes()

    class Runner:
        def run(self, args: list[str]):
            return service.CommandResult(
                0,
                json.dumps(
                    [{"status": "Success", "start_time": "2026-07-19T10:00:00Z"}]
                ),
                "",
            )

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner=Runner(),
        receipt_store=store,
    )

    assert result.metadata_verification_proven is True
    assert result.invocation_attempted is True
    assert receipt_path.read_bytes() == before


@pytest.mark.parametrize(
    ("payload", "terminal"),
    [
        ([], False),
        ([{"status": "Running", "start_time": "2026-07-19T10:00:00Z"}], False),
        (
            [
                {"status": "Success", "start_time": "2026-07-19T10:00:00Z"},
                {"status": "Failed", "start_time": "2026-07-19T10:00:01Z"},
            ],
            False,
        ),
        ([{"status": "Failed", "start_time": "2026-07-19T10:00:00Z"}], True),
    ],
)
def test_every_status_outcome_leaves_accepted_receipt_immutable(
    tmp_path: Path,
    payload: list[dict[str, str]],
    terminal: bool,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)
    store.write(_receipt())
    receipt_path = tmp_path / service.TRIGGER_RECEIPT_RELATIVE_PATH
    before = receipt_path.read_bytes()

    class Runner:
        def run(self, args: list[str]):
            return service.CommandResult(0, json.dumps(payload), "")

    result = service.execute_hosted_foundry_agent_webjob(
        _request("live-status"), runner=Runner(), receipt_store=store
    )

    assert receipt_path.read_bytes() == before
    assert result.terminal_outcome_recorded is terminal
    assert store.read_outcome() == (_outcome(succeeded=False) if terminal else None)


def test_repeated_terminal_status_reuses_immutable_outcome_without_runner(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)
    store.write(_receipt())

    class SuccessRunner:
        def run(self, args: list[str]):
            return service.CommandResult(
                0,
                '[{"status":"Success","start_time":"2026-07-19T10:00:00Z"}]',
                "",
            )

    first = service.execute_hosted_foundry_agent_webjob(
        _request("live-status"), runner=SuccessRunner(), receipt_store=store
    )
    receipt_path = tmp_path / service.TRIGGER_RECEIPT_RELATIVE_PATH
    outcome_path = tmp_path / service.TERMINAL_OUTCOME_RELATIVE_PATH
    receipt_bytes = receipt_path.read_bytes()
    outcome_bytes = outcome_path.read_bytes()
    created: list[bool] = []

    repeated = service.execute_hosted_foundry_agent_webjob(
        _request("live-status"),
        runner_factory=lambda: created.append(True),
        receipt_store=store,
    )

    assert first.metadata_verification_proven is True
    assert repeated.metadata_verification_proven is True
    assert first.invocation_attempted is True
    assert repeated.invocation_attempted is True
    assert repeated.terminal_outcome_recorded is True
    assert repeated.azure_operation_attempted is False
    assert created == []
    assert receipt_path.read_bytes() == receipt_bytes
    assert outcome_path.read_bytes() == outcome_bytes


def test_receipt_read_rejects_symlinked_artifacts_parent(tmp_path: Path) -> None:
    service = _service()
    outside = tmp_path / "outside"
    outside_state = outside / "hosted-foundry-agent-webjob"
    outside_state.mkdir(parents=True)
    (outside_state / service.TRIGGER_RECEIPT_RELATIVE_PATH.name).write_text(
        json.dumps(_receipt().to_json_dict())
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    (checkout / ".artifacts").symlink_to(outside, target_is_directory=True)

    with pytest.raises(service.TriggerReceiptError):
        service.FileTriggerReceiptStore(checkout).read()


def test_all_state_reads_reject_symlinked_state_directory(tmp_path: Path) -> None:
    service = _service()
    checkout = tmp_path / "checkout"
    outside = tmp_path / "outside"
    (checkout / ".artifacts").mkdir(parents=True)
    outside.mkdir()
    (checkout / service.TRIGGER_STATE_DIRECTORY).symlink_to(
        outside, target_is_directory=True
    )

    store = service.FileTriggerReceiptStore(checkout)
    for read in (store.read, store.read_blocked, store.read_outcome, store.reservation_exists):
        with pytest.raises(service.TriggerReceiptError):
            read()


@pytest.mark.parametrize(
    ("relative_path", "reader", "payload"),
    [
        ("TRIGGER_RECEIPT_RELATIVE_PATH", "read", lambda: _receipt().to_json_dict()),
        ("TRIGGER_BLOCKED_RELATIVE_PATH", "read_blocked", lambda: _blocked().to_json_dict()),
        ("TERMINAL_OUTCOME_RELATIVE_PATH", "read_outcome", lambda: _outcome().to_json_dict()),
        (
            "TRIGGER_RESERVATION_RELATIVE_PATH",
            "reservation_exists",
            lambda: {"schema_version": 1, "state": "in-progress"},
        ),
    ],
)
def test_all_state_reads_reject_symlinked_targets(
    tmp_path: Path,
    relative_path: str,
    reader: str,
    payload,
) -> None:
    service = _service()
    state = tmp_path / service.TRIGGER_STATE_DIRECTORY
    state.mkdir(parents=True)
    outside = tmp_path / f"outside-{reader}.json"
    outside.write_text(json.dumps(payload()))
    (tmp_path / getattr(service, relative_path)).symlink_to(outside)

    with pytest.raises(service.TriggerReceiptError):
        getattr(service.FileTriggerReceiptStore(tmp_path), reader)()


def test_state_read_rejects_nonregular_target(tmp_path: Path) -> None:
    service = _service()
    (tmp_path / service.TRIGGER_RECEIPT_RELATIVE_PATH).mkdir(parents=True)

    with pytest.raises(service.TriggerReceiptError):
        service.FileTriggerReceiptStore(tmp_path).read()


def test_active_reservation_and_blocked_state_each_stop_trigger_before_runner(
    tmp_path: Path,
) -> None:
    service = _service()
    store = service.FileTriggerReceiptStore(tmp_path)
    reservation = store.acquire_reservation()
    assert reservation is not None
    created: list[bool] = []

    active = service.execute_hosted_foundry_agent_webjob(
        _request("live-trigger"),
        runner_factory=lambda: created.append(True),
        receipt_store=service.FileTriggerReceiptStore(tmp_path),
    )
    assert active.category == "trigger_reservation_active"
    assert active.trigger_reservation_active is True
    assert created == []
    store.release_reservation(reservation)

    store.write_blocked(_blocked())
    blocked = service.execute_hosted_foundry_agent_webjob(
        _request("live-trigger"),
        runner_factory=lambda: created.append(True),
        receipt_store=store,
    )
    assert blocked.category == "trigger_blocked"
    assert blocked.trigger_blocked is True
    assert created == []


def test_compiled_main_guards_raw_enabled_values_with_trimmed_min_length() -> None:
    compiled = _compile("main.bicep")
    web_app = compiled["resources"]["webApp"]
    value = compiled["variables"]["validatedHostedFoundryVerifierConfiguration"]
    enabled = web_app["properties"]["template"]["definitions"][
        "hostedFoundryVerifierEnabledConfiguration"
    ]["properties"]

    assert value.count("trim(") == 5
    assert value.count("equals(") >= 5
    for name in (
        "projectEndpoint",
        "agentEndpoint",
        "agentName",
        "agentVersion",
        "modelDeploymentName",
    ):
        parameter = f"parameters('hostedFoundryVerifierConfiguration').{name}"
        assert parameter in value
        assert f"trim({parameter})" in value
        assert enabled[name]["minLength"] == 1

    for raw_value in (
        "",
        " ",
        "\t",
        "\n",
        " \t\n ",
        " leading",
        "trailing ",
    ):
        guarded_value = raw_value if raw_value == raw_value.strip() else ""
        assert len(guarded_value) < 1
    assert ("approved" if "approved" == "approved".strip() else "") == "approved"
