import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TextIO
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.foundry_ai_service import FoundryAiService
from src.app.services.foundry_extraction_contract import FoundryExtractionContractError
from src.app.services.ai_service_factory import create_ai_service
from src.app.services.foundry_live_client import (
    AZURE_OPENAI_AUTH_MODE,
    AZURE_OPENAI_LIVE_CLIENT_MODE,
    AZURE_OPENAI_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE,
    AZURE_OPENAI_TOKEN_PROVIDER_UNAVAILABLE_MESSAGE,
    AZURE_OPENAI_TOKEN_SCOPE_CATEGORY,
    FOUNDRY_LIVE_CLIENT_MODE,
    FOUNDRY_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE,
    azure_openai_live_sdk_available,
    create_azure_openai_live_client,
    foundry_live_sdk_available,
)


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
        "Foundry authentication failed. Run `az login`, verify the Foundry "
        "project endpoint, verify the model deployment name, and confirm the "
        "signed-in identity has access to the Azure AI Foundry project."
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
    "rate limited": (
        "Wait and retry the manual smoke test later, or check quota and "
        "capacity for the configured Foundry deployment."
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
    sdk_available = _live_sdk_available(args.live_client_mode) if args.live else None
    if args.diagnose:
        _print_diagnostic_configuration(settings, sdk_available, args.live_client_mode)

    configuration_exit_code = _validate_foundry_configuration(
        settings,
        args.live_client_mode,
        live=args.live,
    )
    if configuration_exit_code != 0:
        if args.diagnose:
            _print_diagnostic_failure("config validation")
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

    compatibility = _get_endpoint_client_compatibility(
        settings,
        args.live_client_mode,
    )
    if compatibility != "compatible":
        _print_endpoint_client_configuration_error(
            compatibility,
            args.live_client_mode,
        )
        if args.diagnose:
            _print_diagnostic_failure("config validation")
        return 2

    if not sdk_available:
        _print_configuration_error(
            "Optional Foundry SDK support is unavailable for --live smoke mode."
        )
        if args.diagnose:
            _print_diagnostic_failure("sdk import")
        return 2

    if args.diagnose:
        token_probe_status = _probe_azure_token_availability()
        print(f"Diagnostic token probe: {token_probe_status}", file=sys.stderr)

    try:
        failure_phase = "client construction"
        ai_service = _create_live_smoke_ai_service(settings, args.live_client_mode)
        print(
            "Running manual Azure AI Foundry smoke test with fictional demo "
            "input only. This command is not part of automated pytest."
        )
        failure_phase = "request execution"
        extraction, urgency = asyncio.run(
            _run_foundry_smoke(ai_service, FICTIONAL_INTAKE_TEXT)
        )
    except Exception as exc:
        failure_category = classify_live_smoke_failure(exc)
        _print_safe_live_failure_summary(failure_category)
        print(f"Safe failure category: {failure_category}", file=sys.stderr)
        print(
            f"Next check: {SAFE_FAILURE_HINTS[failure_category]}",
            file=sys.stderr,
        )
        if args.diagnose:
            _print_diagnostic_failure(
                _diagnostic_failure_phase(failure_phase, failure_category, exc),
                exc,
                failure_category,
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
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help=(
            "Print sanitized manual-only diagnostics for --live failures. "
            "No endpoints, deployments, prompts, tokens, raw exceptions, or "
            "tracebacks are printed."
        ),
    )
    parser.add_argument(
        "--live-client-mode",
        choices=[FOUNDRY_LIVE_CLIENT_MODE, AZURE_OPENAI_LIVE_CLIENT_MODE],
        default=FOUNDRY_LIVE_CLIENT_MODE,
        help=(
            "Select the manual live smoke client path. The default preserves "
            "the Foundry project endpoint path."
        ),
    )
    args = parser.parse_args(argv)
    if args.diagnose and not args.live:
        parser.error("--diagnose is only supported with --live")
    return args


def _validate_foundry_configuration(
    settings: AppSettings,
    live_client_mode: str = FOUNDRY_LIVE_CLIENT_MODE,
    live: bool = False,
) -> int:
    if settings.ai_provider_normalized != "foundry":
        _print_configuration_error(
            "Foundry smoke test requires AI_PROVIDER=foundry."
        )
        return 2

    if (
        live_client_mode == AZURE_OPENAI_LIVE_CLIENT_MODE
        and live
        and settings.azure_openai_endpoint is None
    ):
        _print_configuration_error(
            "Azure OpenAI endpoint smoke mode requires AZURE_OPENAI_ENDPOINT."
        )
        return 2

    if (
        live_client_mode == FOUNDRY_LIVE_CLIENT_MODE or not live
    ) and settings.azure_ai_foundry_project_endpoint is None:
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


def _create_live_smoke_ai_service(
    settings: AppSettings,
    live_client_mode: str,
) -> object:
    if live_client_mode == AZURE_OPENAI_LIVE_CLIENT_MODE:
        return FoundryAiService(
            project_endpoint=_required_setting(
                settings.azure_openai_endpoint,
                "AZURE_OPENAI_ENDPOINT",
            ),
            model_deployment_name=_required_setting(
                settings.azure_ai_foundry_model_deployment_name,
                "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
            ),
            client_factory=create_azure_openai_live_client,
        )

    return create_ai_service(settings)


def _required_setting(value: str | None, name: str) -> str:
    if value is None:
        raise ValueError(f"{name} is required for manual Foundry smoke mode")
    return value


def _print_configuration_error(message: str) -> None:
    print(message, file=sys.stderr)
    print(
        "This manual script is opt-in and does not run in the automated test "
        "suite. Restore AI_PROVIDER=mock after any manual smoke test.",
        file=sys.stderr,
    )


def _print_endpoint_client_configuration_error(
    compatibility: str,
    live_client_mode: str,
) -> None:
    endpoint_name = _required_endpoint_name(live_client_mode)
    expected_shape = _expected_endpoint_shape(live_client_mode)
    if compatibility == "incompatible":
        print(
            "Foundry smoke test endpoint/client configuration is incompatible "
            "with the selected live adapter.",
            file=sys.stderr,
        )
    else:
        print(
            "Foundry smoke test endpoint/client configuration could not be "
            "confirmed for the selected live adapter.",
            file=sys.stderr,
        )
    print(
        f"The selected live adapter mode is {live_client_mode} and expects "
        f"{endpoint_name} to have endpoint shape ({expected_shape}). "
        "No Azure call was made.",
        file=sys.stderr,
    )
    print(
        "No endpoint value, deployment name, token, credential, raw exception, "
        "or traceback was printed.",
        file=sys.stderr,
    )


def _print_safe_live_failure_summary(failure_category: str) -> None:
    if failure_category == "authentication failed":
        print(
            "Foundry authentication failed. No endpoint, deployment, prompt, "
            "token, credential, traceback, or raw exception details were "
            "printed.",
            file=sys.stderr,
        )
        return

    print(
        "Foundry smoke test failed. Review local configuration and provider "
        "setup; no endpoint, deployment, prompt, token, or exception details "
        "were printed.",
        file=sys.stderr,
    )


def _print_diagnostic_configuration(
    settings: AppSettings,
    sdk_available: bool | None,
    live_client_mode: str,
) -> None:
    print("Foundry live diagnostic mode enabled.", file=sys.stderr)
    print(
        f"Diagnostic live client mode: {live_client_mode}",
        file=sys.stderr,
    )
    print("Diagnostic config AI_PROVIDER present: yes", file=sys.stderr)
    print(
        "Diagnostic config AZURE_AI_FOUNDRY_PROJECT_ENDPOINT present: "
        f"{_yes_no(settings.azure_ai_foundry_project_endpoint)}",
        file=sys.stderr,
    )
    print(
        "Diagnostic config AZURE_OPENAI_ENDPOINT present: "
        f"{_yes_no(settings.azure_openai_endpoint)}",
        file=sys.stderr,
    )
    print(
        "Diagnostic endpoint shape: "
        f"{_get_configured_endpoint_shape(settings, live_client_mode)}",
        file=sys.stderr,
    )
    print(
        "Diagnostic configured endpoint shape: "
        f"{_get_configured_endpoint_shape(settings, live_client_mode)}",
        file=sys.stderr,
    )
    print(
        "Diagnostic required endpoint present: "
        f"{_yes_no(_get_configured_endpoint(settings, live_client_mode))}",
        file=sys.stderr,
    )
    print(
        "Diagnostic endpoint/client compatibility: "
        f"{_get_endpoint_client_compatibility(settings, live_client_mode)}",
        file=sys.stderr,
    )
    print(
        "Diagnostic deployment name present: "
        f"{_yes_no(settings.azure_ai_foundry_model_deployment_name)}",
        file=sys.stderr,
    )
    print(
        "Diagnostic SDK imports available: "
        f"{_yes_no(sdk_available)}",
        file=sys.stderr,
    )
    if live_client_mode == AZURE_OPENAI_LIVE_CLIENT_MODE:
        print(
            f"Diagnostic Azure OpenAI auth mode: {AZURE_OPENAI_AUTH_MODE}",
            file=sys.stderr,
        )
        print(
            "Diagnostic token scope category: "
            f"{AZURE_OPENAI_TOKEN_SCOPE_CATEGORY}",
            file=sys.stderr,
        )


def _print_diagnostic_failure(
    phase: str,
    error: BaseException | None = None,
    failure_category: str | None = None,
) -> None:
    print(f"Diagnostic failure phase: {phase}", file=sys.stderr)
    if error is not None:
        print(
            "Diagnostic exception class: "
            f"{error.__class__.__name__}",
            file=sys.stderr,
        )
        print(
            "Diagnostic root exception class: "
            f"{get_safe_root_exception_class(error)}",
            file=sys.stderr,
        )
        print(
            "Diagnostic exception chain classes: "
            f"{' -> '.join(get_safe_exception_chain_classes(error))}",
            file=sys.stderr,
        )
        print(
            "Diagnostic HTTP status category: "
            f"{get_safe_status_category(error)}",
            file=sys.stderr,
        )
    if failure_category is not None:
        print(
            f"Diagnostic safe failure category: {failure_category}",
            file=sys.stderr,
        )


def _diagnostic_failure_phase(
    current_phase: str,
    failure_category: str,
    error: BaseException | None = None,
) -> str:
    if error is not None and _is_token_provider_setup_failure(error):
        return "credential/token provider setup"
    if failure_category == "model response parsing failed":
        return "response parsing"
    if failure_category in {
        "authentication failed",
        "authorization/RBAC failed",
        "deployment or model not found",
        "endpoint rejected request",
        "Azure credential unavailable",
        "rate limited",
    }:
        return "request execution"
    if failure_category == "client construction failed":
        return "client construction"
    return current_phase or "unknown"


def _probe_azure_token_availability() -> str:
    try:
        from azure.identity import AzureCliCredential
    except Exception:
        return "unavailable"

    try:
        AzureCliCredential().get_token("https://cognitiveservices.azure.com/.default")
    except Exception:
        return "unavailable"

    return "available"


def _live_sdk_available(live_client_mode: str) -> bool:
    if live_client_mode == AZURE_OPENAI_LIVE_CLIENT_MODE:
        return azure_openai_live_sdk_available()
    return foundry_live_sdk_available()


def _classify_endpoint_shape(endpoint: str | None) -> str:
    if endpoint is None:
        return "unknown"

    host = urlparse(endpoint).netloc.casefold()
    if "services.ai.azure.com" in host:
        return "services.ai.azure.com"
    if "openai.azure.com" in host:
        return "openai.azure.com"
    return "unknown"


def _get_endpoint_client_compatibility(
    settings: AppSettings,
    live_client_mode: str = FOUNDRY_LIVE_CLIENT_MODE,
) -> str:
    endpoint_shape = _get_configured_endpoint_shape(settings, live_client_mode)
    expected_shape = _expected_endpoint_shape(live_client_mode)
    if endpoint_shape == expected_shape:
        return "compatible"
    if endpoint_shape in {
        FOUNDRY_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE,
        AZURE_OPENAI_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE,
    }:
        return "incompatible"
    return "unknown"


def _get_configured_endpoint_shape(
    settings: AppSettings,
    live_client_mode: str,
) -> str:
    return _classify_endpoint_shape(
        _get_configured_endpoint(settings, live_client_mode)
    )


def _get_configured_endpoint(
    settings: AppSettings,
    live_client_mode: str,
) -> str | None:
    if live_client_mode == AZURE_OPENAI_LIVE_CLIENT_MODE:
        return settings.azure_openai_endpoint
    return settings.azure_ai_foundry_project_endpoint


def _expected_endpoint_shape(live_client_mode: str) -> str:
    if live_client_mode == AZURE_OPENAI_LIVE_CLIENT_MODE:
        return AZURE_OPENAI_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE
    return FOUNDRY_LIVE_CLIENT_SUPPORTED_ENDPOINT_SHAPE


def _required_endpoint_name(live_client_mode: str) -> str:
    if live_client_mode == AZURE_OPENAI_LIVE_CLIENT_MODE:
        return "AZURE_OPENAI_ENDPOINT"
    return "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"


def _yes_no(value: object) -> str:
    return "yes" if bool(value) else "no"


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
    if status_code == 429:
        return "rate limited"

    chain_class_text = " ".join(get_safe_exception_chain_classes(error)).casefold()
    if "credentialunavailable" in chain_class_text:
        return "Azure credential unavailable"
    if "clientauthentication" in chain_class_text:
        return "authentication failed"
    if "authentication" in chain_class_text:
        return "authentication failed"
    if "authorization" in chain_class_text or "forbidden" in chain_class_text:
        return "authorization/RBAC failed"
    if "notfound" in chain_class_text or "resourcegone" in chain_class_text:
        return "deployment or model not found"
    if "badrequest" in chain_class_text:
        return "endpoint rejected request"
    if "ratelimit" in chain_class_text or "toomanyrequests" in chain_class_text:
        return "rate limited"
    if "tokenprovider" in chain_class_text:
        return "Azure credential unavailable"

    combined_text = " ".join(
        f"{candidate.__class__.__name__} {candidate}"
        for candidate in _walk_exception_chain(error)
    ).casefold()

    if "token provider setup failed" in combined_text:
        return "Azure credential unavailable"
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
    if "rate limit" in combined_text or "too many requests" in combined_text:
        return "rate limited"
    if "json" in combined_text or "schema" in combined_text or "parse" in combined_text:
        return "model response parsing failed"
    if "client creation" in combined_text or "live client is not configured" in combined_text:
        return "client construction failed"
    if "sdk support is not available" in combined_text:
        return "client construction failed"

    return "unknown live smoke failure"


def _is_token_provider_setup_failure(error: BaseException) -> bool:
    for candidate in _walk_exception_chain(error):
        if str(candidate) == AZURE_OPENAI_TOKEN_PROVIDER_UNAVAILABLE_MESSAGE:
            return True
        if "tokenprovider" in candidate.__class__.__name__.casefold():
            return True
    return False


def get_safe_exception_chain_classes(
    error: BaseException,
    max_depth: int = 5,
) -> list[str]:
    """Return bounded exception class names without messages or args."""

    return [
        candidate.__class__.__name__
        for candidate in _walk_exception_chain(error, max_depth)
    ]


def get_safe_root_exception_class(error: BaseException, max_depth: int = 5) -> str:
    """Return the deepest observed exception class name without raw details."""

    chain_classes = get_safe_exception_chain_classes(error, max_depth)
    return chain_classes[-1] if chain_classes else "unknown"


def get_safe_status_category(error: BaseException) -> str:
    status_code = _find_status_code(error)
    if status_code in {401, 403, 404, 429}:
        return str(status_code)
    if status_code is not None and 500 <= status_code <= 599:
        return "5xx"
    return "unknown"


def _walk_exception_chain(
    error: BaseException,
    max_depth: int = 5,
) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and current not in chain and len(chain) < max_depth:
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
