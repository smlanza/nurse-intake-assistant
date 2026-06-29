import asyncio
import sys
from pathlib import Path
from typing import TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.ai_service_factory import create_ai_service


FICTIONAL_INTAKE_TEXT = (
    "My name is Demo Patient. DOB: 1980-04-15. "
    "My callback number is demo-callback-001. I need a medication refill."
)


async def _run_foundry_smoke(ai_service: object, intake_text: str):
    extraction = await ai_service.extract_and_summarize(intake_text)
    urgency = await ai_service.classify_urgency(intake_text)
    return extraction, urgency


def main() -> int:
    """Run an opt-in manual Foundry structured extraction smoke test."""

    settings = AppSettings()

    if settings.ai_provider_normalized != "foundry":
        _print_configuration_error(
            "Foundry smoke test requires AI_PROVIDER=foundry."
        )
        return 2

    if settings.azure_ai_foundry_project_endpoint is None:
        _print_configuration_error(
            "Foundry smoke test requires AZURE_AI_FOUNDRY_PROJECT_ENDPOINT."
        )
        return 2

    if settings.azure_ai_foundry_model_deployment_name is None:
        _print_configuration_error(
            "Foundry smoke test requires AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME."
        )
        return 2

    try:
        ai_service = create_ai_service(settings)
        extraction, urgency = asyncio.run(
            _run_foundry_smoke(ai_service, FICTIONAL_INTAKE_TEXT)
        )
    except Exception:
        print(
            "Foundry smoke test failed. Review local configuration and provider "
            "setup; no endpoint, deployment, prompt, or exception details were "
            "printed.",
            file=sys.stderr,
        )
        return 1

    _print_safe_result(extraction, urgency, sys.stdout)
    return 0


def _print_configuration_error(message: str) -> None:
    print(message, file=sys.stderr)
    print(
        "This manual script is opt-in and does not run in the automated test "
        "suite. Restore AI_PROVIDER=mock after any manual smoke test.",
        file=sys.stderr,
    )


def _print_safe_result(
    extraction: object,
    urgency: object,
    output: TextIO,
) -> None:
    patient = extraction.patient
    print("Foundry structured extraction smoke test completed.", file=output)
    print("Input: fictional medication refill intake only.", file=output)
    print(f"Patient name: {patient.name}", file=output)
    print(f"Reason: {extraction.reason_for_calling}", file=output)
    print(f"Symptoms: {_format_list(extraction.symptoms)}", file=output)
    print(f"Summary: {extraction.summary}", file=output)
    print(f"Missing fields: {_format_list(extraction.missing_fields)}", file=output)
    print(f"Urgency: {urgency.urgency}", file=output)
    print(f"Urgency rationale: {urgency.urgency_rationale}", file=output)
    print(f"Advisory disclaimer: {urgency.advisory_disclaimer}", file=output)


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


if __name__ == "__main__":
    raise SystemExit(main())
