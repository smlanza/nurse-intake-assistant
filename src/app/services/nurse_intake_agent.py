from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    UrgencyClassificationResult,
)
from src.app.models.case import CaseDocument
from src.app.services.case_processing_service import CaseProcessingService
from src.app.services.foundry_agent_client import (
    FoundryAgentRequest,
    create_foundry_agent_client,
)
from src.app.services.foundry_agent_contract import (
    build_foundry_agent_intake_instructions,
    normalize_foundry_agent_intake_response,
)
from src.app.services.mock_ai_service import MockAiService
from src.app.services.nurse_handoff_note_formatter import NurseHandoffNoteFormatter
from src.app.services.urgency_rules_service import UrgencyRulesService


class NurseIntakeAgentMetadata(BaseModel):
    provider: Literal["mock", "foundry", "foundry-agent"]
    agentMode: str


class NurseIntakeAgentResult(BaseModel):
    extraction: ExtractionSummaryResult
    urgency: UrgencyClassificationResult
    handoffNote: str
    metadata: NurseIntakeAgentMetadata


class NurseIntakeAgent(Protocol):
    async def analyze_intake(self, raw_text: str) -> NurseIntakeAgentResult:
        """Analyze intake text without implying a specific model/provider."""


class MockNurseIntakeAgent:
    """Deterministic local nurse intake agent boundary for future agent wiring."""

    _CREATED_UTC = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def __init__(
        self,
        ai_service: MockAiService | None = None,
        rules_service: UrgencyRulesService | None = None,
        handoff_formatter: NurseHandoffNoteFormatter | None = None,
    ) -> None:
        self.ai_service = ai_service or MockAiService()
        self.rules_service = rules_service or UrgencyRulesService(
            Path(__file__).parents[1] / "config" / "red_flags.yaml"
        )
        self.handoff_formatter = handoff_formatter or NurseHandoffNoteFormatter()

    async def analyze_intake(self, raw_text: str) -> NurseIntakeAgentResult:
        extraction = await self.ai_service.extract_and_summarize(raw_text)
        ai_urgency = await self.ai_service.classify_urgency(raw_text)
        rule_result = self.rules_service.evaluate(raw_text)
        final_urgency = (
            "Urgent"
            if rule_result.urgency == "Urgent" or ai_urgency.urgency == "Urgent"
            else "Routine"
        )
        urgency_source = CaseProcessingService._merge_urgency_source(
            ai_urgency,
            rule_result,
        )
        urgency_rationale = CaseProcessingService._build_urgency_rationale(
            ai_urgency,
            rule_result,
        )
        urgency = UrgencyClassificationResult(
            urgency=final_urgency,
            urgency_rationale=urgency_rationale,
            advisory_disclaimer=ai_urgency.advisory_disclaimer,
        )
        case = CaseDocument(
            id="mock-agent-analysis",
            createdDate=self._CREATED_UTC.date().isoformat(),
            createdUtc=self._CREATED_UTC,
            lastStatusUpdatedUtc=self._CREATED_UTC,
            caseType="text-intake",
            sourceSystem="mock-agent",
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
            intakeComplete=not extraction.missing_fields,
            processingStatus="Completed",
            intakeStatus=(
                "NeedsFollowUp" if extraction.missing_fields else "Complete"
            ),
            reviewStatus="PendingReview",
        )

        return NurseIntakeAgentResult(
            extraction=extraction,
            urgency=urgency,
            handoffNote=self.handoff_formatter.format(case),
            metadata=NurseIntakeAgentMetadata(
                provider="mock",
                agentMode="mock",
            ),
        )


class FoundryNurseIntakeAgent:
    """Lazy Foundry Agent adapter for configured non-mock agent mode."""

    def __init__(
        self,
        settings: Any,
        client: Any | None = None,
        client_factory: Any = create_foundry_agent_client,
        handoff_formatter: NurseHandoffNoteFormatter | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.client_factory = client_factory
        self.handoff_formatter = handoff_formatter or NurseHandoffNoteFormatter()

    async def analyze_intake(self, raw_text: str) -> NurseIntakeAgentResult:
        client = self._get_client()
        response = await client.invoke_agent(
            FoundryAgentRequest(
                intake_text=raw_text,
                instructions=build_foundry_agent_intake_instructions(),
            )
        )
        structured_result = normalize_foundry_agent_intake_response(
            response.content
        )
        case = self._build_handoff_case(
            raw_text,
            structured_result.extraction,
            structured_result.urgency,
        )
        provider = self._provider()
        return NurseIntakeAgentResult(
            extraction=structured_result.extraction,
            urgency=structured_result.urgency,
            handoffNote=self.handoff_formatter.format(case),
            metadata=NurseIntakeAgentMetadata(
                provider=provider,
                agentMode="foundry-agent",
            ),
        )

    def _get_client(self) -> Any:
        if self.client is None:
            self.client = self.client_factory(self.settings, enable_live=True)
        return self.client

    def _provider(self) -> Literal["foundry", "foundry-agent"]:
        provider = getattr(self.settings, "agent_provider_normalized", "foundry")
        return "foundry" if provider == "foundry" else "foundry-agent"

    @staticmethod
    def _build_handoff_case(
        raw_text: str,
        extraction: ExtractionSummaryResult,
        urgency: UrgencyClassificationResult,
    ) -> CaseDocument:
        created_utc = datetime.now(timezone.utc)
        return CaseDocument(
            createdDate=created_utc.date().isoformat(),
            createdUtc=created_utc,
            lastStatusUpdatedUtc=created_utc,
            caseType="text-intake",
            sourceSystem="foundry-agent",
            patient=extraction.patient,
            reasonForCalling=extraction.reason_for_calling,
            symptoms=extraction.symptoms,
            transcript=raw_text,
            summary=extraction.summary,
            urgency=urgency.urgency,
            urgencySource="AI",
            ruleUrgency="Unknown",
            aiUrgency=urgency.urgency,
            urgencyRationale=urgency.urgency_rationale,
            missingFields=extraction.missing_fields,
            uncertainFields=extraction.uncertain_fields,
            intakeComplete=not extraction.missing_fields,
            processingStatus="Completed",
            intakeStatus=(
                "NeedsFollowUp" if extraction.missing_fields else "Complete"
            ),
            reviewStatus="PendingReview",
        )
