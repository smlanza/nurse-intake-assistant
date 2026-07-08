from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)
from src.app.models.case import (
    CaseDocument,
    CaseType,
    ProcessingTrace,
    UrgencySource,
)
from src.app.services.case_repository import CaseRepository
from src.app.services.email_notification_sender import (
    EmailNotificationSender,
    MockEmailNotificationSender,
)
from src.app.services.mock_ai_service import MockAiService
from src.app.services.nurse_intake_agent_contract import (
    validate_nurse_intake_agent_result,
)
from src.app.services.sms_notification_sender import (
    MockSmsNotificationSender,
    SmsNotificationSender,
)
from src.app.services.urgency_rules_service import (
    RuleEvaluationResult,
    UrgencyRulesService,
)


class CaseProcessingService:
    """Orchestrate intake extraction, urgency, persistence, and notification."""

    _AGENT_CONTRACT_FALLBACK_SUMMARY = (
        "Agent output could not be safely parsed. Nurse review required."
    )
    _AGENT_CONTRACT_FALLBACK_RATIONALE = (
        "Agent output failed contract validation; safe fallback values were used."
    )
    _AGENT_EXECUTION_FALLBACK_RATIONALE = (
        "Agent execution failed; safe fallback values were used."
    )
    _SAFE_AGENT_PROVIDERS = {"mock", "foundry", "foundry-agent"}
    _SAFE_AGENT_MODES = {"mock", "fake", "foundry-agent"}
    _SUPPORTED_CASE_TYPES: tuple[CaseType, ...] = (
        "text-intake",
        "phone-intake",
        "audio-upload",
    )
    _AGENT_STEPS: tuple[str, ...] = (
        "agent.extract_summary",
        "agent.classify_urgency",
        "rules.apply_red_flags",
        "case.persist",
        "notifications.send",
    )
    _AI_STEPS: tuple[str, ...] = (
        "ai.extract_summary",
        "ai.classify_urgency",
        "rules.apply_red_flags",
        "case.persist",
        "notifications.send",
    )

    def __init__(
        self,
        ai_service: MockAiService | None = None,
        rules_service: UrgencyRulesService | None = None,
        case_repository: CaseRepository | None = None,
        email_notification_sender: EmailNotificationSender | None = None,
        sms_notification_sender: SmsNotificationSender | None = None,
        nurse_intake_agent: object | None = None,
        suppress_notifications: bool = False,
    ) -> None:
        self.ai_service = ai_service or MockAiService()
        self.rules_service = rules_service or UrgencyRulesService(
            Path(__file__).parents[1] / "config" / "red_flags.yaml"
        )
        self.case_repository = case_repository
        self.email_notification_sender = email_notification_sender
        self.sms_notification_sender = sms_notification_sender
        self.nurse_intake_agent = nurse_intake_agent
        self.suppress_notifications = suppress_notifications

    async def process(self, raw_text: str, case_type: CaseType) -> CaseDocument:
        """Process supplied text into a completed case document."""
        if case_type not in self._SUPPORTED_CASE_TYPES:
            raise ValueError(f"Unsupported case type: {case_type}")

        agent_result = None
        processing_trace_warnings: list[str] = []
        agent_contract_valid = True
        agent_fallback_reason = None
        agent_used = self.nurse_intake_agent is not None
        if agent_used:
            try:
                agent_result = await self.nurse_intake_agent.analyze_intake(raw_text)
                validation_result = validate_nurse_intake_agent_result(agent_result)
                if validation_result.is_valid:
                    extraction = agent_result.extraction
                    ai_urgency = agent_result.urgency
                else:
                    agent_contract_valid = False
                    agent_fallback_reason = "invalid_agent_output"
                    processing_trace_warnings.append(
                        self._AGENT_CONTRACT_FALLBACK_RATIONALE
                    )
                    extraction = self._build_agent_contract_fallback_extraction()
                    ai_urgency = self._build_agent_contract_fallback_urgency(
                        self._AGENT_CONTRACT_FALLBACK_RATIONALE
                    )
            except Exception:
                agent_contract_valid = False
                agent_fallback_reason = "agent_execution_failed"
                processing_trace_warnings.append(
                    self._AGENT_EXECUTION_FALLBACK_RATIONALE
                )
                extraction = self._build_agent_contract_fallback_extraction()
                ai_urgency = self._build_agent_contract_fallback_urgency(
                    self._AGENT_EXECUTION_FALLBACK_RATIONALE
                )
        else:
            extraction = await self.ai_service.extract_and_summarize(raw_text)
            ai_urgency = await self.ai_service.classify_urgency(raw_text)
        rule_result = self.rules_service.evaluate(raw_text)

        urgency_source = self._merge_urgency_source(ai_urgency, rule_result)
        final_urgency = self._merge_final_urgency(ai_urgency, rule_result)
        urgency_rationale = (
            ai_urgency.urgency_rationale
            if not agent_contract_valid
            else self._build_urgency_rationale(
                ai_urgency,
                rule_result,
            )
        )
        now = datetime.now(timezone.utc)

        case = CaseDocument(
            createdDate=now.date().isoformat(),
            createdUtc=now,
            lastStatusUpdatedUtc=now,
            caseType=case_type,
            patient=extraction.patient,
            reasonForCalling=extraction.reason_for_calling,
            symptoms=extraction.symptoms,
            transcript=raw_text,
            summary=extraction.summary,
            urgency=final_urgency,
            urgencySource=urgency_source,
            ruleUrgency=rule_result.urgency,
            aiUrgency=ai_urgency.urgency,
            urgencyRationale=urgency_rationale,
            missingFields=extraction.missing_fields,
            uncertainFields=extraction.uncertain_fields,
            intakeComplete=agent_contract_valid and not extraction.missing_fields,
            processingStatus="Completed",
            intakeStatus=(
                "NeedsFollowUp"
                if not agent_contract_valid or extraction.missing_fields
                else "Complete"
            ),
            reviewStatus="PendingReview",
            processing_trace=self._build_processing_trace(
                agent_used=agent_used,
                agent_contract_valid=agent_contract_valid,
                agent_fallback_reason=agent_fallback_reason,
                nurse_intake_agent=self.nurse_intake_agent,
                agent_result=agent_result,
                ai_urgency=ai_urgency,
                rule_result=rule_result,
                warnings=processing_trace_warnings,
            ),
        )

        self._apply_email_notification_status(case)
        self._apply_sms_notification_status(case)

        if self.case_repository is not None:
            await self.case_repository.save(case)

        return case

    def _build_processing_trace(
        self,
        *,
        agent_used: bool,
        agent_contract_valid: bool,
        agent_fallback_reason: str | None,
        nurse_intake_agent: object | None,
        agent_result: object | None,
        ai_urgency: object,
        rule_result: RuleEvaluationResult,
        warnings: list[str] | None = None,
    ) -> ProcessingTrace:
        rules_urgency_override = self._rules_override_urgency(
            ai_urgency,
            rule_result,
        )
        if rules_urgency_override:
            final_urgency_source = "rules"
        elif agent_used and not agent_contract_valid:
            final_urgency_source = "unknown"
        elif agent_used:
            final_urgency_source = "agent"
        else:
            final_urgency_source = "ai"

        return ProcessingTrace(
            ai_provider=None if agent_used else self._ai_provider_name(),
            agent_provider=(
                self._agent_provider_name(
                    nurse_intake_agent=nurse_intake_agent,
                    agent_result=agent_result,
                )
                if agent_used
                else None
            ),
            agent_mode=(
                self._agent_mode_name(
                    nurse_intake_agent=nurse_intake_agent,
                    agent_result=agent_result,
                )
                if agent_used
                else None
            ),
            agent_used=agent_used,
            agent_attempted=agent_used,
            agent_output_valid=agent_contract_valid if agent_used else None,
            agent_fallback_used=agent_used and not agent_contract_valid,
            agent_fallback_reason=agent_fallback_reason,
            steps=list(self._AGENT_STEPS if agent_used else self._AI_STEPS),
            rules_urgency_override=rules_urgency_override,
            final_urgency_source=final_urgency_source,
            warnings=warnings or [],
        )

    def _ai_provider_name(self) -> str | None:
        configured_provider = getattr(self.ai_service, "provider", None)
        if isinstance(configured_provider, str):
            return configured_provider

        class_name = self.ai_service.__class__.__name__
        if isinstance(self.ai_service, MockAiService):
            return "mock"
        if class_name == "FoundryAiService":
            return "foundry"
        return class_name

    @classmethod
    def _agent_provider_name(
        cls,
        *,
        nurse_intake_agent: object | None,
        agent_result: object | None,
    ) -> str | None:
        metadata = getattr(agent_result, "metadata", None)
        provider = getattr(metadata, "provider", None)
        safe_provider = cls._safe_agent_provider(provider)
        if safe_provider is not None:
            return safe_provider

        provider = getattr(nurse_intake_agent, "provider", None)
        safe_provider = cls._safe_agent_provider(provider)
        if safe_provider is not None:
            return safe_provider

        settings = getattr(nurse_intake_agent, "settings", None)
        provider = getattr(settings, "agent_provider_normalized", None)
        safe_provider = cls._safe_agent_provider(provider)
        if safe_provider is not None:
            return safe_provider

        return None

    @classmethod
    def _agent_mode_name(
        cls,
        *,
        nurse_intake_agent: object | None,
        agent_result: object | None,
    ) -> str | None:
        metadata = getattr(agent_result, "metadata", None)
        mode = getattr(metadata, "agentMode", None)
        safe_mode = cls._safe_agent_mode(mode)
        if safe_mode is not None:
            return safe_mode

        mode = getattr(nurse_intake_agent, "agentMode", None)
        safe_mode = cls._safe_agent_mode(mode)
        if safe_mode is not None:
            return safe_mode

        provider = cls._agent_provider_name(
            nurse_intake_agent=nurse_intake_agent,
            agent_result=agent_result,
        )
        return "foundry-agent" if provider in {"foundry", "foundry-agent"} else None

    @classmethod
    def _safe_agent_provider(cls, provider: object) -> str | None:
        if isinstance(provider, str) and provider in cls._SAFE_AGENT_PROVIDERS:
            return provider
        return None

    @classmethod
    def _safe_agent_mode(cls, mode: object) -> str | None:
        if isinstance(mode, str) and mode in cls._SAFE_AGENT_MODES:
            return mode
        return None

    @staticmethod
    def _rules_override_urgency(
        ai_urgency: object,
        rule_result: RuleEvaluationResult,
    ) -> bool:
        return rule_result.urgency == "Urgent" and ai_urgency.urgency != "Urgent"

    @classmethod
    def _build_agent_contract_fallback_extraction(cls) -> ExtractionSummaryResult:
        return ExtractionSummaryResult(
            patient=PatientInfo(),
            reason_for_calling=None,
            symptoms=[],
            summary=cls._AGENT_CONTRACT_FALLBACK_SUMMARY,
            missing_fields=["agent_output"],
            uncertain_fields=["agent_output"],
            extraction_notes=cls._AGENT_CONTRACT_FALLBACK_RATIONALE,
        )

    @classmethod
    def _build_agent_contract_fallback_urgency(cls, rationale: str) -> object:
        return SimpleNamespace(
            urgency="Unknown",
            urgency_rationale=rationale,
            advisory_disclaimer="Nurse review required.",
        )

    def _apply_email_notification_status(self, case: CaseDocument) -> None:
        if self.suppress_notifications:
            case.notificationEmailSent = False
            case.notificationEmailStatus = "Suppressed"
            return

        if self.email_notification_sender is None:
            return

        try:
            email_sent = self.email_notification_sender.send_case_notification(
                recipient="nurse@example.com",
                subject=f"New {case.urgency} intake case",
                body=case.summary or "A new intake case is ready for review.",
                case_id=case.id,
            )
        except Exception:
            email_sent = False

        if isinstance(self.email_notification_sender, MockEmailNotificationSender):
            case.notificationEmailSent = email_sent is not False
            case.notificationEmailStatus = (
                "MockRecorded" if case.notificationEmailSent else "Failed"
            )
            return

        if email_sent is True:
            case.notificationEmailSent = True
            case.notificationEmailStatus = "Accepted"
            return

        case.notificationEmailSent = False
        case.notificationEmailStatus = "Failed"

    def _apply_sms_notification_status(self, case: CaseDocument) -> None:
        case.notificationSmsDeliveryConfirmed = False

        if self.suppress_notifications:
            case.notificationSmsSent = False
            case.notificationSmsStatus = "Suppressed"
            return

        if self.sms_notification_sender is None:
            return

        try:
            sms_sent = self.sms_notification_sender.send_case_notification(
                recipient=case.patient.callback_number or "",
                body=case.summary or "A new intake case is ready for review.",
                case_id=case.id,
            )
        except Exception:
            sms_sent = False

        if isinstance(self.sms_notification_sender, MockSmsNotificationSender):
            case.notificationSmsSent = sms_sent is True
            case.notificationSmsStatus = (
                "MockRecorded" if case.notificationSmsSent else "Failed"
            )
            return

        if sms_sent is True:
            case.notificationSmsSent = True
            case.notificationSmsStatus = "Accepted"
            return

        case.notificationSmsSent = False
        case.notificationSmsStatus = "Failed"

    @staticmethod
    def _merge_urgency_source(
        ai_urgency: object,
        rule_result: RuleEvaluationResult,
    ) -> UrgencySource:
        rules_are_urgent = rule_result.urgency == "Urgent"
        ai_is_urgent = ai_urgency.urgency == "Urgent"

        if rules_are_urgent and ai_is_urgent:
            return "RulesAndAI"
        if rules_are_urgent:
            return "Rules"
        if ai_is_urgent:
            return "AI"
        return "Unknown"

    @staticmethod
    def _merge_final_urgency(
        ai_urgency: object,
        rule_result: RuleEvaluationResult,
    ) -> str:
        if rule_result.urgency == "Urgent" or ai_urgency.urgency == "Urgent":
            return "Urgent"
        if ai_urgency.urgency == "Routine":
            return "Routine"
        return "Unknown"

    @staticmethod
    def _build_urgency_rationale(
        ai_urgency: object,
        rule_result: RuleEvaluationResult,
    ) -> str:
        if rule_result.matched_red_flags:
            rule_details = ", ".join(
                f'{match.label} ("{match.matched_term}")'
                for match in rule_result.matched_red_flags
            )
            rule_rationale = f"Red-flag rule match: {rule_details}."
        else:
            rule_rationale = "No red-flag rules matched."

        return (
            f"AI: {ai_urgency.urgency_rationale} "
            f"Rules: {rule_rationale} "
            f"{ai_urgency.advisory_disclaimer}"
        )
