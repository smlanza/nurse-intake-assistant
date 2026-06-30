import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.foundry_extraction_contract import FoundryExtractionContractError
from src.app.services.ai_service_factory import create_ai_service
from src.app.services.foundry_live_client import foundry_live_sdk_available


SAFE_FAILURE_HINTS = {
    "client construction failed": (
        "Check that optional Foundry SDK packages are installed and the "
        "project endpoint is the expected Foundry endpoint type."
    ),
    "Azure credential unavailable": (
        "Check Azure login or local credential setup for the manual smoke "
        "environment."
    ),
    "authentication failed": (
        "Check Azure login state and whether the credential can get a token."
    ),
    "authorization/RBAC failed": (
        "Check project-level RBAC for the signed-in identity."
    ),
    "deployment or model not found": (
        "Check the configured model deployment name and project endpoint."
    ),
    "endpoint rejected request": (
        "Check endpoint type, SDK compatibility, and request support for the "
        "deployed model."
    ),
    "model response parsing failed": (
        "Check whether the model response still matches the structured JSON "
        "contract."
    ),
    "unknown live smoke failure": (
        "Check local Foundry settings, SDK compatibility, Azure login/RBAC, "
        "and the deployment name."
    ),
}

FICTIONAL_INTAKE_TEXT = (
    "Demo patient Alex Morgan requests a callback about a routine medication "
    "refill. Callback number is demo-callback-001. No chest pain, shortness "
    "of breath, or severe symptoms reported."
)


async def _run_foundry_smoke(ai_service: object, intake_text: str):
    extraction = await ai_service.extract_and_summarize(intake_text)
    urgency = await ai_service.classify_urgency(intake_text)
    return extraction, urgency


def main(argv: list[str] | None = None) -> int:
    """Run an opt-in manual Foundry structured extraction smoke test."""

    args = _parse_args(argv)

    if args.env_file is not None:
        env_file_exit_code = _load_env_file(args.env_file)
        if env_file_exit_code != 0:
            return env_file_exit_code
        print(f"Loaded environment file: {args.env_file}")

    settings = AppSettings()

    configuration_exit_code = _validate_foundry_configuration(settings)
    if configuration_exit_code != 0:
        return configuration_exit_code

    if args.check:
        sdk_message = (
            "Optional Foundry SDK imports appear available."
            if foundry_live_sdk_available()
            else "Optional Foundry SDK imports are unavailable."
        )
        print(
            "Foundry smoke-test preflight passed. Configuration is present. "
            f"{sdk_message} No AI service was created. No model call was made."
        )
        print("Restore AI_PROVIDER=mock after any manual smoke test.")
        return 0

    if not foundry_live_sdk_available():
        _print_configuration_error(
            "Optional Foundry SDK support is unavailable for --live smoke mode."
        )
        return 2

    try:
        ai_service = create_ai_service(settings)
        print(
            "Running manual Azure AI Foundry smoke test with fictional demo "
            "input only. This command is not part of automated pytest."
        )
        extraction, urgency = asyncio.run(
            _run_foundry_smoke(ai_service, FICTIONAL_INTAKE_TEXT)
        )
    except Exception as exc:
        failure_category = classify_live_smoke_failure(exc)
        print(
            "Foundry smoke test failed. Review local configuration and provider "
            "setup; no endpoint, deployment, prompt, token, or exception "
            "details were printed.",
            file=sys.stderr,
        )
        print(f"Safe failure category: {failure_category}", file=sys.stderr)
        print(
            f"Next check: {SAFE_FAILURE_HINTS[failure_category]}",
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
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate local Foundry configuration and optional SDK visibility "
            "without creating the AI service or making a model call."
        ),
    )
    mode.add_argument(
        "--live",
        action="store_true",
        help=(
            "Run the explicit manual live smoke test using fictional input. "
            "This may create a Foundry client and call Azure."
        ),
    )
    parser.add_argument(
        "--env-file",
        help=(
            "Load Foundry smoke-test settings from a KEY=value file for this "
            "script process only. Existing shell environment variables win."
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


def _load_env_file(env_file: str) -> int:
    path = Path(env_file)
    if not path.exists():
        print(
            f"Foundry smoke env file not found: {env_file}",
            file=sys.stderr,
        )
        print(
            "Create a local .env.foundry.local file from the example, or pass "
            "the correct --env-file path. No Azure call was made.",
            file=sys.stderr,
        )
        return 2

    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        if "=" not in line:
            print(
                f"Invalid Foundry smoke env file line {line_number}: expected KEY=value.",
                file=sys.stderr,
            )
            print(
                "No environment values were printed. No Azure call was made.",
                file=sys.stderr,
            )
            return 2

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            print(
                f"Invalid Foundry smoke env file line {line_number}: missing key.",
                file=sys.stderr,
            )
            print(
                "No environment values were printed. No Azure call was made.",
                file=sys.stderr,
            )
            return 2

        if key not in os.environ:
            os.environ[key] = _strip_optional_quotes(value.strip())

    return 0


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def classify_live_smoke_failure(error: BaseException) -> str:
    """Map live smoke exceptions to safe, non-secret diagnostic categories."""

    for candidate in _walk_exception_chain(error):
        if isinstance(candidate, FoundryExtractionContractError):
            return "model response parsing failed"

    status_code = _find_status_code(error)
    if status_code == 401:
        return "authentication failed"
    if status_code == 403:
        return "authorization/RBAC failed"
    if status_code == 404:
        return "deployment or model not found"
    if status_code == 400:
        return "endpoint rejected request"

    combined_text = " ".join(
        f"{candidate.__class__.__name__} {candidate}"
        for candidate in _walk_exception_chain(error)
    ).casefold()

    if "credentialunavailable" in combined_text or "credential unavailable" in combined_text:
        return "Azure credential unavailable"
    if "defaultazurecredential" in combined_text and "failed" in combined_text:
        return "Azure credential unavailable"
    if "authentication" in combined_text or "unauthorized" in combined_text:
        return "authentication failed"
    if "authorization" in combined_text or "forbidden" in combined_text or "rbac" in combined_text:
        return "authorization/RBAC failed"
    if "deployment" in combined_text and "not found" in combined_text:
        return "deployment or model not found"
    if "model" in combined_text and "not found" in combined_text:
        return "deployment or model not found"
    if "bad request" in combined_text or "invalid request" in combined_text:
        return "endpoint rejected request"
    if "json" in combined_text or "schema" in combined_text or "parse" in combined_text:
        return "model response parsing failed"
    if "client creation" in combined_text or "live client is not configured" in combined_text:
        return "client construction failed"
    if "sdk support is not available" in combined_text:
        return "client construction failed"

    return "unknown live smoke failure"


def _walk_exception_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _find_status_code(error: BaseException) -> int | None:
    for candidate in _walk_exception_chain(error):
        status_code = _extract_status_code(candidate)
        if status_code is not None:
            return status_code
    return None


def _extract_status_code(error: BaseException) -> int | None:
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        return status_code

    response = getattr(error, "response", None)
    response_status_code = getattr(response, "status_code", None)
    if isinstance(response_status_code, int):
        return response_status_code

    return None


def _print_safe_result(
    extraction: object,
    urgency: object,
    output: TextIO,
) -> None:
    patient = extraction.patient
    print("Foundry structured extraction smoke test completed.", file=output)
    print(
        "Input: fictional routine medication refill callback request only.",
        file=output,
    )
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
