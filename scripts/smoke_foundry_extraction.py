import argparse
import asyncio
import sys
from pathlib import Path
from typing import TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.ai_service_factory import create_ai_service
from src.app.services.foundry_live_client import foundry_live_sdk_available


FICTIONAL_INTAKE_TEXT = (
    "My name is Demo Patient. DOB: 1980-04-15. "
    "My callback number is demo-callback-001. I need a medication refill."
)


async def _run_foundry_smoke(ai_service: object, intake_text: str):
    extraction = await ai_service.extract_and_summarize(intake_text)
    urgency = await ai_service.classify_urgency(intake_text)
    return extraction, urgency


def main(argv: list[str] | None = None) -> int:
    """Run an opt-in manual Foundry structured extraction smoke test."""

    args = _parse_args(argv)
    settings = AppSettings()

    configuration_exit_code = _validate_foundry_configuration(settings)
    if configuration_exit_code != 0:
        return configuration_exit_code

    if args.check:
        if not foundry_live_sdk_available():
            _print_configuration_error(
                "Optional Foundry SDK support is unavailable."
            )
            return 2

        print(
            "Foundry smoke-test preflight passed. Configuration is present and "
            "optional SDK imports are available. No model call was made."
        )
        print("Restore AI_PROVIDER=mock after any manual smoke test.")
        return 0

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


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an opt-in manual Azure AI Foundry structured extraction "
            "smoke test using fictional data only."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate local Foundry configuration and optional SDK availability "
            "without creating the AI service or making a model call."
        ),
    )
    return parser.parse_args(argv)


def _validate_foundry_configuration(settings: AppSettings) -> int:
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
