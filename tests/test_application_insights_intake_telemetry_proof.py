import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.app.application_composition import compose_application
from src.app.config.settings import AppSettings
from src.app.models.intake_telemetry import INTAKE_TELEMETRY_OPERATION
from src.app.services.application_insights_intake_telemetry_proof import (
    ALLOWLISTED_DIMENSIONS,
    FIXED_FICTIONAL_INTAKE,
    QUERY_PROJECTED_COLUMNS,
    TELEMETRY_QUERY_MAX_SECONDS,
    ApplicationInsightsIntakeTelemetryProof,
    CommandResult,
    build_check_result,
    build_telemetry_query,
)
from src.app.services.daily_azure_environment_rebuild import (
    RESOURCE_GROUP_PURPOSE,
    DailyAzureConfig,
    DailyAzureReadinessReceipt,
)


SUBSCRIPTION_ID = "11111111-1111-4111-8111-111111111111"
TENANT_ID = "22222222-2222-4222-8222-222222222222"
RESOURCE_GROUP = "fictional-daily-rg"
APP_NAME = "fictional-appi"
APP_ID = "33333333-3333-4333-8333-333333333333"
RESOURCE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/"
    f"providers/Microsoft.Insights/components/{APP_NAME}"
)
WORKSPACE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/"
    "providers/Microsoft.OperationalInsights/workspaces/fictional-logs"
)
CONNECTION_STRING = "InstrumentationKey=44444444-4444-4444-8444-444444444444"
LOWER = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)


def _config() -> DailyAzureConfig:
    return DailyAzureConfig(
        subscription_name="Fictional Subscription",
        location="centralus",
        resource_group=RESOURCE_GROUP,
        environment_name="daily",
        project_name="nurse-intake",
        foundry_account_name="fictional-foundry",
        foundry_project_name="fictional-project",
        model_deployment_name="fictional-model",
        model_name="gpt-5-mini",
        model_version="2025-08-07",
        model_sku="GlobalStandard",
        model_capacity=1,
        agent_name="fictional-agent",
        web_app_name="fictional-web-app",
        web_app_sku="B1",
        enable_hosted_foundry_verifier=True,
        discover_hosted_foundry_webjob=True,
    )


def _receipt() -> DailyAzureReadinessReceipt:
    return DailyAzureReadinessReceipt(
        schema_version=4,
        operation="rebuild_daily_azure_environment",
        ready=True,
        configuration_fingerprint="a" * 64,
        run_epoch="b" * 32,
        correlation_fingerprint="c" * 64,
        requested_foundry_account_name="fictional-foundry",
        foundry_account_name="fictional-foundry",
        foundry_account_name_generated=False,
        foundry_account_name_generation_attempts=0,
        foundry_account_name_conflicts=(),
        resource_group=RESOURCE_GROUP,
        foundry_project_name="fictional-project",
        web_app_name="fictional-web-app",
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 10.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


class FakeTelemetryClient:
    events: list[tuple[str, dict[str, object]]] = []
    flush_error: Exception | None = None

    def __init__(self, instrumentation_key: str) -> None:
        assert instrumentation_key

    def track_event(self, name: str, properties: dict[str, object]) -> None:
        self.events.append((name, properties))

    def flush(self) -> None:
        if self.flush_error is not None:
            raise self.flush_error


class FakeRunner:
    def __init__(self, query_payloads: list[object] | None = None) -> None:
        self.calls: list[tuple[list[str], float | None]] = []
        self.query_payloads = list(query_payloads or [])
        self.query_count = 0
        self.query_duration = 0.0
        self.clock: FakeClock | None = None
        self.resource_name = APP_NAME

    def run(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        self.calls.append((list(args), timeout_seconds))
        joined = " ".join(args)
        if args[:3] == ["az", "account", "show"]:
            return _result(
                {
                    "id": SUBSCRIPTION_ID,
                    "tenantId": TENANT_ID,
                    "subscription": "Fictional Subscription",
                    "state": "Enabled",
                    "isDefault": True,
                }
            )
        if args[:3] == ["az", "group", "show"]:
            return _result(
                {
                    "location": "centralus",
                    "provisioningState": "Succeeded",
                    "ownershipTag": RESOURCE_GROUP_PURPOSE,
                }
            )
        if args[:3] == ["az", "resource", "list"]:
            return _result(
                [
                    {
                        "id": RESOURCE_ID,
                        "name": self.resource_name,
                        "type": "Microsoft.Insights/components",
                        "location": "centralus",
                    }
                ]
            )
        if args[:3] == ["az", "resource", "show"]:
            if "connectionString" in joined:
                return _result(
                    {
                        "id": RESOURCE_ID,
                        "name": self.resource_name,
                        "appId": APP_ID,
                        "connectionString": CONNECTION_STRING,
                    }
                )
            return _result(
                {
                    "id": RESOURCE_ID,
                    "name": self.resource_name,
                    "type": "Microsoft.Insights/components",
                    "kind": "web",
                    "location": "centralus",
                    "provisioningState": "Succeeded",
                    "workspaceResourceId": WORKSPACE_ID,
                }
            )
        if args[:2] == ["az", "rest"]:
            self.query_count += 1
            if self.clock is not None:
                self.clock.value += self.query_duration
            payload = self.query_payloads.pop(0) if self.query_payloads else []
            return _result(payload)
        raise AssertionError(f"Unexpected fake command kind: {args[:3]}")


def _result(payload: object) -> CommandResult:
    return CommandResult(0, json.dumps(payload), "")


def _query_response(
    properties: dict[str, object],
    *,
    timestamp: datetime = LOWER + timedelta(seconds=1),
    rows: int = 1,
) -> dict[str, object]:
    return {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "timestamp", "type": "datetime"},
                    {"name": "name", "type": "string"},
                    {"name": "customDimensions", "type": "dynamic"},
                ],
                "rows": [
                    [
                        timestamp.isoformat().replace("+00:00", "Z"),
                        INTAKE_TELEMETRY_OPERATION,
                        properties,
                    ]
                    for _ in range(rows)
                ],
            }
        ]
    }


def _proof(
    monkeypatch: pytest.MonkeyPatch,
    runner: FakeRunner,
    *,
    approver=lambda summary: True,
    receipt_loader=lambda path, config: _receipt(),
    clock: FakeClock | None = None,
) -> ApplicationInsightsIntakeTelemetryProof:
    import src.app.services.azure_monitor_intake_telemetry as adapter

    FakeTelemetryClient.events = []
    FakeTelemetryClient.flush_error = None
    monkeypatch.setattr(adapter, "_get_telemetry_client_class", lambda: FakeTelemetryClient)
    proof_clock = clock or FakeClock()
    runner.clock = proof_clock
    return ApplicationInsightsIntakeTelemetryProof(
        config=_config(),
        readiness_receipt=_receipt(),
        readiness_receipt_path=Path(".artifacts/daily-azure-rebuild/readiness-receipt.json"),
        runner=runner,
        approver=approver,
        receipt_loader=receipt_loader,
        compose=compose_application,
        monotonic_clock=proof_clock.monotonic,
        utc_now=lambda: LOWER,
        sleep=proof_clock.sleep,
    )


def _run_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    query_payloads: list[object] | None = None,
) -> tuple[object, FakeRunner]:
    runner = FakeRunner(query_payloads=[])
    proof = _proof(monkeypatch, runner)
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"] and not runner.query_payloads:
            properties = FakeTelemetryClient.events[0][1]
            runner.query_payloads.append(_query_response(properties))
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]
    if query_payloads is not None:
        runner.query_payloads = list(query_payloads)
    return proof.run_live(), runner


def test_check_contract_is_deterministic_and_has_no_side_effects() -> None:
    first = build_check_result(
        config=_config(),
        readiness_receipt=_receipt(),
        readiness_receipt_path=Path(".artifacts/daily-azure-rebuild/readiness-receipt.json"),
        sdk_available=True,
        cli_available=True,
    )
    second = build_check_result(
        config=_config(),
        readiness_receipt=_receipt(),
        readiness_receipt_path=Path(".artifacts/daily-azure-rebuild/readiness-receipt.json"),
        sdk_available=True,
        cli_available=True,
    )

    assert first == second
    assert first.ok is True
    assert first.mode == "check"
    assert first.intake_attempted is False
    assert first.telemetry_emission_count == 0
    assert first.query_attempted is False


def test_query_projection_is_narrow_and_contains_no_sensitive_content() -> None:
    query = build_telemetry_query(
        LOWER,
        LOWER + timedelta(seconds=TELEMETRY_QUERY_MAX_SECONDS),
    )

    assert QUERY_PROJECTED_COLUMNS == ("timestamp", "name", "customDimensions")
    assert "project timestamp, name, customDimensions" in query
    assert INTAKE_TELEMETRY_OPERATION in query
    for forbidden in (
        "message",
        "operation_Id",
        "user_Id",
        "session_Id",
        "cloud_RoleName",
        "client_IP",
        "PATIENT_SECRET_SENTINEL",
        "PHONE_SECRET_SENTINEL",
    ):
        assert forbidden not in query


def test_success_uses_production_composition_and_one_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, runner = _run_success(monkeypatch)

    assert result.ok is True
    assert result.production_composition_used is True
    assert result.intake_attempted is True
    assert result.case_persisted_in_memory is True
    assert result.notifications_suppressed is True
    assert result.telemetry_provider_verified is True
    assert result.telemetry_emission_attempted is True
    assert result.telemetry_emission_count == 1
    assert result.eligible_record_count == 1
    assert result.telemetry_record_verified is True
    assert len(FakeTelemetryClient.events) == 1
    assert runner.query_count == 1


def test_production_composition_receives_exact_safe_posture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[AppSettings] = []
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)
    proof.compose = lambda settings: captured.append(settings) or compose_application(settings)
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            runner.query_payloads.append(_query_response(FakeTelemetryClient.events[0][1]))
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.ok is True
    assert len(captured) == 1
    settings = captured[0]
    assert settings.app_mode == "mock"
    assert settings.ai_provider_normalized == "mock"
    assert settings.agent_provider_normalized == "mock"
    assert settings.speech_provider_normalized == "mock"
    assert settings.email_provider_normalized == "mock"
    assert settings.sms_provider_normalized == "mock"
    assert settings.demo_suppress_notifications is True
    assert settings.telemetry_provider_normalized == "azure-monitor"


def test_proof_processes_exactly_one_fixed_intake_through_composed_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    process_calls: list[tuple[str, str]] = []
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)

    def tracked_compose(settings: AppSettings):
        application = compose_application(settings)
        original_process = application.case_processing_service.process

        async def process(raw_text: str, case_type: str):
            process_calls.append((raw_text, case_type))
            return await original_process(raw_text, case_type)

        application.case_processing_service.process = process  # type: ignore[method-assign]
        return application

    proof.compose = tracked_compose
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            runner.query_payloads.append(
                _query_response(FakeTelemetryClient.events[0][1])
            )
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.ok is True
    assert process_calls == [(FIXED_FICTIONAL_INTAKE, "text-intake")]
    assert len(FakeTelemetryClient.events) == 1


def test_approval_decline_stops_before_configuration_composition_or_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner, approver=lambda summary: False)
    proof.compose = lambda settings: pytest.fail("composition must not run")

    result = proof.run_live()

    assert result.category == "approval_declined"
    assert result.intake_attempted is False
    assert result.query_attempted is False
    assert FakeTelemetryClient.events == []


def test_changed_readiness_after_approval_stops_before_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def load(path: Path, config: DailyAzureConfig):
        nonlocal calls
        calls += 1
        return _receipt() if calls == 1 else None

    runner = FakeRunner()
    proof = _proof(monkeypatch, runner, receipt_loader=load)
    proof.compose = lambda settings: pytest.fail("composition must not run")

    result = proof.run_live()

    assert result.category == "approval_evidence_stale"
    assert result.telemetry_emission_count == 0
    assert result.query_attempted is False


def test_resource_mismatch_fails_before_approval_or_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approvals: list[object] = []
    runner = FakeRunner()
    runner.resource_name = "wrong-resource"
    proof = _proof(monkeypatch, runner, approver=lambda summary: approvals.append(summary))

    result = proof.run_live()

    assert result.category == "application_insights_resource_mismatch"
    assert approvals == []
    assert FakeTelemetryClient.events == []


def test_account_identity_mismatch_fails_before_resource_reads_or_emission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        result = original_run(args, timeout_seconds=timeout_seconds)
        if args[:3] == ["az", "account", "show"]:
            payload = json.loads(result.stdout)
            payload["subscription"] = "Wrong Subscription"
            return _result(payload)
        return result

    runner.run = run  # type: ignore[method-assign]
    proof = _proof(monkeypatch, runner)

    result = proof.run_live()

    assert result.category == "account_verification_failed"
    assert all(args[:3] != ["az", "resource", "list"] for args, _ in runner.calls)
    assert FakeTelemetryClient.events == []


def test_ambiguous_application_insights_resources_fail_before_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:3] == ["az", "resource", "list"]:
            candidate = {
                "id": RESOURCE_ID,
                "name": APP_NAME,
                "type": "Microsoft.Insights/components",
                "location": "centralus",
            }
            return _result([candidate, candidate])
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]
    proof = _proof(monkeypatch, runner)

    result = proof.run_live()

    assert result.category == "application_insights_resource_ambiguous"
    assert FakeTelemetryClient.events == []


def test_resource_evidence_changed_after_approval_stops_before_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()

    def approve(summary: object) -> bool:
        runner.resource_name = "changed-after-approval"
        return True

    proof = _proof(monkeypatch, runner, approver=approve)
    proof.compose = lambda settings: pytest.fail("composition must not run")

    result = proof.run_live()

    assert result.category == "approval_evidence_stale"
    assert result.telemetry_emission_count == 0


def test_zero_results_poll_without_reemission_then_one_result_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(query_payloads=[])
    proof = _proof(monkeypatch, runner)
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            if runner.query_count == 0:
                runner.query_payloads.append({"tables": [{"name": "PrimaryResult", "columns": [
                    {"name": "timestamp", "type": "datetime"},
                    {"name": "name", "type": "string"},
                    {"name": "customDimensions", "type": "dynamic"},
                ], "rows": []}]})
            else:
                runner.query_payloads.append(_query_response(FakeTelemetryClient.events[0][1]))
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.ok is True
    assert runner.query_count == 2
    assert len(FakeTelemetryClient.events) == 1
    assert runner.clock is not None and runner.clock.sleeps


def test_multiple_eligible_results_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            runner.query_payloads.append(
                _query_response(FakeTelemetryClient.events[0][1], rows=2)
            )
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.category == "telemetry_record_ambiguous"
    assert result.eligible_record_count == 2
    assert len(FakeTelemetryClient.events) == 1


@pytest.mark.parametrize(
    ("mutate", "category"),
    [
        (lambda properties: {k: v for k, v in properties.items() if k != "sms_status"}, "telemetry_contract_mismatch"),
        (lambda properties: {**properties, "extra": "unsafe"}, "telemetry_contract_mismatch"),
        (lambda properties: {**properties, "final_urgency": "SECRET_VALUE"}, "telemetry_record_invalid"),
    ],
)
def test_invalid_dimensions_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    mutate,
    category: str,
) -> None:
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            runner.query_payloads.append(
                _query_response(mutate(FakeTelemetryClient.events[0][1]))
            )
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.category == category
    assert result.ok is False


def test_out_of_window_result_is_discarded_and_polling_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            timestamp = LOWER - timedelta(seconds=1) if runner.query_count == 0 else LOWER + timedelta(seconds=1)
            runner.query_payloads.append(
                _query_response(FakeTelemetryClient.events[0][1], timestamp=timestamp)
            )
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.ok is True
    assert runner.query_count == 2
    assert len(FakeTelemetryClient.events) == 1


def test_result_returned_at_deadline_cannot_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClock()
    runner = FakeRunner()
    runner.query_duration = TELEMETRY_QUERY_MAX_SECONDS
    proof = _proof(monkeypatch, runner, clock=clock)
    original_run = runner.run

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            runner.query_payloads.append(_query_response(FakeTelemetryClient.events[0][1]))
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.category == "telemetry_ingestion_timeout"
    assert result.telemetry_record_verified is False


def test_valid_empty_results_poll_until_single_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)
    original_run = runner.run
    empty = {
        "tables": [
            {
                "name": "PrimaryResult",
                "columns": [
                    {"name": "timestamp", "type": "datetime"},
                    {"name": "name", "type": "string"},
                    {"name": "customDimensions", "type": "dynamic"},
                ],
                "rows": [],
            }
        ]
    }

    def run(args: list[str], *, timeout_seconds: float | None = None):
        if args[:2] == ["az", "rest"]:
            runner.query_payloads.append(empty)
        return original_run(args, timeout_seconds=timeout_seconds)

    runner.run = run  # type: ignore[method-assign]

    result = proof.run_live()

    assert result.category == "telemetry_ingestion_timeout"
    assert runner.query_count > 1
    assert len(FakeTelemetryClient.events) == 1
    assert sum(runner.clock.sleeps) == TELEMETRY_QUERY_MAX_SECONDS


def test_malformed_query_output_fails_without_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(query_payloads=[{"tables": "malformed"}])
    proof = _proof(monkeypatch, runner)

    result = proof.run_live()

    assert result.category == "response_parse_failed"
    assert runner.query_count == 1
    assert len(FakeTelemetryClient.events) == 1


def test_query_timeouts_share_one_absolute_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner(query_payloads=[{"tables": [{"name": "PrimaryResult", "columns": [
        {"name": "timestamp", "type": "datetime"},
        {"name": "name", "type": "string"},
        {"name": "customDimensions", "type": "dynamic"},
    ], "rows": []}]}] * 2)
    runner.query_duration = 7.0
    proof = _proof(monkeypatch, runner)

    result = proof.run_live()

    query_timeouts = [timeout for args, timeout in runner.calls if args[:2] == ["az", "rest"]]
    assert result.ok is False
    assert len(query_timeouts) >= 2
    assert query_timeouts[0] == TELEMETRY_QUERY_MAX_SECONDS
    assert all(later < earlier for earlier, later in zip(query_timeouts, query_timeouts[1:]))


def test_telemetry_flush_failure_is_sanitized_and_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)
    FakeTelemetryClient.flush_error = RuntimeError("EXCEPTION_SECRET_SENTINEL")

    result = proof.run_live()

    assert result.category == "telemetry_emission_failed"
    assert result.telemetry_emission_count == 0
    assert result.query_attempted is False
    assert len(FakeTelemetryClient.events) == 1
    assert "EXCEPTION_SECRET_SENTINEL" not in json.dumps(result.to_json_dict())


def test_application_failure_remains_primary_over_telemetry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = FakeRunner()
    proof = _proof(monkeypatch, runner)

    def compose_with_failure(settings: AppSettings):
        application = compose_application(settings)

        async def fail(raw_text: str):
            raise RuntimeError("PRIMARY_EXCEPTION_SECRET_SENTINEL")

        application.ai_service.extract_and_summarize = fail  # type: ignore[method-assign]
        return application

    proof.compose = compose_with_failure
    FakeTelemetryClient.flush_error = RuntimeError("TELEMETRY_EXCEPTION_SECRET_SENTINEL")

    result = proof.run_live()

    assert result.category == "intake_processing_failed"
    assert result.query_attempted is False
    serialized = json.dumps(result.to_json_dict())
    assert "PRIMARY_EXCEPTION_SECRET_SENTINEL" not in serialized
    assert "TELEMETRY_EXCEPTION_SECRET_SENTINEL" not in serialized


def test_sensitive_values_never_enter_result_query_or_runner_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, runner = _run_success(monkeypatch)
    serialized = json.dumps(result.to_json_dict(), sort_keys=True)
    all_args = json.dumps([args for args, timeout in runner.calls])

    for sentinel in (
        "PATIENT_SECRET_SENTINEL",
        "PHONE_SECRET_SENTINEL",
        "SUMMARY_SECRET_SENTINEL",
        "PROMPT_SECRET_SENTINEL",
        "EXCEPTION_SECRET_SENTINEL",
        "ENDPOINT_SECRET_SENTINEL",
    ):
        assert sentinel not in serialized
        assert sentinel not in all_args
    assert set(FakeTelemetryClient.events[0][1]) == ALLOWLISTED_DIMENSIONS
    assert "PATIENT_SECRET_SENTINEL" in FIXED_FICTIONAL_INTAKE
    assert "PHONE_SECRET_SENTINEL" in FIXED_FICTIONAL_INTAKE
