import inspect
from typing import Any

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    UrgencyClassificationResult,
)
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
    build_foundry_structured_extraction_prompt,
    parse_foundry_structured_extraction_response,
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
        self._structured_result_cache: dict[
            str,
            tuple[ExtractionSummaryResult, UrgencyClassificationResult],
        ] = {}

    def build_structured_extraction_prompt(self, raw_text: str) -> str:
        """Return offline prompt instructions for future live Foundry calls."""

        return build_foundry_structured_extraction_prompt(raw_text)

    def parse_structured_extraction_response(
        self,
        model_response: str,
    ) -> tuple[ExtractionSummaryResult, UrgencyClassificationResult]:
        """Parse future live Foundry JSON into current app output models."""

        return parse_foundry_structured_extraction_response(model_response)

    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        extraction, urgency = await self._get_structured_result(raw_text)
        self._structured_result_cache[raw_text] = (extraction, urgency)
        return extraction

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        cached_result = self._structured_result_cache.get(raw_text)
        if cached_result is not None:
            return cached_result[1]

        extraction, urgency = await self._get_structured_result(raw_text)
        self._structured_result_cache[raw_text] = (extraction, urgency)
        return urgency

    async def _get_structured_result(
        self,
        raw_text: str,
    ) -> tuple[ExtractionSummaryResult, UrgencyClassificationResult]:
        prompt = self.build_structured_extraction_prompt(raw_text)

        try:
            model_response = await self._call_client(
                "complete_structured_extraction",
                prompt,
            )
        except FoundryAiClientNotImplementedError:
            raise
        except FoundryExtractionContractError:
            raise
        except Exception as exc:
            raise RuntimeError("Azure AI Foundry structured extraction failed") from exc

        if not isinstance(model_response, str):
            raise FoundryExtractionContractError(
                "Azure AI Foundry structured extraction response must be text."
            )

        return self.parse_structured_extraction_response(model_response)

    async def _call_client(self, method_name: str, prompt: str) -> Any:
        client = self._get_client()
        method = getattr(client, method_name)
        result = method(
            prompt=prompt,
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
