import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterator, Literal


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
from src.app.services.daily_azure_environment_rebuild import (
    ConfigValidationError,
    DailyAzureConfig,
    DailyAzureReadinessReceipt,
    READINESS_RECEIPT_FILE,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)
from src.app.services.email_notification_sender import (
    MockEmailNotificationSender,
)
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
)
from src.app.services.sms_notification_sender import MockSmsNotificationSender


OPERATION = "smoke_application_foundry_extraction"
FIXED_FICTIONAL_INTAKE = (
    "Fictional patient Avery Example, date of birth 2000-01-01, with callback "
    "identifier fictional-callback-only, reports new chest pain and shortness "
    "of breath. This is fixed fictional test data requiring nurse review."
)
GENERIC_INVOCATION_FAILURE = "Application Foundry smoke invocation failed."

SmokeMode = Literal["check", "live"]
SmokeCategory = Literal[
    "success", "invalid_arguments", "fixed_input_invalid", "missing_configuration",
    "invalid_configuration", "readiness_receipt_invalid", "unsafe_configuration",
    "composition_failed", "authentication_failed", "authorization_failed",
    "provider_request_failed", "model_response_invalid", "processing_failed",
    "persistence_failed", "result_contract_invalid", "unexpected_error",
]

FAILURE_NEXT_STEP = "Review the sanitized failure without exposing private details."
SUCCESS_NEXT_STEP = "Review the sanitized proof and restore the mock-only workflow."
READINESS_NEXT_STEP = (
    "Obtain current readiness evidence; do not run rebuild or cleanup concurrently."
)


def _next_step(category: SmokeCategory) -> str:
    if category == "success":
        return SUCCESS_NEXT_STEP
    if category == "readiness_receipt_invalid":
        return READINESS_NEXT_STEP
    return FAILURE_NEXT_STEP


@dataclass(frozen=True)
class ApplicationFoundrySmokeReadiness:
    ready: bool
    category: SmokeCategory
    missing_settings: tuple[str, ...] = ()
    unsafe_settings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplicationFoundrySmokeConfiguration:
    settings: AppSettings
    daily_config: DailyAzureConfig
    readiness_receipt: DailyAzureReadinessReceipt


@dataclass(frozen=True)
class ApplicationFoundrySmokeResult:
    ok: bool
    category: SmokeCategory
    mode: SmokeMode
    fictional_data: bool = True
    local_composition_validated: bool = False
    case_processing_service_used: bool = False
    ai_provider_verified: bool = False
    foundry_invocation_attempted: bool = False
    foundry_output_valid: bool = False
    fallback_used: bool = False
    deterministic_rules_evaluated: bool = False
    rules_promoted_urgency: bool = False
    case_document_valid: bool = False
    case_persisted_in_memory: bool = False
    notifications_suppressed: bool = False
    notification_attempted: bool = False
    nurse_review_required: bool = True
    azure_mutation_attempted: bool = False
    missing_settings: tuple[str, ...] = ()
    unsafe_settings: tuple[str, ...] = ()
    recommended_next_step: str = FAILURE_NEXT_STEP

    def to_json_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["operation"] = OPERATION
        return result


SAFE_RESULT_FIELDS = {
    *(field.name for field in fields(ApplicationFoundrySmokeResult)),
    "operation",
}


class SmokeConfigurationError(ValueError):
    def __init__(self, category: SmokeCategory) -> None:
        super().__init__("Application Foundry smoke configuration is invalid.")
        self.category = category


class _InvalidArgumentsError(Exception):
    pass


class _FinalReadinessError(Exception):
    pass


class _SanitizedArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _InvalidArgumentsError from None


class _FinalReadinessTrackingAiService:
    provider = "foundry"

    def __init__(
        self,
        delegate: FoundryAiService,
        configuration: ApplicationFoundrySmokeConfiguration,
    ) -> None:
        self.delegate = delegate
        self.configuration = configuration
        self.invocation_attempted = False

    async def extract_and_summarize(self, raw_text: str):
        _revalidate_readiness(self.configuration)
        self.invocation_attempted = True
        return await self.delegate.extract_and_summarize(raw_text)

    async def classify_urgency(self, raw_text: str):
        return await self.delegate.classify_urgency(raw_text)


class _PersistenceTrackingRepository:
    def __init__(self, delegate: InMemoryCaseRepository) -> None:
        self.delegate = delegate
        self.save_attempted = False
        self.saved_case: CaseDocument | None = None

    async def save(self, case: CaseDocument) -> CaseDocument:
        self.save_attempted = True
        saved = await self.delegate.save(case)
        self.saved_case = saved
        return saved

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
    json_requested = False
    requested_mode: SmokeMode = "check"
    try:
        raw_argv = list(sys.argv[1:] if argv is None else argv)
        json_requested = "--json" in raw_argv
        requested_mode = "live" if "--live" in raw_argv else "check"
        try:
            args = _parse_args(raw_argv)
        except _InvalidArgumentsError:
            return _emit_parser_failure(json_requested, requested_mode)

        configuration = _load_application_configuration(args.config)
        readiness = build_application_foundry_smoke_readiness(configuration.settings)
        if args.check:
            result = _check_result(readiness)
            _print_result(result, json_output=args.json)
            return 0 if result.ok else 2

        if not readiness.ready:
            result = _result_from_readiness(readiness, "live")
            _print_result(result, json_output=True)
            return 2

        result = run_application_foundry_smoke(configuration)
        _print_result(result, json_output=True)
        if result.ok:
            return 0
        if result.category in {
            "missing_configuration",
            "invalid_configuration",
            "readiness_receipt_invalid",
            "unsafe_configuration",
        }:
            return 2
        return 1
    except SmokeConfigurationError as error:
        result = _empty_result(error.category, requested_mode)
        return _emit_contained_result(result, json_requested, exit_code=2)
    except Exception:
        result = _empty_result("unexpected_error", requested_mode)
        return _emit_contained_result(result, json_requested, exit_code=1)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = _SanitizedArgumentParser(
        description=(
            "Run one fixed fictional intake through the application-integrated "
            "Azure AI Foundry structured-extraction boundary."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Validate the local smoke contract without clients or external calls.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help="Process the fixed fictional intake with one live Foundry request.",
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
        help="Path to the ignored daily Azure configuration.",
    )
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("invalid argument combination")
    return args


def build_application_foundry_smoke_readiness(
    settings: object,
) -> ApplicationFoundrySmokeReadiness:
    if not _fixed_input_valid():
        return ApplicationFoundrySmokeReadiness(False, "fixed_input_invalid")

    required_settings = {
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT": "azure_ai_foundry_project_endpoint",
        "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": (
            "azure_ai_foundry_model_deployment_name"
        ),
    }
    missing = tuple(
        name
        for name, attribute in required_settings.items()
        if not _nonblank(getattr(settings, attribute, None))
    )
    expected_settings = {
        "APP_MODE": ("app_mode", "mock"),
        "AI_PROVIDER": ("ai_provider_normalized", "foundry"),
        "AGENT_PROVIDER": ("agent_provider_normalized", "mock"),
        "EMAIL_PROVIDER": ("email_provider_normalized", "mock"),
        "SMS_PROVIDER": ("sms_provider_normalized", "mock"),
    }
    unsafe = [
        name
        for name, (attribute, expected) in expected_settings.items()
        if not isinstance((actual := getattr(settings, attribute, None)), str)
        or actual.strip().casefold() != expected
    ]
    if getattr(settings, "demo_suppress_notifications", None) is not True:
        unsafe.append("DEMO_SUPPRESS_NOTIFICATIONS")

    category: SmokeCategory
    if missing:
        category = "missing_configuration"
    elif unsafe:
        category = "unsafe_configuration"
    else:
        category = "success"
    return ApplicationFoundrySmokeReadiness(
        ready=category == "success",
        category=category,
        missing_settings=missing,
        unsafe_settings=tuple(unsafe),
    )


def run_application_foundry_smoke(
    configuration: ApplicationFoundrySmokeConfiguration,
) -> ApplicationFoundrySmokeResult:
    readiness = build_application_foundry_smoke_readiness(configuration.settings)
    if not readiness.ready:
        return _result_from_readiness(readiness, "live")

    try:
        application = compose_application(configuration.settings)
    except Exception:
        return _empty_result("composition_failed", "live")
    if not _composition_is_safe(application):
        return _empty_result("composition_failed", "live")

    tracked_ai = _FinalReadinessTrackingAiService(
        application.ai_service,
        configuration,
    )
    tracked_repository = _PersistenceTrackingRepository(application.case_repository)
    service = application.case_processing_service
    rules_tracker = _RulesExecutionTracker(service.rules_service)
    service.ai_service = tracked_ai
    service.case_repository = tracked_repository
    service.rules_service = rules_tracker
    try:
        try:
            case = asyncio.run(service.process(FIXED_FICTIONAL_INTAKE, "text-intake"))
        except _FinalReadinessError:
            return _failed_execution_result(
                "readiness_receipt_invalid",
                tracked_ai,
                tracked_repository,
                application,
                rules_tracker,
            )
        except FoundryExtractionContractError:
            return _failed_execution_result(
                "model_response_invalid",
                tracked_ai,
                tracked_repository,
                application,
                rules_tracker,
            )
        except Exception as error:
            if tracked_repository.save_attempted:
                category: SmokeCategory = "persistence_failed"
            elif tracked_ai.invocation_attempted:
                category = _provider_failure_category(error)
            else:
                category = "processing_failed"
            return _failed_execution_result(
                category,
                tracked_ai,
                tracked_repository,
                application,
                rules_tracker,
            )

        return _success_or_contract_failure(
            case,
            application,
            tracked_ai,
            tracked_repository,
            rules_tracker,
        )
    finally:
        _close_foundry_live_client(application.ai_service)


def _composition_is_safe(application: ApplicationComposition) -> bool:
    service = application.case_processing_service
    return bool(
        isinstance(application.ai_service, FoundryAiService)
        and type(application.case_repository) is InMemoryCaseRepository
        and type(application.email_notification_sender)
        is MockEmailNotificationSender
        and type(application.sms_notification_sender) is MockSmsNotificationSender
        and application.nurse_intake_agent is None
        and isinstance(service, CaseProcessingService)
        and service.ai_service is application.ai_service
        and service.case_repository is application.case_repository
        and service.email_notification_sender
        is application.email_notification_sender
        and service.sms_notification_sender is application.sms_notification_sender
        and service.nurse_intake_agent is None
        and service.suppress_notifications is True
    )


def _revalidate_readiness(
    configuration: ApplicationFoundrySmokeConfiguration,
) -> None:
    current = load_matching_daily_azure_readiness_receipt(
        PROJECT_ROOT / READINESS_RECEIPT_FILE,
        configuration.daily_config,
    )
    if current is None or current != configuration.readiness_receipt:
        raise _FinalReadinessError from None


def _success_or_contract_failure(
    case: object,
    application: ApplicationComposition,
    tracked_ai: _FinalReadinessTrackingAiService,
    tracked_repository: _PersistenceTrackingRepository,
    rules_tracker: _RulesExecutionTracker,
) -> ApplicationFoundrySmokeResult:
    case_valid = isinstance(case, CaseDocument)
    trace = case.processing_trace if case_valid else None
    foundry_output_valid = bool(
        case_valid
        and trace is not None
        and trace.ai_provider == "foundry"
        and trace.agent_used is False
        and case.aiUrgency in {"Routine", "Urgent"}
    )
    rules_evaluated = bool(
        rules_tracker.attempt_count == 1
        and rules_tracker.completed
    )
    rules_promoted = bool(
        rules_evaluated
        and trace is not None
        and trace.rules_urgency_override is True
        and case.urgency == "Urgent"
        and case.urgencySource == "Rules"
    )
    stored_cases = asyncio.run(application.case_repository.list_cases())
    persisted = bool(
        case_valid
        and tracked_repository.saved_case is case
        and len(stored_cases) == 1
        and stored_cases[0] is case
    )
    email_attempts = application.email_notification_sender.sent_notifications
    sms_attempts = application.sms_notification_sender.sent_notifications
    notification_attempted = bool(email_attempts or sms_attempts)
    notifications_suppressed = bool(
        case_valid
        and case.notificationEmailStatus == "Suppressed"
        and case.notificationSmsStatus == "Suppressed"
    )
    nurse_review_required = bool(
        case_valid and case.reviewStatus == "PendingReview"
    )
    success = bool(
        foundry_output_valid
        and tracked_ai.invocation_attempted
        and rules_evaluated
        and persisted
        and notifications_suppressed
        and not notification_attempted
        and nurse_review_required
    )
    category: SmokeCategory = "success" if success else "result_contract_invalid"
    return ApplicationFoundrySmokeResult(
        ok=success,
        category=category,
        mode="live",
        local_composition_validated=True,
        case_processing_service_used=True,
        ai_provider_verified=True,
        foundry_invocation_attempted=tracked_ai.invocation_attempted,
        foundry_output_valid=foundry_output_valid,
        deterministic_rules_evaluated=rules_evaluated,
        rules_promoted_urgency=rules_promoted,
        case_document_valid=case_valid,
        case_persisted_in_memory=persisted,
        notifications_suppressed=notifications_suppressed,
        notification_attempted=notification_attempted,
        nurse_review_required=nurse_review_required,
        recommended_next_step=_next_step(category),
    )


def _failed_execution_result(
    category: SmokeCategory,
    tracked_ai: _FinalReadinessTrackingAiService,
    tracked_repository: _PersistenceTrackingRepository,
    application: ApplicationComposition,
    rules_tracker: _RulesExecutionTracker,
) -> ApplicationFoundrySmokeResult:
    notification_attempted = bool(
        application.email_notification_sender.sent_notifications
        or application.sms_notification_sender.sent_notifications
    )
    return ApplicationFoundrySmokeResult(
        ok=False,
        category=category,
        mode="live",
        local_composition_validated=True,
        case_processing_service_used=True,
        ai_provider_verified=True,
        foundry_invocation_attempted=tracked_ai.invocation_attempted,
        deterministic_rules_evaluated=bool(
            rules_tracker.attempt_count == 1
            and rules_tracker.completed
        ),
        case_persisted_in_memory=tracked_repository.saved_case is not None,
        notification_attempted=notification_attempted,
        nurse_review_required=False,
        recommended_next_step=_next_step(category),
    )


def _check_result(
    readiness: ApplicationFoundrySmokeReadiness,
) -> ApplicationFoundrySmokeResult:
    if not readiness.ready:
        return _result_from_readiness(readiness, "check")
    return ApplicationFoundrySmokeResult(
        ok=True,
        category="success",
        mode="check",
        local_composition_validated=True,
        ai_provider_verified=True,
        notifications_suppressed=True,
        recommended_next_step=(
            "Run the supervised live command only after reviewing this offline result."
        ),
    )


def _result_from_readiness(
    readiness: ApplicationFoundrySmokeReadiness,
    mode: SmokeMode,
) -> ApplicationFoundrySmokeResult:
    return ApplicationFoundrySmokeResult(
        **{
            **_empty_result(readiness.category, mode).__dict__,
            "missing_settings": readiness.missing_settings,
            "unsafe_settings": readiness.unsafe_settings,
        }
    )


def _empty_result(
    category: SmokeCategory,
    mode: SmokeMode,
) -> ApplicationFoundrySmokeResult:
    return ApplicationFoundrySmokeResult(
        ok=False,
        category=category,
        mode=mode,
        recommended_next_step=_next_step(category),
    )


def _load_application_configuration(
    config_path: Path | str,
) -> ApplicationFoundrySmokeConfiguration:
    try:
        daily_config = load_daily_azure_config(
            config_path,
            repository_root=PROJECT_ROOT,
        )
    except ConfigValidationError as error:
        category: SmokeCategory = (
            "missing_configuration"
            if error.category == "missing_configuration"
            else "invalid_configuration"
        )
        raise SmokeConfigurationError(category) from None

    receipt = load_matching_daily_azure_readiness_receipt(
        PROJECT_ROOT / READINESS_RECEIPT_FILE,
        daily_config,
    )
    if receipt is None:
        raise SmokeConfigurationError("readiness_receipt_invalid")

    project_endpoint = (
        f"https://{receipt.foundry_account_name}.services.ai.azure.com/"
        f"api/projects/{receipt.foundry_project_name}"
    )
    with _temporary_environment(
        {
            "APP_MODE": "mock",
            "AI_PROVIDER": "foundry",
            "AGENT_PROVIDER": "mock",
            "EMAIL_PROVIDER": "mock",
            "SMS_PROVIDER": "mock",
            "DEMO_SUPPRESS_NOTIFICATIONS": "true",
            "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT": project_endpoint,
            "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME": (
                daily_config.model_deployment_name
            ),
        }
    ):
        settings = AppSettings()
    return ApplicationFoundrySmokeConfiguration(
        settings=settings,
        daily_config=daily_config,
        readiness_receipt=receipt,
    )


@contextmanager
def _temporary_environment(values: dict[str, str]) -> Iterator[None]:
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


def _provider_failure_category(error: BaseException) -> SmokeCategory:
    for candidate in _exception_chain(error):
        if isinstance(candidate, FoundryExtractionContractError):
            return "model_response_invalid"
        status_code = getattr(candidate, "status_code", None)
        if status_code == 401:
            return "authentication_failed"
        if status_code == 403:
            return "authorization_failed"
        if _is_token_acquisition_error(candidate):
            return "authentication_failed"
    return "provider_request_failed"


def _is_token_acquisition_error(error: BaseException) -> bool:
    exception_type = error.__class__
    return (exception_type.__module__, exception_type.__name__) in {
        ("azure.core.exceptions", "ClientAuthenticationError"),
        ("azure.identity._exceptions", "AuthenticationRequiredError"),
        ("azure.identity._exceptions", "CredentialUnavailableError"),
    }


def _close_foundry_live_client(ai_service: FoundryAiService) -> None:
    client = ai_service.client
    close = getattr(client, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


def _exception_chain(error: BaseException) -> tuple[BaseException, ...]:
    values: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(values) < 8:
        values.append(current)
        next_error = current.__cause__ or current.__context__
        current = next_error if isinstance(next_error, BaseException) else None
    return tuple(values)


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


def _nonblank(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _emit_parser_failure(json_output: bool, mode: SmokeMode) -> int:
    result = _empty_result("invalid_arguments", mode)
    if json_output:
        _write_json_result(result)
    else:
        print(GENERIC_INVOCATION_FAILURE, file=sys.stderr)
    return 2


def _emit_contained_result(
    result: ApplicationFoundrySmokeResult,
    json_output: bool,
    *,
    exit_code: int,
) -> int:
    try:
        _print_result(result, json_output=json_output)
    except Exception:
        try:
            if json_output:
                _write_json_result(_empty_result("unexpected_error", result.mode))
            else:
                print(GENERIC_INVOCATION_FAILURE, file=sys.stderr)
        except Exception:
            pass
    return exit_code


def _write_json_result(result: ApplicationFoundrySmokeResult) -> None:
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))


def _print_result(
    result: ApplicationFoundrySmokeResult,
    *,
    json_output: bool,
) -> None:
    if json_output:
        _write_json_result(result)
        return
    status = "passed" if result.ok else "failed"
    print(f"Application Foundry smoke {result.mode} {status}: {result.category}.")


if __name__ == "__main__":
    raise SystemExit(main())
