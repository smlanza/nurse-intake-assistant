import inspect
from typing import Any

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)


class FoundryAiClientNotImplementedError(RuntimeError):
    """Signal that live Foundry client creation is intentionally absent."""


class FoundryAiService:
    """Scaffold future Azure AI Foundry extraction through injected clients."""

    def __init__(
        self,
        project_endpoint: str,
        model_deployment_name: str,
        client: Any | None = None,
        client_factory: Any | None = None,
    ) -> None:
        self.project_endpoint = project_endpoint
        self.model_deployment_name = model_deployment_name
        self.client = client
        self.client_factory = client_factory

    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        try:
            payload = await self._call_client("extract_and_summarize", raw_text)
        except FoundryAiClientNotImplementedError:
            raise
        except Exception as exc:
            raise RuntimeError("Azure AI Foundry extraction failed") from exc

        return ExtractionSummaryResult(
            patient=PatientInfo(**payload.get("patient", {})),
            reason_for_calling=payload.get("reason_for_calling"),
            symptoms=payload.get("symptoms", []),
            summary=payload["summary"],
            missing_fields=payload.get("missing_fields", []),
            uncertain_fields=payload.get("uncertain_fields", []),
            extraction_notes=payload.get("extraction_notes"),
        )

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        try:
            payload = await self._call_client("classify_urgency", raw_text)
        except FoundryAiClientNotImplementedError:
            raise
        except Exception as exc:
            raise RuntimeError("Azure AI Foundry urgency classification failed") from exc

        return UrgencyClassificationResult(
            urgency=payload["urgency"],
            urgency_rationale=payload["urgency_rationale"],
            advisory_disclaimer=payload["advisory_disclaimer"],
        )

    async def _call_client(self, method_name: str, raw_text: str) -> dict[str, Any]:
        client = self._get_client()
        method = getattr(client, method_name)
        result = method(
            raw_text=raw_text,
            model_deployment_name=self.model_deployment_name,
        )
        if inspect.isawaitable(result):
            result = await result
        return result

    def _get_client(self) -> Any:
        if self.client is not None:
            return self.client

        if self.client_factory is None:
            raise FoundryAiClientNotImplementedError(
                "Azure AI Foundry client creation is not implemented yet."
            )

        self.client = self.client_factory(self.project_endpoint)
        return self.client
