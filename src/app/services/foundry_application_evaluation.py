"""Offline evaluation through the production application composition boundary."""

import asyncio
from copy import copy
from enum import Enum
from typing import Literal, Mapping

from pydantic import ValidationError

from src.app.application_composition import (
    ApplicationComposition,
    compose_application,
)
from src.app.config.settings import AppSettings
from src.app.models.case import CaseDocument
from src.app.services.case_repository import InMemoryCaseRepository
from src.app.services.email_notification_sender import MockEmailNotificationSender
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.foundry_evaluation import (
    EvaluationCandidate,
    EvaluationDataset,
    EvaluationReport,
    evaluate_dataset,
)
from src.app.services.foundry_evaluation_adapters import (
    adapt_foundry_ai_service_output,
    adapt_nurse_intake_agent_output,
)
from src.app.services.mock_ai_service import MockAiService
from src.app.services.nurse_intake_agent import FoundryNurseIntakeAgent
from src.app.services.sms_notification_sender import MockSmsNotificationSender


class ApplicationEvaluationMode(str, Enum):
    STRUCTURED_EXTRACTION = "structured-extraction"
    AGENT = "agent"


ApplicationEvaluationErrorCategory = Literal[
    "invalid_mode",
    "invalid_dataset",
    "missing_fake_client",
    "composition_failed",
    "processing_failed",
    "adaptation_failed",
    "invalid_candidate_set",
    "evaluation_failed",
]


class FoundryApplicationEvaluationError(ValueError):
    """Sanitized fail-closed error for offline application evaluation."""

    def __init__(self, category: ApplicationEvaluationErrorCategory) -> None:
        super().__init__("Offline application evaluation failed.")
        self.category = category


def run_foundry_application_evaluation(
    *,
    mode: ApplicationEvaluationMode | str,
    dataset: EvaluationDataset,
    settings: AppSettings,
    fake_client: object,
) -> EvaluationReport:
    """Evaluate one mode over a complete dataset using injected offline behavior."""

    selected_mode = _validated_mode(mode)
    validated_dataset = _validated_dataset(dataset)
    _require_fake_client(selected_mode, fake_client)
    offline_settings = _offline_settings(settings, selected_mode)

    try:
        application = compose_application(offline_settings)
    except Exception:
        raise FoundryApplicationEvaluationError("composition_failed") from None

    _inject_selected_fake(application, selected_mode, fake_client)
    try:
        candidates = asyncio.run(
            _process_complete_dataset(
                application,
                selected_mode,
                validated_dataset,
            )
        )
    except FoundryApplicationEvaluationError:
        raise
    except Exception:
        raise FoundryApplicationEvaluationError("processing_failed") from None
    _require_exact_candidate_keys(validated_dataset, candidates)

    try:
        return evaluate_dataset(validated_dataset, candidates)
    except Exception:
        raise FoundryApplicationEvaluationError("evaluation_failed") from None


def _validated_mode(mode: object) -> ApplicationEvaluationMode:
    try:
        return ApplicationEvaluationMode(mode)
    except (TypeError, ValueError):
        raise FoundryApplicationEvaluationError("invalid_mode") from None


def _validated_dataset(dataset: object) -> EvaluationDataset:
    try:
        payload = dataset.model_dump(mode="json")
        return EvaluationDataset.model_validate(payload)
    except (AttributeError, TypeError, ValidationError, ValueError):
        raise FoundryApplicationEvaluationError("invalid_dataset") from None


def _require_fake_client(
    mode: ApplicationEvaluationMode,
    fake_client: object,
) -> None:
    method_name = (
        "complete_structured_extraction"
        if mode is ApplicationEvaluationMode.STRUCTURED_EXTRACTION
        else "invoke_agent"
    )
    if fake_client is None or not callable(getattr(fake_client, method_name, None)):
        raise FoundryApplicationEvaluationError("missing_fake_client")


def _offline_settings(
    settings: AppSettings,
    mode: ApplicationEvaluationMode,
) -> AppSettings:
    try:
        configured = copy(settings)
        configured.app_mode = "mock"
        configured.demo_suppress_notifications = True
        configured.email_provider = "mock"
        configured.email_provider_normalized = "mock"
        configured.sms_provider = "mock"
        configured.sms_provider_normalized = "mock"
        if mode is ApplicationEvaluationMode.STRUCTURED_EXTRACTION:
            configured.ai_provider = "foundry"
            configured.ai_provider_normalized = "foundry"
            configured.agent_provider = "mock"
            configured.agent_provider_normalized = "mock"
        else:
            configured.ai_provider = "mock"
            configured.ai_provider_normalized = "mock"
            configured.agent_provider = "foundry-agent"
            configured.agent_provider_normalized = "foundry-agent"
        return configured
    except Exception:
        raise FoundryApplicationEvaluationError("composition_failed") from None


def _inject_selected_fake(
    application: ApplicationComposition,
    mode: ApplicationEvaluationMode,
    fake_client: object,
) -> None:
    if not isinstance(application.case_repository, InMemoryCaseRepository):
        raise FoundryApplicationEvaluationError("composition_failed")
    if not isinstance(
        application.email_notification_sender,
        MockEmailNotificationSender,
    ) or not isinstance(
        application.sms_notification_sender,
        MockSmsNotificationSender,
    ):
        raise FoundryApplicationEvaluationError("composition_failed")
    if application.case_processing_service.suppress_notifications is not True:
        raise FoundryApplicationEvaluationError("composition_failed")

    if mode is ApplicationEvaluationMode.STRUCTURED_EXTRACTION:
        if not isinstance(application.ai_service, FoundryAiService):
            raise FoundryApplicationEvaluationError("composition_failed")
        if application.nurse_intake_agent is not None:
            raise FoundryApplicationEvaluationError("composition_failed")
        application.ai_service.client = fake_client
        return

    if not isinstance(application.ai_service, MockAiService) or not isinstance(
        application.nurse_intake_agent,
        FoundryNurseIntakeAgent,
    ):
        raise FoundryApplicationEvaluationError("composition_failed")
    application.nurse_intake_agent.client = fake_client


async def _process_complete_dataset(
    application: ApplicationComposition,
    mode: ApplicationEvaluationMode,
    dataset: EvaluationDataset,
) -> dict[str, EvaluationCandidate]:
    candidates: dict[str, EvaluationCandidate] = {}
    for evaluation_case in dataset.cases:
        try:
            case = await application.case_processing_service.process(
                evaluation_case.intake_text,
                "text-intake",
            )
        except Exception:
            raise FoundryApplicationEvaluationError("processing_failed") from None
        if not isinstance(case, CaseDocument):
            raise FoundryApplicationEvaluationError("processing_failed")
        _require_suppressed_notifications(application, case)
        try:
            candidate = (
                adapt_foundry_ai_service_output(case)
                if mode is ApplicationEvaluationMode.STRUCTURED_EXTRACTION
                else adapt_nurse_intake_agent_output(case)
            )
        except Exception:
            raise FoundryApplicationEvaluationError("adaptation_failed") from None
        if not isinstance(candidate, EvaluationCandidate):
            raise FoundryApplicationEvaluationError("adaptation_failed")
        candidates[evaluation_case.case_id] = candidate
    return candidates


def _require_suppressed_notifications(
    application: ApplicationComposition,
    case: CaseDocument,
) -> None:
    email_sender = application.email_notification_sender
    sms_sender = application.sms_notification_sender
    if (
        case.notificationEmailStatus != "Suppressed"
        or case.notificationSmsStatus != "Suppressed"
        or case.notificationEmailSent
        or case.notificationSmsSent
        or email_sender.sent_notifications
        or sms_sender.sent_notifications
    ):
        raise FoundryApplicationEvaluationError("processing_failed")


def _require_exact_candidate_keys(
    dataset: EvaluationDataset,
    candidates: Mapping[str, object],
) -> None:
    expected = {case.case_id for case in dataset.cases}
    if set(candidates) != expected:
        raise FoundryApplicationEvaluationError("invalid_candidate_set")
