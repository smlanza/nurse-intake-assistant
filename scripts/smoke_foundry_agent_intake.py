import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.case_repository import InMemoryCaseRepository
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
}


SmokeCategory = Literal[
    "success",
    "missing_configuration",
    "unsafe_application_configuration",
    "route_request_failed",
    "agent_not_attempted",
    "safe_fallback_used",
    "response_contract_invalid",
    "unexpected_error",
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


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.env_file is not None and not _load_env_file(args.env_file):
        return 2

    settings = AppSettings()
    readiness = build_foundry_agent_intake_readiness(settings)

    if args.check:
        payload = _check_result(readiness)
        _print_json(payload)
        return 0 if payload["ready"] else 2

    if readiness.required_settings_missing:
        _print_json(_empty_live_result("missing_configuration").to_json_dict())
        return 2
    if readiness.unsafe_settings:
        _print_json(
            _empty_live_result(
                "unsafe_application_configuration"
            ).to_json_dict()
        )
        return 2

    try:
        agent = _create_live_agent(settings)
    except Exception:
        _print_json(_empty_live_result("unexpected_error").to_json_dict())
        return 1

    try:
        case, case_saved, handoff_note_present = _run_intake_route(agent)
    except Exception:
        _print_json(_empty_live_result("route_request_failed").to_json_dict())
        return 1

    result = _result_from_case(
        case,
        case_saved=case_saved,
        handoff_note_present=handoff_note_present,
    )
    _print_json(result.to_json_dict())
    return 0 if result.ok else 1


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
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def build_foundry_agent_intake_readiness(
    settings: Any,
) -> FoundryAgentIntakeReadiness:
    """Return sanitized, side-effect-free application smoke readiness."""

    missing = _missing_configuration(settings)
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
) -> dict[str, object]:
    return {
        "ok": readiness.ready,
        "ready": readiness.ready,
        "mode": "check",
        "category": readiness.category,
        "message": SAFE_MESSAGES[readiness.category],
        "required_settings_present": [
            setting_name
            for setting_name, _ in REQUIRED_SETTINGS
            if setting_name not in readiness.required_settings_missing
        ],
        "required_settings_missing": readiness.required_settings_missing,
        "unsafe_application_settings": readiness.unsafe_settings,
        "client_created": False,
        "intake_processed": False,
        "case_saved": False,
        "notifications_recorded": False,
        "azure_call_made": False,
        "recommended_next_step": SAFE_NEXT_STEPS[readiness.category],
    }


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


def _result_from_case(
    case: Any,
    *,
    case_saved: bool,
    handoff_note_present: bool,
) -> ApplicationIntakeSmokeResult:
    trace = getattr(case, "processing_trace", None)
    agent_attempted = bool(getattr(trace, "agent_attempted", False))
    agent_output_valid = getattr(trace, "agent_output_valid", None)
    fallback_used = bool(getattr(trace, "agent_fallback_used", False))
    processing_trace_present = trace is not None
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

    if not agent_attempted:
        category: SmokeCategory = "agent_not_attempted"
    elif fallback_used:
        category = "safe_fallback_used"
    elif agent_output_valid is not True:
        category = "response_contract_invalid"
    elif not (
        case_saved
        and review_status == "PendingReview"
        and notifications_suppressed
        and processing_trace_present
        and handoff_note_present
        and urgency_present
    ):
        category = "response_contract_invalid"
    else:
        category = "success"

    return ApplicationIntakeSmokeResult(
        ok=category == "success",
        mode="live",
        category=category,
        message=SAFE_MESSAGES[category],
        agent_attempted=agent_attempted,
        agent_output_valid=(
            agent_output_valid if isinstance(agent_output_valid, bool) else None
        ),
        fallback_used=fallback_used,
        case_saved=case_saved,
        intake_status=intake_status,
        review_status=review_status,
        urgency_present=urgency_present,
        handoff_note_present=handoff_note_present,
        processing_trace_present=processing_trace_present,
        notifications_suppressed=notifications_suppressed,
        recommended_next_step=SAFE_NEXT_STEPS[category],
    )


def _run_intake_route(agent: object) -> tuple[Any, bool, bool]:
    return asyncio.run(_run_intake_route_async(agent))


async def _run_intake_route_async(agent: object) -> tuple[Any, bool, bool]:
    import src.app.routes.intake as intake_route

    repository = InMemoryCaseRepository()
    service = CaseProcessingService(
        ai_service=MockAiService(),
        nurse_intake_agent=agent,
        suppress_notifications=True,
    )
    original_service = intake_route.case_processing_service
    original_repository = intake_route.case_repository
    try:
        intake_route.case_processing_service = service
        intake_route.case_repository = repository
        request = intake_route.TextIntakeRequest(
            text=FICTIONAL_INTAKE_TEXT,
            sourceSystem="foundry-agent-application-smoke",
        )
        case = await intake_route.create_text_intake(request)
        saved_case = await repository.get_by_id(case.id)
        handoff_note = NurseHandoffNoteFormatter().format(case)
        return case, saved_case is not None, bool(handoff_note.strip())
    finally:
        intake_route.case_processing_service = original_service
        intake_route.case_repository = original_repository


def _create_live_agent(settings: AppSettings) -> object:
    return create_nurse_intake_agent(settings)


def _missing_configuration(settings: Any) -> list[str]:
    missing: list[str] = []
    for setting_name, attribute_name in REQUIRED_SETTINGS:
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
