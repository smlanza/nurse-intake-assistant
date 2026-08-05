import asyncio
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import time
from typing import Literal, Protocol

from src.app.application_composition import ApplicationComposition, compose_application
from src.app.config.settings import AppSettings
from src.app.models.intake_telemetry import (
    INTAKE_TELEMETRY_OPERATION,
    IntakeTelemetryEvent,
    build_intake_telemetry_event,
)
from src.app.services.azure_monitor_intake_telemetry import (
    AzureMonitorIntakeTelemetrySink,
)
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.daily_azure_environment_rebuild import (
    RESOURCE_GROUP_PURPOSE,
    DailyAzureConfig,
    DailyAzureReadinessReceipt,
)
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.intake_telemetry import IntakeTelemetrySink
from src.app.services.mock_ai_service import MockAiService
from src.app.services.sms_notification_sender import MockSmsNotificationSender


PROOF_OPERATION = "smoke_application_insights_intake_telemetry"
FIXED_FICTIONAL_INTAKE = (
    "My name is Avery Example. DOB: 2000-01-01. My callback number is "
    "000-000-0200. I need a medication refill. PATIENT_SECRET_SENTINEL "
    "PHONE_SECRET_SENTINEL. This is fixed fictional test data requiring "
    "human nurse review."
)
TELEMETRY_QUERY_MAX_SECONDS = 300.0
TELEMETRY_QUERY_POLL_SECONDS = 5.0
AZURE_READ_TIMEOUT_SECONDS = 30.0
QUERY_PROJECTED_COLUMNS = ("timestamp", "name", "customDimensions")
ALLOWLISTED_DIMENSIONS = frozenset(
    field.name for field in fields(IntakeTelemetryEvent)
)
SAFE_POSTURE = (
    ("APP_MODE", "mock"),
    ("AI_PROVIDER", "mock"),
    ("AGENT_PROVIDER", "mock"),
    ("SPEECH_PROVIDER", "mock"),
    ("EMAIL_PROVIDER", "mock"),
    ("SMS_PROVIDER", "mock"),
    ("DEMO_SUPPRESS_NOTIFICATIONS", "true"),
    ("TELEMETRY_PROVIDER", "azure-monitor"),
)

ProofMode = Literal["check", "live"]


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class AzureCliRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        ...


@dataclass(frozen=True)
class ApplicationInsightsIntakeTelemetryApprovalSummary:
    readiness_verified: bool
    account_verified: bool
    application_insights_resource_verified: bool
    fixed_fictional_input: bool
    safe_provider_posture: bool
    telemetry_emission_limit: int
    query_deadline_seconds: int
    infrastructure_mutation: bool


@dataclass(frozen=True)
class ApplicationInsightsIntakeTelemetryProofResult:
    ok: bool
    mode: ProofMode
    category: str
    fictional_input: bool = True
    readiness_verified: bool = False
    account_verified: bool = False
    application_insights_resource_verified: bool = False
    production_composition_used: bool = False
    intake_attempted: bool = False
    case_persisted_in_memory: bool = False
    notifications_suppressed: bool = False
    telemetry_provider_verified: bool = False
    telemetry_emission_attempted: bool = False
    telemetry_emission_count: int = 0
    query_attempted: bool = False
    eligible_record_count: int = 0
    telemetry_record_verified: bool = False
    allowlisted_dimensions_verified: bool = False
    unexpected_dimensions_absent: bool = False
    sensitive_content_absent: bool = False
    azure_mutation_made: bool = False
    recommended_next_step: str = "Review the sanitized failure and stop."

    def to_json_dict(self) -> dict[str, object]:
        return {"operation": PROOF_OPERATION, **asdict(self)}


@dataclass(frozen=True)
class _AccountEvidence:
    subscription_id: str
    tenant_id: str
    subscription_name: str


@dataclass(frozen=True)
class _ApplicationInsightsResourceEvidence:
    resource_id: str
    name: str
    location: str
    workspace_resource_id: str


@dataclass(frozen=True)
class _PrivateTelemetryConfiguration:
    resource_id: str
    name: str
    app_id: str
    connection_string: str


@dataclass(frozen=True)
class _QueryInspection:
    category: str
    eligible_record_count: int = 0
    verified: bool = False
    allowlisted_dimensions_verified: bool = False
    unexpected_dimensions_absent: bool = False
    sensitive_content_absent: bool = False


class _ProofTelemetrySink:
    def __init__(self, delegate: IntakeTelemetrySink) -> None:
        self.delegate = delegate
        self.attempt_count = 0
        self.emission_count = 0
        self.event: IntakeTelemetryEvent | None = None

    def record_intake_completed(self, event: IntakeTelemetryEvent) -> None:
        self.attempt_count += 1
        self.event = event
        self.delegate.record_intake_completed(event)
        self.emission_count += 1


def failure_result(
    category: str,
    mode: ProofMode,
    **changes: object,
) -> ApplicationInsightsIntakeTelemetryProofResult:
    values = {
        field.name: field.default
        for field in fields(ApplicationInsightsIntakeTelemetryProofResult)
        if field.name not in {"ok", "mode", "category"}
    }
    values.update(changes)
    return ApplicationInsightsIntakeTelemetryProofResult(
        ok=False,
        mode=mode,
        category=category,
        **values,
    )


def build_check_result(
    *,
    config: DailyAzureConfig,
    readiness_receipt: DailyAzureReadinessReceipt,
    readiness_receipt_path: Path,
    sdk_available: bool,
    cli_available: bool,
) -> ApplicationInsightsIntakeTelemetryProofResult:
    category = _local_contract_category(
        config,
        readiness_receipt,
        readiness_receipt_path,
        sdk_available=sdk_available,
        cli_available=cli_available,
    )
    if category != "success":
        return failure_result(category, "check")
    return ApplicationInsightsIntakeTelemetryProofResult(
        ok=True,
        mode="check",
        category="success",
        readiness_verified=True,
        notifications_suppressed=True,
        telemetry_provider_verified=True,
        allowlisted_dimensions_verified=True,
        unexpected_dimensions_absent=True,
        sensitive_content_absent=True,
        recommended_next_step=(
            "Run the supervised live proof only with current readiness and approval."
        ),
    )


def build_telemetry_query(lower: datetime, upper: datetime) -> str:
    if not _utc_datetime(lower) or not _utc_datetime(upper) or lower >= upper:
        raise ValueError("Telemetry query window is invalid")
    lower_text = lower.isoformat().replace("+00:00", "Z")
    upper_text = upper.isoformat().replace("+00:00", "Z")
    return (
        "customEvents\n"
        f"| where timestamp >= datetime({lower_text})\n"
        f"| where timestamp <= datetime({upper_text})\n"
        f'| where name == "{INTAKE_TELEMETRY_OPERATION}"\n'
        "| project timestamp, name, customDimensions"
    )


class ApplicationInsightsIntakeTelemetryProof:
    def __init__(
        self,
        *,
        config: DailyAzureConfig,
        readiness_receipt: DailyAzureReadinessReceipt,
        readiness_receipt_path: Path,
        runner: AzureCliRunner,
        approver: Callable[[ApplicationInsightsIntakeTelemetryApprovalSummary], bool],
        receipt_loader: Callable[
            [Path, DailyAzureConfig], DailyAzureReadinessReceipt | None
        ],
        compose: Callable[[AppSettings], ApplicationComposition] = compose_application,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.readiness_receipt = readiness_receipt
        self.readiness_receipt_path = readiness_receipt_path
        self.runner = runner
        self.approver = approver
        self.receipt_loader = receipt_loader
        self.compose = compose
        self.monotonic_clock = monotonic_clock
        self.utc_now = utc_now
        self.sleep = sleep

    def run_live(self) -> ApplicationInsightsIntakeTelemetryProofResult:
        current_receipt = self.receipt_loader(
            self.readiness_receipt_path,
            self.config,
        )
        if current_receipt != self.readiness_receipt:
            return failure_result("readiness_invalid", "live")
        if _local_contract_category(
            self.config,
            current_receipt,
            self.readiness_receipt_path,
            sdk_available=True,
            cli_available=True,
        ) != "success":
            return failure_result("invalid_configuration", "live")

        account = self._read_account()
        if account is None:
            return failure_result(
                "account_verification_failed",
                "live",
                readiness_verified=True,
            )
        resource, resource_category = self._read_owned_application_insights(
            account
        )
        if resource is None:
            return failure_result(
                resource_category,
                "live",
                readiness_verified=True,
                account_verified=True,
            )

        approved_binding = self._approval_binding(current_receipt, account, resource)
        summary = ApplicationInsightsIntakeTelemetryApprovalSummary(
            readiness_verified=True,
            account_verified=True,
            application_insights_resource_verified=True,
            fixed_fictional_input=True,
            safe_provider_posture=True,
            telemetry_emission_limit=1,
            query_deadline_seconds=int(TELEMETRY_QUERY_MAX_SECONDS),
            infrastructure_mutation=False,
        )
        if self.approver(summary) is not True:
            return failure_result(
                "approval_declined",
                "live",
                readiness_verified=True,
                account_verified=True,
                application_insights_resource_verified=True,
                notifications_suppressed=True,
                telemetry_provider_verified=True,
            )

        fresh_receipt = self.receipt_loader(
            self.readiness_receipt_path,
            self.config,
        )
        fresh_account = self._read_account()
        fresh_resource = None
        if fresh_account is not None:
            fresh_resource, _ = self._read_owned_application_insights(fresh_account)
        if (
            fresh_receipt is None
            or fresh_account is None
            or fresh_resource is None
            or self._approval_binding(
                fresh_receipt,
                fresh_account,
                fresh_resource,
            )
            != approved_binding
        ):
            return failure_result(
                "approval_evidence_stale",
                "live",
                readiness_verified=True,
                account_verified=True,
                application_insights_resource_verified=True,
                notifications_suppressed=True,
                telemetry_provider_verified=True,
            )

        private_config = self._read_private_configuration(fresh_resource)
        if private_config is None:
            return failure_result(
                "telemetry_configuration_failed",
                "live",
                readiness_verified=True,
                account_verified=True,
                application_insights_resource_verified=True,
            )
        return self._run_composed_proof(private_config)

    def _run_composed_proof(
        self,
        private_config: _PrivateTelemetryConfiguration,
    ) -> ApplicationInsightsIntakeTelemetryProofResult:
        base = failure_result(
            "application_composition_failed",
            "live",
            readiness_verified=True,
            account_verified=True,
            application_insights_resource_verified=True,
        )
        try:
            settings = _build_safe_settings(private_config.connection_string)
            application = self.compose(settings)
        except Exception:
            return base
        if not _composition_is_safe(application):
            return base

        service = application.case_processing_service
        tracking_sink = _ProofTelemetrySink(application.intake_telemetry_sink)
        service.telemetry_sink = tracking_sink
        lower = self.utc_now()
        if not _utc_datetime(lower):
            return replace(base, category="invalid_configuration")
        started_monotonic = self.monotonic_clock()
        deadline = started_monotonic + TELEMETRY_QUERY_MAX_SECONDS

        try:
            case = asyncio.run(
                service.process(FIXED_FICTIONAL_INTAKE, "text-intake")
            )
        except Exception:
            return replace(
                base,
                category="intake_processing_failed",
                production_composition_used=True,
                intake_attempted=True,
                telemetry_provider_verified=True,
                telemetry_emission_attempted=tracking_sink.attempt_count == 1,
                telemetry_emission_count=tracking_sink.emission_count,
            )

        persisted, notifications_suppressed = _terminal_application_state(
            application,
            case,
        )
        execution = replace(
            base,
            production_composition_used=True,
            intake_attempted=True,
            case_persisted_in_memory=persisted,
            notifications_suppressed=notifications_suppressed,
            telemetry_provider_verified=True,
            telemetry_emission_attempted=tracking_sink.attempt_count == 1,
            telemetry_emission_count=tracking_sink.emission_count,
        )
        if not persisted or not notifications_suppressed:
            return replace(execution, category="intake_processing_failed")
        if (
            tracking_sink.attempt_count != 1
            or tracking_sink.emission_count != 1
            or tracking_sink.event is None
        ):
            return replace(execution, category="telemetry_emission_failed")
        expected = tracking_sink.event.to_properties()
        if set(expected) != ALLOWLISTED_DIMENSIONS:
            return replace(execution, category="telemetry_contract_mismatch")
        upper = lower + timedelta(seconds=TELEMETRY_QUERY_MAX_SECONDS)
        return self._poll_for_record(
            execution,
            private_config,
            expected,
            lower,
            upper,
            deadline,
        )

    def _poll_for_record(
        self,
        base: ApplicationInsightsIntakeTelemetryProofResult,
        private_config: _PrivateTelemetryConfiguration,
        expected: dict[str, str | bool],
        lower: datetime,
        upper: datetime,
        deadline: float,
    ) -> ApplicationInsightsIntakeTelemetryProofResult:
        query = build_telemetry_query(lower, upper)
        query_attempted = False
        while True:
            before = self.monotonic_clock()
            remaining = deadline - before
            if remaining <= 0:
                return replace(
                    base,
                    category="telemetry_ingestion_timeout",
                    query_attempted=query_attempted,
                )
            query_attempted = True
            outcome = self.runner.run(
                _query_args(private_config.app_id, query),
                timeout_seconds=remaining,
            )
            returned_at = self.monotonic_clock()
            if returned_at >= deadline:
                return replace(
                    base,
                    category="telemetry_ingestion_timeout",
                    query_attempted=True,
                )
            if outcome.return_code != 0:
                return replace(
                    base,
                    category="telemetry_query_failed",
                    query_attempted=True,
                )
            inspection = _inspect_query_response(
                outcome.stdout,
                expected=expected,
                lower=lower,
                upper=upper,
            )
            if inspection.category != "no_eligible_record":
                return replace(
                    base,
                    ok=inspection.verified,
                    category=inspection.category,
                    query_attempted=True,
                    eligible_record_count=inspection.eligible_record_count,
                    telemetry_record_verified=inspection.verified,
                    allowlisted_dimensions_verified=(
                        inspection.allowlisted_dimensions_verified
                    ),
                    unexpected_dimensions_absent=(
                        inspection.unexpected_dimensions_absent
                    ),
                    sensitive_content_absent=inspection.sensitive_content_absent,
                    recommended_next_step=(
                        "Review the sanitized proof; hosted telemetry remains unproven."
                        if inspection.verified
                        else base.recommended_next_step
                    ),
                )
            remaining = deadline - self.monotonic_clock()
            if remaining <= 0:
                return replace(
                    base,
                    category="telemetry_ingestion_timeout",
                    query_attempted=True,
                )
            self.sleep(min(TELEMETRY_QUERY_POLL_SECONDS, remaining))

    def _read_account(self) -> _AccountEvidence | None:
        outcome = self.runner.run(
            [
                "az",
                "account",
                "show",
                "--query",
                "{id:id,tenantId:tenantId,subscription:name,state:state,isDefault:isDefault}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            timeout_seconds=AZURE_READ_TIMEOUT_SECONDS,
        )
        payload = _json_value(outcome.stdout) if outcome.return_code == 0 else None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"id", "tenantId", "subscription", "state", "isDefault"}
            or not _uuid(payload.get("id"))
            or not _uuid(payload.get("tenantId"))
            or payload.get("subscription") != self.config.subscription_name
            or payload.get("state") != "Enabled"
            or payload.get("isDefault") is not True
        ):
            return None
        return _AccountEvidence(
            subscription_id=payload["id"],
            tenant_id=payload["tenantId"],
            subscription_name=payload["subscription"],
        )

    def _read_owned_application_insights(
        self,
        account: _AccountEvidence,
    ) -> tuple[_ApplicationInsightsResourceEvidence | None, str]:
        group = self.runner.run(
            [
                "az",
                "group",
                "show",
                "--name",
                self.config.resource_group,
                "--query",
                "{location:location,provisioningState:properties.provisioningState,ownershipTag:tags.purpose}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            timeout_seconds=AZURE_READ_TIMEOUT_SECONDS,
        )
        group_payload = _json_value(group.stdout) if group.return_code == 0 else None
        if (
            not isinstance(group_payload, dict)
            or set(group_payload) != {"location", "provisioningState", "ownershipTag"}
            or not _location_matches(group_payload.get("location"), self.config.location)
            or group_payload.get("provisioningState") != "Succeeded"
            or group_payload.get("ownershipTag") != RESOURCE_GROUP_PURPOSE
        ):
            return None, "application_insights_resource_mismatch"

        listed = self.runner.run(
            [
                "az",
                "resource",
                "list",
                "--resource-group",
                self.config.resource_group,
                "--resource-type",
                "Microsoft.Insights/components",
                "--query",
                "[].{id:id,name:name,type:type,location:location}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            timeout_seconds=AZURE_READ_TIMEOUT_SECONDS,
        )
        resources = _json_value(listed.stdout) if listed.return_code == 0 else None
        if not isinstance(resources, list):
            return None, "application_insights_resource_not_found"
        if len(resources) == 0:
            return None, "application_insights_resource_not_found"
        if len(resources) != 1:
            return None, "application_insights_resource_ambiguous"
        candidate = resources[0]
        if not _listed_resource_valid(candidate, account, self.config):
            return None, "application_insights_resource_mismatch"

        shown = self.runner.run(
            [
                "az",
                "resource",
                "show",
                "--ids",
                candidate["id"],
                "--api-version",
                "2020-02-02",
                "--query",
                "{id:id,name:name,type:type,kind:kind,location:location,provisioningState:properties.provisioningState,workspaceResourceId:properties.WorkspaceResourceId}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            timeout_seconds=AZURE_READ_TIMEOUT_SECONDS,
        )
        payload = _json_value(shown.stdout) if shown.return_code == 0 else None
        if not _shown_resource_valid(payload, candidate, account, self.config):
            return None, "application_insights_resource_mismatch"
        return (
            _ApplicationInsightsResourceEvidence(
                resource_id=payload["id"],
                name=payload["name"],
                location=payload["location"],
                workspace_resource_id=payload["workspaceResourceId"],
            ),
            "success",
        )

    def _read_private_configuration(
        self,
        resource: _ApplicationInsightsResourceEvidence,
    ) -> _PrivateTelemetryConfiguration | None:
        outcome = self.runner.run(
            [
                "az",
                "resource",
                "show",
                "--ids",
                resource.resource_id,
                "--api-version",
                "2020-02-02",
                "--query",
                "{id:id,name:name,appId:properties.AppId,connectionString:properties.ConnectionString}",
                "--output",
                "json",
                "--only-show-errors",
            ],
            timeout_seconds=AZURE_READ_TIMEOUT_SECONDS,
        )
        payload = _json_value(outcome.stdout) if outcome.return_code == 0 else None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"id", "name", "appId", "connectionString"}
            or payload.get("id") != resource.resource_id
            or payload.get("name") != resource.name
            or not _uuid(payload.get("appId"))
            or not _nonblank(payload.get("connectionString"))
        ):
            return None
        return _PrivateTelemetryConfiguration(
            resource_id=payload["id"],
            name=payload["name"],
            app_id=payload["appId"],
            connection_string=payload["connectionString"],
        )

    def _approval_binding(
        self,
        receipt: DailyAzureReadinessReceipt,
        account: _AccountEvidence,
        resource: _ApplicationInsightsResourceEvidence,
    ) -> tuple[object, ...]:
        return (
            receipt,
            account,
            resource,
            _local_contract_binding(),
        )


def _local_contract_category(
    config: DailyAzureConfig,
    receipt: DailyAzureReadinessReceipt,
    receipt_path: Path,
    *,
    sdk_available: bool,
    cli_available: bool,
) -> str:
    if not _fixed_input_valid() or not _receipt_path_valid(receipt_path):
        return "invalid_configuration"
    if (
        receipt.ready is not True
        or receipt.resource_group != config.resource_group
        or receipt.foundry_project_name != config.foundry_project_name
        or receipt.web_app_name != config.web_app_name
    ):
        return "readiness_invalid"
    try:
        query = build_telemetry_query(
            datetime(2000, 1, 1, tzinfo=timezone.utc),
            datetime(2000, 1, 1, tzinfo=timezone.utc)
            + timedelta(seconds=TELEMETRY_QUERY_MAX_SECONDS),
        )
        sanitized = build_intake_telemetry_event(
            case=None,
            requested_case_type="text-intake",
            ai_provider="PATIENT_SECRET_SENTINEL",
            agent_provider="PHONE_SECRET_SENTINEL",
            agent_used=False,
            contract_valid=True,
            fallback_used=False,
            processing_succeeded=False,
            safe_failure_category="processing_failure",
            started_monotonic=0.0,
            finished_monotonic=0.1,
        ).to_properties()
    except Exception:
        return "invalid_configuration"
    if (
        tuple(query.rsplit("project ", 1)[-1].split(", "))
        != QUERY_PROJECTED_COLUMNS
        or set(IntakeTelemetryEvent.__dataclass_fields__) != ALLOWLISTED_DIMENSIONS
        or set(sanitized) != ALLOWLISTED_DIMENSIONS
        or any(
            sentinel in json.dumps(sanitized, sort_keys=True)
            for sentinel in ("PATIENT_SECRET_SENTINEL", "PHONE_SECRET_SENTINEL")
        )
        or not _safe_resource_name(config.resource_group)
        or not _safe_resource_name(config.project_name)
        or not _safe_resource_name(config.environment_name)
    ):
        return "invalid_configuration"
    if not sdk_available or not cli_available:
        return "telemetry_configuration_failed"
    return "success"


def _local_contract_binding() -> tuple[object, ...]:
    return (
        FIXED_FICTIONAL_INTAKE,
        tuple(sorted(ALLOWLISTED_DIMENSIONS)),
        QUERY_PROJECTED_COLUMNS,
        SAFE_POSTURE,
        TELEMETRY_QUERY_MAX_SECONDS,
        TELEMETRY_QUERY_POLL_SECONDS,
    )


def _fixed_input_valid() -> bool:
    return bool(
        "fixed fictional" in FIXED_FICTIONAL_INTAKE.casefold()
        and "PATIENT_SECRET_SENTINEL" in FIXED_FICTIONAL_INTAKE
        and "PHONE_SECRET_SENTINEL" in FIXED_FICTIONAL_INTAKE
        and "+1" not in FIXED_FICTIONAL_INTAKE
        and "555" not in FIXED_FICTIONAL_INTAKE
        and "@" not in FIXED_FICTIONAL_INTAKE
    )


def _receipt_path_valid(path: Path) -> bool:
    parts = path.parts
    expected = (".artifacts", "daily-azure-rebuild", "readiness-receipt.json")
    return ".." not in parts and tuple(parts[-3:]) == expected


def _composition_is_safe(application: object) -> bool:
    if not isinstance(application, ApplicationComposition):
        return False
    settings = application.settings
    service = application.case_processing_service
    return bool(
        settings.app_mode == "mock"
        and settings.ai_provider_normalized == "mock"
        and settings.agent_provider_normalized == "mock"
        and settings.speech_provider_normalized == "mock"
        and settings.email_provider_normalized == "mock"
        and settings.sms_provider_normalized == "mock"
        and settings.demo_suppress_notifications is True
        and settings.telemetry_provider_normalized == "azure-monitor"
        and type(application.ai_service) is MockAiService
        and type(application.case_repository) is InMemoryCaseRepository
        and type(application.email_notification_sender) is MockEmailNotificationSender
        and type(application.sms_notification_sender) is MockSmsNotificationSender
        and application.nurse_intake_agent is None
        and isinstance(application.intake_telemetry_sink, AzureMonitorIntakeTelemetrySink)
        and isinstance(service, CaseProcessingService)
        and service.telemetry_sink is application.intake_telemetry_sink
        and service.suppress_notifications is True
    )


def _terminal_application_state(
    application: ApplicationComposition,
    case: object,
) -> tuple[bool, bool]:
    stored = asyncio.run(application.case_repository.list_cases())
    persisted = len(stored) == 1 and stored[0] is case
    notifications_suppressed = bool(
        getattr(case, "notificationEmailStatus", None) == "Suppressed"
        and getattr(case, "notificationSmsStatus", None) == "Suppressed"
        and not application.email_notification_sender.sent_notifications
        and not application.sms_notification_sender.sent_notifications
    )
    return persisted, notifications_suppressed


def _inspect_query_response(
    raw: str,
    *,
    expected: dict[str, str | bool],
    lower: datetime,
    upper: datetime,
) -> _QueryInspection:
    payload = _json_value(raw)
    if not isinstance(payload, dict) or set(payload) != {"tables"}:
        return _QueryInspection("response_parse_failed")
    tables = payload.get("tables")
    if not isinstance(tables, list) or len(tables) != 1:
        return _QueryInspection("response_parse_failed")
    table = tables[0]
    expected_columns = [
        {"name": "timestamp", "type": "datetime"},
        {"name": "name", "type": "string"},
        {"name": "customDimensions", "type": "dynamic"},
    ]
    if (
        not isinstance(table, dict)
        or set(table) != {"name", "columns", "rows"}
        or table.get("name") != "PrimaryResult"
        or table.get("columns") != expected_columns
        or not isinstance(table.get("rows"), list)
    ):
        return _QueryInspection("response_parse_failed")

    eligible = 0
    for row in table["rows"]:
        if not isinstance(row, list) or len(row) != 3:
            return _QueryInspection("telemetry_record_invalid")
        timestamp = _parse_utc(row[0])
        name = row[1]
        dimensions = row[2]
        if timestamp is None or not isinstance(name, str):
            return _QueryInspection("telemetry_record_invalid")
        if timestamp < lower or timestamp > upper or name != INTAKE_TELEMETRY_OPERATION:
            continue
        if not isinstance(dimensions, dict):
            return _QueryInspection("telemetry_record_invalid")
        if set(dimensions) != ALLOWLISTED_DIMENSIONS:
            return _QueryInspection("telemetry_contract_mismatch")
        try:
            IntakeTelemetryEvent(**dimensions)
        except (TypeError, ValueError):
            return _QueryInspection("telemetry_record_invalid")
        if dimensions == expected:
            eligible += 1
    if eligible > 1:
        return _QueryInspection(
            "telemetry_record_ambiguous",
            eligible_record_count=eligible,
            allowlisted_dimensions_verified=True,
            unexpected_dimensions_absent=True,
            sensitive_content_absent=True,
        )
    if eligible == 1:
        return _QueryInspection(
            "success",
            eligible_record_count=1,
            verified=True,
            allowlisted_dimensions_verified=True,
            unexpected_dimensions_absent=True,
            sensitive_content_absent=True,
        )
    return _QueryInspection("no_eligible_record")


def _build_safe_settings(connection_string: str) -> AppSettings:
    with _temporary_environment(
        {**dict(SAFE_POSTURE), "APPLICATIONINSIGHTS_CONNECTION_STRING": connection_string}
    ):
        return AppSettings()


@contextmanager
def _temporary_environment(values: dict[str, str]):
    original = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _listed_resource_valid(
    candidate: object,
    account: _AccountEvidence,
    config: DailyAzureConfig,
) -> bool:
    if not isinstance(candidate, dict) or set(candidate) != {"id", "name", "type", "location"}:
        return False
    name = candidate.get("name")
    return bool(
        _safe_resource_name(name)
        and candidate.get("type") == "Microsoft.Insights/components"
        and _location_matches(candidate.get("location"), config.location)
        and _resource_id_matches(
            candidate.get("id"),
            subscription_id=account.subscription_id,
            resource_group=config.resource_group,
            provider="Microsoft.Insights",
            resource_type="components",
            resource_name=name,
        )
    )


def _shown_resource_valid(
    payload: object,
    candidate: dict[str, object],
    account: _AccountEvidence,
    config: DailyAzureConfig,
) -> bool:
    if not isinstance(payload, dict) or set(payload) != {
        "id",
        "name",
        "type",
        "kind",
        "location",
        "provisioningState",
        "workspaceResourceId",
    }:
        return False
    return bool(
        payload.get("id") == candidate.get("id")
        and payload.get("name") == candidate.get("name")
        and payload.get("type") == "Microsoft.Insights/components"
        and payload.get("kind") == "web"
        and _location_matches(payload.get("location"), config.location)
        and payload.get("provisioningState") == "Succeeded"
        and _resource_id_matches(
            payload.get("workspaceResourceId"),
            subscription_id=account.subscription_id,
            resource_group=config.resource_group,
            provider="Microsoft.OperationalInsights",
            resource_type="workspaces",
            resource_name=None,
        )
    )


def _resource_id_matches(
    value: object,
    *,
    subscription_id: str,
    resource_group: str,
    provider: str,
    resource_type: str,
    resource_name: object,
) -> bool:
    if not isinstance(value, str):
        return False
    parts = value.split("/")
    return bool(
        len(parts) == 9
        and parts[1].casefold() == "subscriptions"
        and parts[2].casefold() == subscription_id.casefold()
        and parts[3].casefold() == "resourcegroups"
        and parts[4].casefold() == resource_group.casefold()
        and parts[5].casefold() == "providers"
        and parts[6].casefold() == provider.casefold()
        and parts[7].casefold() == resource_type.casefold()
        and _safe_resource_name(parts[8])
        and (resource_name is None or parts[8].casefold() == str(resource_name).casefold())
    )


def _query_args(app_id: str, query: str) -> list[str]:
    return [
        "az",
        "rest",
        "--method",
        "post",
        "--url",
        f"https://api.applicationinsights.io/v1/apps/{app_id}/query",
        "--resource",
        "https://api.applicationinsights.io",
        "--headers",
        "Content-Type=application/json",
        "--body",
        json.dumps({"query": query}, separators=(",", ":")),
        "--output",
        "json",
        "--only-show-errors",
    ]


def _json_value(raw: str) -> object | None:
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None


def _uuid(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
        r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}",
        value,
    ) is not None


def _safe_resource_name(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(
        r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,258}[A-Za-z0-9])?",
        value,
    ) is not None


def _location_matches(value: object, expected: str) -> bool:
    return isinstance(value, str) and value.replace(" ", "").casefold() == expected.replace(" ", "").casefold()


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _utc_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() == timedelta(0)


def _parse_utc(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if _utc_datetime(parsed) else None
