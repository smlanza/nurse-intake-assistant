from datetime import datetime, timezone
from pathlib import Path

from src.app.models.case import CaseDocument, CaseType, UrgencySource
from src.app.models.ai_outputs import UrgencyClassificationResult
from src.app.services.case_repository import CaseRepository
from src.app.services.email_notification_sender import (
    EmailNotificationSender,
    MockEmailNotificationSender,
)
from src.app.services.mock_ai_service import MockAiService
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

    _SUPPORTED_CASE_TYPES: tuple[CaseType, ...] = (
        "text-intake",
        "phone-intake",
        "audio-upload",
    )

    def __init__(
        self,
        ai_service: MockAiService | None = None,
        rules_service: UrgencyRulesService | None = None,
        case_repository: CaseRepository | None = None,
        email_notification_sender: EmailNotificationSender | None = None,
        sms_notification_sender: SmsNotificationSender | None = None,
        suppress_notifications: bool = False,
    ) -> None:
        self.ai_service = ai_service or MockAiService()
        self.rules_service = rules_service or UrgencyRulesService(
            Path(__file__).parents[1] / "config" / "red_flags.yaml"
        )
        self.case_repository = case_repository
        self.email_notification_sender = email_notification_sender
        self.sms_notification_sender = sms_notification_sender
        self.suppress_notifications = suppress_notifications

    async def process(self, raw_text: str, case_type: CaseType) -> CaseDocument:
        """Process supplied text into a completed case document."""
        if case_type not in self._SUPPORTED_CASE_TYPES:
            raise ValueError(f"Unsupported case type: {case_type}")

        extraction = await self.ai_service.extract_and_summarize(raw_text)
        ai_urgency = await self.ai_service.classify_urgency(raw_text)
        rule_result = self.rules_service.evaluate(raw_text)

        urgency_source = self._merge_urgency_source(ai_urgency, rule_result)
        final_urgency = (
            "Urgent"
            if rule_result.urgency == "Urgent" or ai_urgency.urgency == "Urgent"
            else "Routine"
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
            urgencyRationale=self._build_urgency_rationale(
                ai_urgency,
                rule_result,
            ),
            missingFields=extraction.missing_fields,
            uncertainFields=extraction.uncertain_fields,
            intakeComplete=not extraction.missing_fields,
            processingStatus="Completed",
            intakeStatus=(
                "NeedsFollowUp" if extraction.missing_fields else "Complete"
            ),
            reviewStatus="PendingReview",
        )

        self._apply_email_notification_status(case)
        self._apply_sms_notification_status(case)

        if self.case_repository is not None:
            await self.case_repository.save(case)

        return case

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
        ai_urgency: UrgencyClassificationResult,
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
    def _build_urgency_rationale(
        ai_urgency: UrgencyClassificationResult,
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
