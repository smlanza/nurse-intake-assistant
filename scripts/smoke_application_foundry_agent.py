import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
import inspect
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterator, Literal

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.application_composition import (
    ApplicationComposition,
    compose_application,
)
from src.app.config.settings import AppSettings
from src.app.models.case import CaseDocument
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.foundry_agent_client import (
    FoundryAgentClientError,
    is_valid_stable_agent_endpoint,
    stable_agent_endpoint_matches_configuration,
)
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
)
from src.app.services.mock_ai_service import MockAiService
from src.app.services.nurse_intake_agent import FoundryNurseIntakeAgent
from src.app.services.sms_notification_sender import MockSmsNotificationSender


OPERATION = "smoke_application_foundry_agent"
FIXED_FICTIONAL_INTAKE = (
    "Fictional patient Avery Example, date of birth 2000-01-01, with callback "
    "identifier fictional-callback-only, reports new chest pain and shortness "
    "of breath. This is fixed fictional test data requiring nurse review."
)
GENERIC_FAILURE_MESSAGE = "Application Foundry Agent smoke failed."

SmokeMode = Literal["check", "live"]
SmokeCategory = Literal[
    "success",
    "invalid_arguments",
    "fixed_input_invalid",
    "missing_configuration",
    "invalid_configuration",
    "unsafe_provider_posture",
    "composition_failure",
    "authentication_failure",
    "authorization_failure",
    "agent_invocation_failure",
    "invalid_agent_output",
    "unexpected_fallback",
    "deterministic_rules_failure",
    "persistence_failure",
    "notification_suppression_failure",
    "nurse_review_invariant_failure",
    "unexpected_exception",
]

_REQUIRED_AGENT_SETTINGS = (
    (
        "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT",
        "azure_ai_foundry_agent_project_endpoint",
    ),
    (
        "AZURE_AI_FOUNDRY_AGENT_ENDPOINT",
        "azure_ai_foundry_agent_endpoint",
    ),
    ("AZURE_AI_FOUNDRY_AGENT_NAME", "azure_ai_foundry_agent_name"),
    ("AZURE_AI_FOUNDRY_AGENT_VERSION", "azure_ai_foundry_agent_version"),
)
_SAFE_PROVIDER_SETTINGS = (
    ("APP_MODE", "app_mode", "mock"),
    ("AI_PROVIDER", "ai_provider_normalized", "mock"),
    ("AGENT_PROVIDER", "agent_provider_normalized", "foundry-agent"),
    ("EMAIL_PROVIDER", "email_provider_normalized", "mock"),
    ("SMS_PROVIDER", "sms_provider_normalized", "mock"),
)
_ISOLATED_SETTING_NAMES = {
    *(name for name, _, _ in _SAFE_PROVIDER_SETTINGS),
    *(name for name, _ in _REQUIRED_AGENT_SETTINGS),
    "AZURE_AI_FOUNDRY_AGENT_USE_PROJECT_ENDPOINT_COMPATIBILITY",
    "AZURE_AI_FOUNDRY_MANAGED_IDENTITY_CLIENT_ID",
    "DEMO_SUPPRESS_NOTIFICATIONS",
}
_ENVIRONMENT_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class ApplicationFoundryAgentReadiness:
    ready: bool
    category: SmokeCategory
    required_agent_settings_present: tuple[str, ...] = ()
    missing_settings: tuple[str, ...] = ()
    unsafe_settings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplicationFoundryAgentSmokeResult:
    ok: bool
    category: SmokeCategory
    mode: SmokeMode
    application_composition_used: bool = False
    agent_attempted: bool = False
    agent_output_valid: bool = False
    fallback_used: bool = False
    deterministic_rules_applied: bool = False
    case_persisted_in_memory: bool = False
    notification_email_status: str = "NotEvaluated"
    notification_sms_status: str = "NotEvaluated"
    nurse_review_required: bool = False
    azure_mutation_made: bool = False
    required_agent_settings_present: tuple[str, ...] = ()
    missing_settings: tuple[str, ...] = ()
    unsafe_settings: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["operation"] = OPERATION
        return result


SAFE_RESULT_FIELDS = {
    *(field.name for field in fields(ApplicationFoundryAgentSmokeResult)),
    "operation",
}


class SmokeConfigurationError(ValueError):
    def __init__(self, category: SmokeCategory) -> None:
        super().__init__("Application Foundry Agent configuration is invalid.")
        self.category = category


class _InvalidArgumentsError(Exception):
    pass


class _SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _InvalidArgumentsError from None


class _InvocationTrackingAgent:
    def __init__(self, delegate: FoundryNurseIntakeAgent) -> None:
        self.delegate = delegate
        self.attempt_count = 0
        self.completed = False
        self.failure_category: SmokeCategory | None = None

    async def analyze_intake(self, raw_text: str) -> Any:
        self.attempt_count += 1
        try:
            result = await self.delegate.analyze_intake(raw_text)
        except Exception as error:
            self.failure_category = _agent_failure_category(error)
            raise
        self.completed = True
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


class _RulesExecutionTracker:
    def __init__(self, delegate: object) -> None:
        self.delegate = delegate
        self.attempt_count = 0
        self.completed = False

    def evaluate(self, raw_text: str) -> Any:
        self.attempt_count += 1
        result = self.delegate.evaluate(raw_text)
        self.completed = True
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    json_requested = "--json" in raw_argv
    requested_mode: SmokeMode = "live" if "--live" in raw_argv else "check"
    try:
        try:
            args = _parse_args(raw_argv)
        except _InvalidArgumentsError:
            result = _empty_result("invalid_arguments", requested_mode)
            return _emit_result(result, json_requested, exit_code=2)

        with _configuration_context(args.config) as settings:
            readiness = build_application_foundry_agent_readiness(settings)
            if args.check:
                result = _check_result(readiness)
                _print_result(result, json_output=args.json)
                return 0 if result.ok else 2

            if not readiness.ready:
                result = _result_from_readiness(readiness, "live")
                _print_result(result, json_output=True)
                return 2

            result = run_application_foundry_agent_smoke(settings)
            _print_result(result, json_output=True)
            if result.ok:
                return 0
            if result.category in {
                "missing_configuration",
                "invalid_configuration",
                "unsafe_provider_posture",
            }:
                return 2
            return 1
    except SmokeConfigurationError as error:
        result = _empty_result(error.category, requested_mode)
        return _emit_result(result, json_requested, exit_code=2)
    except Exception:
        result = _empty_result("unexpected_exception", requested_mode)
        return _emit_result(result, json_requested, exit_code=1)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        description=(
            "Run one fixed fictional intake through the application-integrated "
            "Microsoft Foundry Agent boundary."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Validate local configuration and command contracts only.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help="Run the one explicitly selected live fictional Agent intake.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print one sanitized JSON result; required with --live.",
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to the ignored Foundry Agent application configuration.",
    )
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("invalid argument combination")
    return args


def build_application_foundry_agent_readiness(
    settings: object,
) -> ApplicationFoundryAgentReadiness:
    if not _fixed_input_valid():
        return ApplicationFoundryAgentReadiness(False, "fixed_input_invalid")

    present = tuple(
        setting_name
        for setting_name, attribute in _REQUIRED_AGENT_SETTINGS
        if _nonblank(getattr(settings, attribute, None))
    )
    missing = tuple(
        setting_name
        for setting_name, _ in _REQUIRED_AGENT_SETTINGS
        if setting_name not in present
    )
    unsafe = [
        setting_name
        for setting_name, attribute, expected in _SAFE_PROVIDER_SETTINGS
        if not _matches_expected(getattr(settings, attribute, None), expected)
    ]
    if getattr(settings, "demo_suppress_notifications", None) is not True:
        unsafe.append("DEMO_SUPPRESS_NOTIFICATIONS")

    if missing:
        category: SmokeCategory = "missing_configuration"
    elif not _stable_agent_configuration_valid(settings):
        category = "invalid_configuration"
    elif unsafe:
        category = "unsafe_provider_posture"
    else:
        category = "success"
    return ApplicationFoundryAgentReadiness(
        ready=category == "success",
        category=category,
        required_agent_settings_present=present,
        missing_settings=missing,
        unsafe_settings=tuple(unsafe),
    )


def run_application_foundry_agent_smoke(
    settings: AppSettings,
) -> ApplicationFoundryAgentSmokeResult:
    readiness = build_application_foundry_agent_readiness(settings)
    if not readiness.ready:
        return _result_from_readiness(readiness, "live")

    try:
        application = compose_application(settings)
    except Exception:
        return _empty_result("composition_failure", "live")
    if not _composition_is_safe(application, settings):
        return _empty_result("composition_failure", "live")

    original_agent = application.nurse_intake_agent
    agent_tracker = _InvocationTrackingAgent(original_agent)
    rules_tracker = _RulesExecutionTracker(
        application.case_processing_service.rules_service
    )
    application.case_processing_service.nurse_intake_agent = agent_tracker
    application.case_processing_service.rules_service = rules_tracker
    try:
        try:
            case = asyncio.run(
                application.case_processing_service.process(
                    FIXED_FICTIONAL_INTAKE,
                    "text-intake",
                )
            )
        except Exception:
            category: SmokeCategory
            if agent_tracker.failure_category is not None:
                category = agent_tracker.failure_category
            elif (
                rules_tracker.attempt_count != 1
                or not rules_tracker.completed
            ):
                category = "deterministic_rules_failure"
            elif agent_tracker.completed:
                category = "persistence_failure"
            else:
                category = "agent_invocation_failure"
            return ApplicationFoundryAgentSmokeResult(
                ok=False,
                category=category,
                mode="live",
                application_composition_used=True,
                agent_attempted=agent_tracker.attempt_count > 0,
                agent_output_valid=agent_tracker.completed,
                fallback_used=False,
                deterministic_rules_applied=rules_tracker.completed,
                required_agent_settings_present=(
                    readiness.required_agent_settings_present
                ),
            )

        return _result_from_processed_case(
            case,
            application,
            agent_tracker,
            rules_tracker,
            readiness,
        )
    finally:
        _close_agent_client(original_agent)


def _composition_is_safe(
    application: object,
    settings: object,
) -> bool:
    if not isinstance(application, ApplicationComposition):
        return False
    service = application.case_processing_service
    return bool(
        application.settings is settings
        and type(application.ai_service) is MockAiService
        and isinstance(application.nurse_intake_agent, FoundryNurseIntakeAgent)
        and application.nurse_intake_agent.settings is settings
        and isinstance(application.case_repository, InMemoryCaseRepository)
        and type(application.email_notification_sender)
        is MockEmailNotificationSender
        and type(application.sms_notification_sender) is MockSmsNotificationSender
        and isinstance(service, CaseProcessingService)
        and service.ai_service is application.ai_service
        and service.nurse_intake_agent is application.nurse_intake_agent
        and service.case_repository is application.case_repository
        and service.email_notification_sender
        is application.email_notification_sender
        and service.sms_notification_sender is application.sms_notification_sender
        and service.suppress_notifications is True
    )


def _result_from_processed_case(
    case: object,
    application: ApplicationComposition,
    agent_tracker: _InvocationTrackingAgent,
    rules_tracker: _RulesExecutionTracker,
    readiness: ApplicationFoundryAgentReadiness,
) -> ApplicationFoundryAgentSmokeResult:
    case_valid = isinstance(case, CaseDocument)
    trace = case.processing_trace if case_valid else None
    agent_output_valid = bool(
        case_valid
        and trace is not None
        and trace.agent_attempted is True
        and trace.agent_output_valid is True
    )
    fallback_used = bool(
        case_valid
        and trace is not None
        and trace.agent_fallback_used is True
    )
    deterministic_rules_applied = bool(
        rules_tracker.attempt_count == 1
        and rules_tracker.completed
    )
    try:
        stored_cases = asyncio.run(application.case_repository.list_cases())
    except Exception:
        stored_cases = []
    persisted = bool(
        case_valid
        and len(stored_cases) == 1
        and stored_cases[0] is case
    )
    notification_email_status = (
        "Suppressed"
        if case_valid and case.notificationEmailStatus == "Suppressed"
        else "Invalid"
        if case_valid
        else "NotEvaluated"
    )
    notification_sms_status = (
        "Suppressed"
        if case_valid and case.notificationSmsStatus == "Suppressed"
        else "Invalid"
        if case_valid
        else "NotEvaluated"
    )
    notifications_suppressed = bool(
        notification_email_status == "Suppressed"
        and notification_sms_status == "Suppressed"
        and not application.email_notification_sender.sent_notifications
        and not application.sms_notification_sender.sent_notifications
    )
    nurse_review_required = bool(
        case_valid and case.reviewStatus == "PendingReview"
    )

    if agent_tracker.attempt_count != 1:
        category: SmokeCategory = "agent_invocation_failure"
    elif agent_tracker.failure_category is not None:
        category = agent_tracker.failure_category
    elif fallback_used and not agent_output_valid:
        category = "invalid_agent_output"
    elif fallback_used:
        category = "unexpected_fallback"
    elif not agent_output_valid:
        category = "invalid_agent_output"
    elif not deterministic_rules_applied:
        category = "deterministic_rules_failure"
    elif not persisted:
        category = "persistence_failure"
    elif not notifications_suppressed:
        category = "notification_suppression_failure"
    elif not nurse_review_required:
        category = "nurse_review_invariant_failure"
    else:
        category = "success"

    return ApplicationFoundryAgentSmokeResult(
        ok=category == "success",
        category=category,
        mode="live",
        application_composition_used=True,
        agent_attempted=agent_tracker.attempt_count > 0,
        agent_output_valid=agent_output_valid,
        fallback_used=fallback_used,
        deterministic_rules_applied=deterministic_rules_applied,
        case_persisted_in_memory=persisted,
        notification_email_status=notification_email_status,
        notification_sms_status=notification_sms_status,
        nurse_review_required=nurse_review_required,
        required_agent_settings_present=readiness.required_agent_settings_present,
    )


def _check_result(
    readiness: ApplicationFoundryAgentReadiness,
) -> ApplicationFoundryAgentSmokeResult:
    return ApplicationFoundryAgentSmokeResult(
        ok=readiness.ready,
        category=readiness.category,
        mode="check",
        required_agent_settings_present=readiness.required_agent_settings_present,
        missing_settings=readiness.missing_settings,
        unsafe_settings=readiness.unsafe_settings,
    )


def _result_from_readiness(
    readiness: ApplicationFoundryAgentReadiness,
    mode: SmokeMode,
) -> ApplicationFoundryAgentSmokeResult:
    return ApplicationFoundryAgentSmokeResult(
        ok=False,
        category=readiness.category,
        mode=mode,
        required_agent_settings_present=readiness.required_agent_settings_present,
        missing_settings=readiness.missing_settings,
        unsafe_settings=readiness.unsafe_settings,
    )


def _empty_result(
    category: SmokeCategory,
    mode: SmokeMode,
) -> ApplicationFoundryAgentSmokeResult:
    return ApplicationFoundryAgentSmokeResult(
        ok=False,
        category=category,
        mode=mode,
    )


@contextmanager
def _configuration_context(config_path: Path | str) -> Iterator[AppSettings]:
    path = Path(config_path)
    if not path.is_file():
        raise SmokeConfigurationError("missing_configuration")
    try:
        parsed = dotenv_values(path)
    except Exception:
        raise SmokeConfigurationError("invalid_configuration") from None
    if any(
        not isinstance(name, str)
        or _ENVIRONMENT_NAME.fullmatch(name) is None
        or not isinstance(value, str)
        for name, value in parsed.items()
    ):
        raise SmokeConfigurationError("invalid_configuration")
    values = {name: value for name, value in parsed.items() if value is not None}
    values.setdefault("DEMO_SUPPRESS_NOTIFICATIONS", "true")
    with _temporary_environment(values):
        try:
            settings = AppSettings()
        except ValueError:
            raise SmokeConfigurationError("invalid_configuration") from None
        yield settings


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
    affected_names = set(values) | _ISOLATED_SETTING_NAMES
    original = {name: os.environ.get(name) for name in affected_names}
    try:
        for name in _ISOLATED_SETTING_NAMES:
            os.environ.pop(name, None)
        os.environ.update(values)
        yield
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _stable_agent_configuration_valid(settings: object) -> bool:
    project_endpoint = getattr(
        settings,
        "azure_ai_foundry_agent_project_endpoint",
        None,
    )
    stable_endpoint = getattr(
        settings,
        "azure_ai_foundry_agent_endpoint",
        None,
    )
    agent_name = getattr(settings, "azure_ai_foundry_agent_name", None)
    return bool(
        is_valid_stable_agent_endpoint(stable_endpoint)
        and stable_agent_endpoint_matches_configuration(
            project_endpoint=project_endpoint,
            stable_agent_endpoint=stable_endpoint,
            agent_name=agent_name,
        )
    )


def _agent_failure_category(error: BaseException) -> SmokeCategory:
    if any(
        isinstance(candidate, FoundryExtractionContractError)
        for candidate in _exception_chain(error)
    ):
        return "invalid_agent_output"
    for candidate in _exception_chain(error):
        status_code = getattr(candidate, "status_code", None)
        if status_code == 401:
            return "authentication_failure"
        if status_code == 403:
            return "authorization_failure"
        if _is_authentication_error(candidate):
            return "authentication_failure"
    if isinstance(error, FoundryAgentClientError):
        return "agent_invocation_failure"
    return "agent_invocation_failure"


def _is_authentication_error(error: BaseException) -> bool:
    exception_type = error.__class__
    return (exception_type.__module__, exception_type.__name__) in {
        ("azure.core.exceptions", "ClientAuthenticationError"),
        ("azure.identity._exceptions", "AuthenticationRequiredError"),
        ("azure.identity._exceptions", "CredentialUnavailableError"),
    }


def _exception_chain(error: BaseException) -> tuple[BaseException, ...]:
    values: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(values) < 8:
        values.append(current)
        next_error = current.__cause__ or current.__context__
        current = next_error if isinstance(next_error, BaseException) else None
    return tuple(values)


def _close_agent_client(agent: FoundryNurseIntakeAgent) -> None:
    live_client = getattr(agent, "client", None)
    responses_client = getattr(live_client, "_responses_client", None)
    for candidate in (responses_client, live_client):
        close = getattr(candidate, "close", None)
        if not callable(close):
            continue
        try:
            close_result = close()
            if inspect.isawaitable(close_result):
                asyncio.run(close_result)
        except Exception:
            pass
        return


def _fixed_input_valid() -> bool:
    normalized = FIXED_FICTIONAL_INTAKE.casefold()
    return bool(
        "fictional" in normalized
        and "chest pain" in normalized
        and "shortness of breath" in normalized
        and "+1" not in FIXED_FICTIONAL_INTAKE
        and "555" not in FIXED_FICTIONAL_INTAKE
        and "@" not in FIXED_FICTIONAL_INTAKE
    )


def _matches_expected(value: object, expected: str) -> bool:
    return isinstance(value, str) and value.strip().casefold() == expected


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _emit_result(
    result: ApplicationFoundryAgentSmokeResult,
    json_output: bool,
    *,
    exit_code: int,
) -> int:
    try:
        _print_result(result, json_output=json_output)
    except Exception:
        try:
            if json_output:
                _write_json_result(
                    _empty_result("unexpected_exception", result.mode)
                )
            else:
                print(GENERIC_FAILURE_MESSAGE, file=sys.stderr)
        except Exception:
            pass
    return exit_code


def _write_json_result(result: ApplicationFoundryAgentSmokeResult) -> None:
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))


def _print_result(
    result: ApplicationFoundryAgentSmokeResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        _write_json_result(result)
        return
    status = "passed" if result.ok else "failed"
    print(
        f"Application Foundry Agent smoke {result.mode} {status}: "
        f"{result.category}."
    )


if __name__ == "__main__":
    raise SystemExit(main())
