import argparse
import asyncio
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterator, Literal, cast

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from starlette.exceptions import HTTPException


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.foundry_agent_verification import (
    FoundryAgentVerification,
    FoundryAgentVerificationResult,
    build_foundry_agent_verification_request,
    foundry_agent_verification_sdk_available,
)
from src.app.services.mock_ai_service import MockAiService
from src.app.services.nurse_handoff_note_formatter import NurseHandoffNoteFormatter
from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent
from src.app.services.nurse_intake_agent_instructions import (
    build_nurse_intake_agent_fictional_test_input,
)


FICTIONAL_INTAKE_TEXT = build_nurse_intake_agent_fictional_test_input()
FOUNDRY_AGENT_INTAKE_LIVE_COMMAND = (
    "python scripts/smoke_foundry_agent_intake.py --live --json"
)
REQUIRED_SETTINGS = (
    ("AGENT_PROVIDER", "agent_provider_normalized"),
    (
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "azure_ai_foundry_agent_project_endpoint",
    ),
    ("AZURE_AI_FOUNDRY_AGENT_NAME", "azure_ai_foundry_agent_name"),
    ("AZURE_AI_FOUNDRY_AGENT_VERSION", "azure_ai_foundry_agent_version"),
)
VERIFICATION_REQUIRED_SETTINGS = REQUIRED_SETTINGS + (
    (
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
        "azure_ai_foundry_model_deployment_name",
    ),
)
SAFE_MESSAGES = {
    "success": "Application-level Foundry Agent intake smoke succeeded.",
    "missing_configuration": "Required Foundry Agent configuration is missing.",
    "unsafe_application_configuration": (
        "Application configuration is unsafe for this manual smoke."
    ),
    "route_request_failed": "The application text-intake route did not complete.",
    "agent_not_attempted": "The application did not attempt the configured agent.",
    "safe_fallback_used": (
        "The application preserved its safe fallback after the agent attempt."
    ),
    "response_contract_invalid": (
        "The application result did not satisfy the smoke success contract."
    ),
    "unexpected_error": "The application-level smoke failed unexpectedly.",
    "sdk_unavailable": "Foundry Agent verification SDK support is unavailable.",
    "authentication_or_authorization_failed": (
        "Foundry Agent version verification was not authorized."
    ),
    "agent_version_not_found": "The configured Foundry Agent version was not found.",
    "definition_mismatch": "The configured Foundry Agent definition did not match.",
    "agent_verification_failed": "Foundry Agent version verification failed.",
    "azure_request_failed": "The Azure Foundry Agent verification request failed.",
}
SAFE_NEXT_STEPS = {
    "success": "Review the sanitized result, then restore AGENT_PROVIDER=mock.",
    "missing_configuration": "Add the missing setting names in the ignored local environment file.",
    "unsafe_application_configuration": (
        "Use mock application, AI, email, and SMS providers with notifications suppressed."
    ),
    "route_request_failed": "Review safe local configuration and route readiness.",
    "agent_not_attempted": "Check that AGENT_PROVIDER=foundry-agent is configured.",
    "safe_fallback_used": (
        "Review the agent contract separately; nurse review remains required."
    ),
    "response_contract_invalid": (
        "Review the application processing-trace and nurse-review boundaries."
    ),
    "unexpected_error": "Review the offline-safe setup before retrying manually.",
    "sdk_unavailable": "Install the optional Foundry Agent SDK before retrying.",
    "authentication_or_authorization_failed": (
        "Review Foundry access, then rerun read-only verification."
    ),
    "agent_version_not_found": (
        "Set the exact immutable version, then rerun read-only verification."
    ),
    "definition_mismatch": (
        "Provision or select the intended immutable definition, then verify again."
    ),
    "agent_verification_failed": (
        "Review Foundry readiness, then rerun read-only verification."
    ),
    "azure_request_failed": (
        "Review Foundry readiness, then rerun read-only verification."
    ),
}

VERIFICATION_GATE_FAILURE_MESSAGE = (
    "Immutable Foundry Agent version verification did not succeed."
)
VERIFICATION_GATE_NEXT_STEP = (
    "Resolve the sanitized verification category and rerun the read-only gate "
    "before application invocation."
)
VERIFICATION_CHECK_SUCCESS_MESSAGE = (
    "Guarded application smoke readiness passed; immutable verification is "
    "required before invocation."
)
VERIFICATION_CHECK_NEXT_STEP = (
    "Run the explicit live guarded smoke only after reviewing this offline result."
)


SmokeCategory = Literal[
    "success",
    "missing_configuration",
    "unsafe_application_configuration",
    "route_request_failed",
    "agent_not_attempted",
    "safe_fallback_used",
    "response_contract_invalid",
    "unexpected_error",
    "sdk_unavailable",
    "authentication_or_authorization_failed",
    "agent_version_not_found",
    "definition_mismatch",
    "agent_verification_failed",
    "azure_request_failed",
]


@dataclass(frozen=True)
class ApplicationIntakeSmokeResult:
    ok: bool
    mode: Literal["live"]
    category: SmokeCategory
    message: str
    agent_attempted: bool
    agent_output_valid: bool | None
    fallback_used: bool
    case_saved: bool
    intake_status: str | None
    review_status: str | None
    urgency_present: bool
    handoff_note_present: bool
    processing_trace_present: bool
    notifications_suppressed: bool
    recommended_next_step: str
    extraction_present: bool = False

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "category": self.category,
            "message": self.message,
            "agent_attempted": self.agent_attempted,
            "agent_output_valid": self.agent_output_valid,
            "fallback_used": self.fallback_used,
            "case_saved": self.case_saved,
            "intake_status": self.intake_status,
            "review_status": self.review_status,
            "urgency_present": self.urgency_present,
            "handoff_note_present": self.handoff_note_present,
            "processing_trace_present": self.processing_trace_present,
            "notifications_suppressed": self.notifications_suppressed,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class FoundryAgentIntakeReadiness:
    ready: bool
    category: Literal[
        "success",
        "missing_configuration",
        "unsafe_application_configuration",
    ]
    required_settings_missing: list[str]
    unsafe_settings: list[str]


@dataclass(frozen=True)
class _ApplicationStateSnapshot:
    route_service: object
    route_repository: object
    dependency_overrides_object: object
    dependency_override_values: dict[object, object]
    application_cases: tuple[object, ...]
    email_notifications: tuple[object, ...]
    sms_notifications: tuple[object, ...]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.env_file is not None and not _load_env_file(args.env_file):
        return 2

    settings = AppSettings()
    verification_requested = args.verify_agent_version
    readiness = build_foundry_agent_intake_readiness(
        settings,
        require_agent_version_verification=verification_requested,
    )

    if args.check:
        verification_sdk_available = (
            foundry_agent_verification_sdk_available()
            if verification_requested
            else None
        )
        payload = _check_result(
            readiness,
            verification_requested=verification_requested,
            verification_sdk_available=verification_sdk_available,
        )
        _print_json(payload)
        return 0 if payload["ready"] else 2

    if readiness.required_settings_missing:
        return _finish_live(
            _empty_live_result("missing_configuration"),
            2,
            verification_requested=verification_requested,
            verification_category="missing_configuration",
        )
    if readiness.unsafe_settings:
        return _finish_live(
            _empty_live_result("unsafe_application_configuration"),
            2,
            verification_requested=verification_requested,
            verification_category="unsafe_application_configuration",
        )

    verification_result: FoundryAgentVerificationResult | None = None
    if verification_requested:
        try:
            candidate = _create_verification_service().verify(
                build_foundry_agent_verification_request(settings)
            )
        except Exception:
            return _finish_live(
                _verification_gate_failure_result("agent_verification_failed"),
                1,
                verification_requested=True,
                verification_category="agent_verification_failed",
                azure_lookup_attempted=None,
            )
        if not isinstance(candidate, FoundryAgentVerificationResult):
            return _finish_live(
                _verification_gate_failure_result("response_contract_invalid"),
                1,
                verification_requested=True,
                verification_category="response_contract_invalid",
                azure_lookup_attempted=None,
            )
        verification_result = candidate
        if not verification_result.ok:
            gate_category = _verification_gate_category(
                verification_result.category
            )
            return _finish_live(
                _verification_gate_failure_result(gate_category),
                1,
                verification_requested=True,
                verification_result=verification_result,
                verification_category=gate_category,
            )

    try:
        agent = _create_live_agent(settings)
    except Exception:
        return _finish_live(
            _empty_live_result("unexpected_error"),
            1,
            verification_requested=verification_requested,
            verification_result=verification_result,
        )

    tracked_agent = _InvocationTrackingAgent(agent)
    state_before = _capture_application_state_safely()
    application_intake_attempted = False
    route_failure_category: SmokeCategory | None = None
    try:
        application_intake_attempted = True
        route_result = _run_intake_route(tracked_agent)
    except (HTTPException, RequestValidationError, ValidationError):
        route_failure_category = "route_request_failed"
        route_result = None
    except Exception:
        route_failure_category = "unexpected_error"
        route_result = None

    state_restored = _application_state_matches(state_before)
    if route_failure_category is not None:
        return _finish_live(
            _empty_live_result(route_failure_category),
            1,
            verification_requested=verification_requested,
            verification_result=verification_result,
            invocation_attempted=tracked_agent.invocation_attempted,
            application_intake_attempted=application_intake_attempted,
            temporary_application_state_restored=state_restored,
        )

    route_values = _usable_route_result(route_result)
    if route_values is None:
        return _finish_live(
            _empty_live_result("route_request_failed"),
            1,
            verification_requested=verification_requested,
            verification_result=verification_result,
            invocation_attempted=tracked_agent.invocation_attempted,
            application_intake_attempted=application_intake_attempted,
            temporary_application_state_restored=state_restored,
        )
    case, case_saved, handoff_note_present = route_values

    result = _result_from_case(
        case,
        case_saved=case_saved,
        handoff_note_present=handoff_note_present,
    )
    return _finish_live(
        result,
        0 if result.ok else 1,
        verification_requested=verification_requested,
        verification_result=verification_result,
        invocation_attempted=tracked_agent.invocation_attempted,
        application_intake_attempted=application_intake_attempted,
        temporary_application_state_restored=state_restored,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an explicit application-level Foundry Agent text-intake smoke "
            "with fictional data only."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Validate configuration offline without creating clients or cases.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help="Run one opt-in fictional intake through the application route.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print exactly one sanitized JSON result; required with --live.",
    )
    parser.add_argument(
        "--env-file",
        help="Load KEY=value settings for this process; existing environment wins.",
    )
    parser.add_argument(
        "--verify-agent-version",
        action="store_true",
        help=(
            "Require read-only verification of the configured immutable agent "
            "version before live application intake."
        ),
    )
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def build_foundry_agent_intake_readiness(
    settings: Any,
    *,
    require_agent_version_verification: bool = False,
) -> FoundryAgentIntakeReadiness:
    """Return sanitized, side-effect-free application smoke readiness."""

    missing = _missing_configuration(
        settings,
        require_agent_version_verification=require_agent_version_verification,
    )
    unsafe = _unsafe_application_settings(settings)
    if missing:
        category = "missing_configuration"
    elif unsafe:
        category = "unsafe_application_configuration"
    else:
        category = "success"
    return FoundryAgentIntakeReadiness(
        ready=category == "success",
        category=category,
        required_settings_missing=missing,
        unsafe_settings=unsafe,
    )


def _check_result(
    readiness: FoundryAgentIntakeReadiness,
    *,
    verification_requested: bool = False,
    verification_sdk_available: bool | None = None,
) -> dict[str, object]:
    sdk_ready = (
        not verification_requested or verification_sdk_available is True
    )
    ready = readiness.ready and sdk_ready
    category = (
        readiness.category
        if not readiness.ready
        else "sdk_unavailable"
        if not sdk_ready
        else "success"
    )
    payload: dict[str, object] = {
        "ok": ready,
        "ready": ready,
        "mode": "check",
        "category": category,
        "message": (
            VERIFICATION_CHECK_SUCCESS_MESSAGE
            if verification_requested and ready
            else SAFE_MESSAGES[category]
        ),
        "required_settings_present": [
            setting_name
            for setting_name, _ in (
                VERIFICATION_REQUIRED_SETTINGS
                if verification_requested
                else REQUIRED_SETTINGS
            )
            if setting_name not in readiness.required_settings_missing
        ],
        "required_settings_missing": readiness.required_settings_missing,
        "unsafe_application_settings": readiness.unsafe_settings,
        "client_created": False,
        "intake_processed": False,
        "case_saved": False,
        "notifications_recorded": False,
        "azure_call_made": False,
        "recommended_next_step": (
            VERIFICATION_CHECK_NEXT_STEP
            if verification_requested and ready
            else SAFE_NEXT_STEPS[category]
        ),
    }
    if verification_requested:
        payload.update(
            {
                "verification": {
                    "requested": True,
                    "azure_lookup_attempted": False,
                    "configured_agent_version_matched": None,
                    "category": "not_attempted",
                    "sdk_available": verification_sdk_available,
                },
                "invocation_attempted": False,
                "application_intake_attempted": False,
                "temporary_application_state_restored": True,
                "expected_safe_output_fields_present": [],
            }
        )
    return payload


def _empty_live_result(category: SmokeCategory) -> ApplicationIntakeSmokeResult:
    return ApplicationIntakeSmokeResult(
        ok=False,
        mode="live",
        category=category,
        message=SAFE_MESSAGES[category],
        agent_attempted=False,
        agent_output_valid=None,
        fallback_used=False,
        case_saved=False,
        intake_status=None,
        review_status=None,
        urgency_present=False,
        handoff_note_present=False,
        processing_trace_present=False,
        notifications_suppressed=False,
        recommended_next_step=SAFE_NEXT_STEPS[category],
    )


def _verification_gate_failure_result(
    category: SmokeCategory,
) -> ApplicationIntakeSmokeResult:
    return replace(
        _empty_live_result(category),
        message=VERIFICATION_GATE_FAILURE_MESSAGE,
        recommended_next_step=VERIFICATION_GATE_NEXT_STEP,
    )


def _finish_live(
    result: ApplicationIntakeSmokeResult,
    exit_code: int,
    **payload_options: Any,
) -> int:
    _print_json(_live_result_payload(result, **payload_options))
    return exit_code


def _live_result_payload(
    result: ApplicationIntakeSmokeResult,
    *,
    verification_requested: bool,
    verification_result: FoundryAgentVerificationResult | None = None,
    verification_category: str | None = None,
    azure_lookup_attempted: bool | None = False,
    invocation_attempted: bool = False,
    application_intake_attempted: bool = False,
    temporary_application_state_restored: bool = True,
) -> dict[str, object]:
    payload = result.to_json_dict()
    if not verification_requested:
        return payload

    if verification_result is not None:
        verification_category = verification_category or _verification_gate_category(
            verification_result.category
        )
        azure_lookup_attempted = verification_result.azure_lookup_attempted
        configured_agent_version_matched = _verification_match_status(
            verification_result
        )
        verification_sdk_available: bool | None = (
            verification_result.category != "sdk_unavailable"
        )
    else:
        configured_agent_version_matched = None
        verification_sdk_available = None

    expected_fields = [
        field_name
        for field_name, present in (
            ("extraction", result.extraction_present),
            ("urgency", result.urgency_present),
            ("handoffNote", result.handoff_note_present),
        )
        if present
    ]

    payload.update(
        {
            "verification": {
                "requested": True,
                "azure_lookup_attempted": azure_lookup_attempted,
                "configured_agent_version_matched": (
                    configured_agent_version_matched
                ),
                "category": verification_category or "not_attempted",
                "sdk_available": verification_sdk_available,
            },
            "invocation_attempted": invocation_attempted,
            "application_intake_attempted": application_intake_attempted,
            "temporary_application_state_restored": (
                temporary_application_state_restored
            ),
            "expected_safe_output_fields_present": expected_fields,
        }
    )
    return payload


def _verification_gate_category(category: str) -> SmokeCategory:
    if category == "agent_verification_failed":
        return "azure_request_failed"
    return cast(SmokeCategory, category)


def _verification_match_status(
    result: FoundryAgentVerificationResult,
) -> bool | None:
    if result.ok and result.agent_definition_matches:
        return True
    if result.category in {"definition_mismatch", "agent_version_not_found"}:
        return False
    return None


def _result_from_case(
    case: Any,
    *,
    case_saved: bool,
    handoff_note_present: bool,
) -> ApplicationIntakeSmokeResult:
    trace = getattr(case, "processing_trace", None)
    processing_trace_present = trace is not None
    missing = object()
    attempted_value = getattr(trace, "agent_attempted", missing)
    output_valid_value = getattr(trace, "agent_output_valid", missing)
    fallback_value = getattr(trace, "agent_fallback_used", missing)
    trace_metadata_valid = (
        isinstance(attempted_value, bool)
        and (isinstance(output_valid_value, bool) or output_valid_value is None)
        and isinstance(fallback_value, bool)
    )
    agent_attempted = attempted_value if isinstance(attempted_value, bool) else False
    agent_output_valid = (
        output_valid_value
        if isinstance(output_valid_value, bool) or output_valid_value is None
        else None
    )
    fallback_used = fallback_value if isinstance(fallback_value, bool) else False
    notifications_suppressed = (
        getattr(case, "notificationEmailStatus", None) == "Suppressed"
        and getattr(case, "notificationSmsStatus", None) == "Suppressed"
    )
    review_status = _safe_status(getattr(case, "reviewStatus", None))
    intake_status = _safe_status(getattr(case, "intakeStatus", None))
    urgency_present = getattr(case, "urgency", None) in {
        "Routine",
        "Urgent",
        "Unknown",
    }
    extraction_present = _safe_extraction_present(case)
    safe_application_postconditions = (
        case_saved is True
        and intake_status in {"Complete", "NeedsFollowUp"}
        and review_status == "PendingReview"
        and urgency_present
        and handoff_note_present is True
        and processing_trace_present
        and trace_metadata_valid
        and notifications_suppressed
    )

    if not safe_application_postconditions:
        category: SmokeCategory = "response_contract_invalid"
    elif not agent_attempted and (
        fallback_used or agent_output_valid not in {False, None}
    ):
        category = "response_contract_invalid"
    elif not agent_attempted:
        category = "agent_not_attempted"
    elif fallback_used and agent_output_valid is False:
        category = "safe_fallback_used"
    elif fallback_used or agent_output_valid is not True:
        category = "response_contract_invalid"
    else:
        category = "success"

    return ApplicationIntakeSmokeResult(
        ok=category == "success",
        mode="live",
        category=category,
        message=SAFE_MESSAGES[category],
        agent_attempted=agent_attempted,
        agent_output_valid=agent_output_valid,
        fallback_used=fallback_used,
        case_saved=case_saved,
        intake_status=intake_status,
        review_status=review_status,
        urgency_present=urgency_present,
        handoff_note_present=handoff_note_present,
        processing_trace_present=processing_trace_present,
        notifications_suppressed=notifications_suppressed,
        recommended_next_step=SAFE_NEXT_STEPS[category],
        extraction_present=extraction_present,
    )


def _safe_extraction_present(case: Any) -> bool:
    summary = getattr(case, "summary", None)
    symptoms = getattr(case, "symptoms", None)
    return (
        getattr(case, "patient", None) is not None
        and isinstance(summary, str)
        and bool(summary.strip())
        and isinstance(symptoms, list)
    )


def _run_intake_route(agent: object) -> tuple[Any, bool, bool]:
    return asyncio.run(_run_intake_route_async(agent))


class _InvocationTrackingAgent:
    def __init__(self, agent: object) -> None:
        self._agent = agent
        self.invocation_attempted = False

    async def analyze_intake(self, raw_text: str) -> Any:
        self.invocation_attempted = True
        return await self._agent.analyze_intake(raw_text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)


def _usable_route_result(
    result: object,
) -> tuple[Any, bool, bool] | None:
    if not isinstance(result, tuple) or len(result) != 3:
        return None
    case, case_saved, handoff_note_present = result
    if case is None:
        return None
    if not isinstance(case_saved, bool) or not isinstance(
        handoff_note_present,
        bool,
    ):
        return None
    return case, case_saved, handoff_note_present


async def _run_intake_route_async(agent: object) -> tuple[Any, bool, bool]:
    import src.app.routes.intake as intake_route

    repository = InMemoryCaseRepository()
    service = CaseProcessingService(
        ai_service=MockAiService(),
        nurse_intake_agent=agent,
        suppress_notifications=True,
    )
    with _temporary_application_overrides(
        intake_route=intake_route,
        service=service,
        repository=repository,
    ):
        request = intake_route.TextIntakeRequest(
            text=FICTIONAL_INTAKE_TEXT,
            sourceSystem="foundry-agent-application-smoke",
        )
        case = await intake_route.create_text_intake(request)
        saved_case = await repository.get_by_id(case.id)
        handoff_note = NurseHandoffNoteFormatter().format(case)
        return case, saved_case is not None, bool(handoff_note.strip())


@contextmanager
def _temporary_application_overrides(
    *,
    intake_route: Any,
    service: CaseProcessingService,
    repository: InMemoryCaseRepository,
) -> Iterator[None]:
    from src.app.main import app

    original_service = intake_route.case_processing_service
    original_repository = intake_route.case_repository
    original_dependency_overrides = app.dependency_overrides
    dependency_override_snapshot = dict(original_dependency_overrides)
    try:
        intake_route.case_processing_service = service
        intake_route.case_repository = repository
        yield
    finally:
        intake_route.case_processing_service = original_service
        intake_route.case_repository = original_repository
        original_dependency_overrides.clear()
        original_dependency_overrides.update(dependency_override_snapshot)
        app.dependency_overrides = original_dependency_overrides


def _create_live_agent(settings: AppSettings) -> object:
    return create_nurse_intake_agent(settings)


def _create_verification_service() -> FoundryAgentVerification:
    return FoundryAgentVerification()


def _capture_application_state_safely() -> _ApplicationStateSnapshot | None:
    try:
        return _capture_application_state()
    except Exception:
        return None


def _capture_application_state() -> _ApplicationStateSnapshot:
    from src.app.dependencies import (
        case_repository as application_repository,
        email_notification_sender,
        sms_notification_sender,
    )
    from src.app.main import app
    import src.app.routes.intake as intake_route

    return _ApplicationStateSnapshot(
        route_service=intake_route.case_processing_service,
        route_repository=intake_route.case_repository,
        dependency_overrides_object=app.dependency_overrides,
        dependency_override_values=dict(app.dependency_overrides),
        application_cases=tuple(asyncio.run(application_repository.list_cases())),
        email_notifications=tuple(
            getattr(email_notification_sender, "sent_notifications", ())
        ),
        sms_notifications=tuple(
            getattr(sms_notification_sender, "sent_notifications", ())
        ),
    )


def _application_state_matches(
    before: _ApplicationStateSnapshot | None,
) -> bool:
    if before is None:
        return False
    try:
        after = _capture_application_state()
    except Exception:
        return False
    return (
        after.route_service is before.route_service
        and after.route_repository is before.route_repository
        and after.dependency_overrides_object is before.dependency_overrides_object
        and after.dependency_override_values == before.dependency_override_values
        and after.application_cases == before.application_cases
        and after.email_notifications == before.email_notifications
        and after.sms_notifications == before.sms_notifications
    )


def _missing_configuration(
    settings: Any,
    *,
    require_agent_version_verification: bool = False,
) -> list[str]:
    missing: list[str] = []
    required_settings = (
        VERIFICATION_REQUIRED_SETTINGS
        if require_agent_version_verification
        else REQUIRED_SETTINGS
    )
    for setting_name, attribute_name in required_settings:
        value = getattr(settings, attribute_name, None)
        if setting_name == "AGENT_PROVIDER":
            if value not in {"foundry", "foundry-agent"}:
                missing.append(setting_name)
        elif not isinstance(value, str) or not value.strip():
            missing.append(setting_name)
    return missing


def _unsafe_application_settings(settings: Any) -> list[str]:
    unsafe: list[str] = []
    safe_values = (
        ("APP_MODE", getattr(settings, "app_mode", ""), "mock"),
        (
            "AI_PROVIDER",
            getattr(settings, "ai_provider_normalized", ""),
            "mock",
        ),
        (
            "EMAIL_PROVIDER",
            getattr(settings, "email_provider_normalized", ""),
            "mock",
        ),
        (
            "SMS_PROVIDER",
            getattr(settings, "sms_provider_normalized", ""),
            "mock",
        ),
    )
    for setting_name, actual, expected in safe_values:
        if str(actual).strip().lower() != expected:
            unsafe.append(setting_name)
    if getattr(settings, "demo_suppress_notifications", False) is not True:
        unsafe.append("DEMO_SUPPRESS_NOTIFICATIONS")
    return unsafe


def _safe_status(value: object) -> str | None:
    safe_values = {"Complete", "NeedsFollowUp", "PendingReview", "Reviewed"}
    return value if isinstance(value, str) and value in safe_values else None


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _load_env_file(path_value: str) -> bool:
    from dotenv import dotenv_values

    path = Path(path_value)
    if not path.is_file():
        _print_json(
            _empty_live_result("missing_configuration").to_json_dict()
        )
        return False
    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ.setdefault(key, value)
    return True


if __name__ == "__main__":
    raise SystemExit(main())
