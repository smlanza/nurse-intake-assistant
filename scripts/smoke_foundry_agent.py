import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
from src.app.services.foundry_agent_client import (
    FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY,
    FOUNDRY_AGENT_NOT_WIRED_CATEGORY,
    FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
    FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
    FoundryAgentClientError,
    foundry_agent_sdk_available,
)
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
    FoundryExtractionParseError,
)
from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent
from src.app.services.nurse_intake_agent_contract import (
    validate_nurse_intake_agent_result,
)
from src.app.services.nurse_intake_agent_instructions import (
    NURSE_INTAKE_AGENT_INSTRUCTION_VERSION,
    build_nurse_intake_agent_expected_json_shape,
    build_nurse_intake_agent_fictional_test_input,
    build_nurse_intake_agent_instructions,
)
from src.app.services.nurse_intake_agent_preflight import (
    FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND,
    build_nurse_intake_agent_status,
)


FICTIONAL_AGENT_INTAKE_TEXT = build_nurse_intake_agent_fictional_test_input()
FOUNDRY_AGENT_PROVIDER_VALUES = {"foundry", "foundry-agent"}
SAFE_FAILURE_HINTS = {
    "configuration": (
        "Check AGENT_PROVIDER, the Foundry Agent project endpoint setting, "
        "and the Foundry Agent ID setting."
    ),
    "credential": (
        "Check local Azure credential setup for this manual smoke environment."
    ),
    "authentication": (
        "Run az login and verify the signed-in identity can authenticate to "
        "the Foundry project."
    ),
    "authorization": (
        "Check project-level RBAC for the signed-in identity and agent resource."
    ),
    "not_found": (
        "Check that the configured Foundry Agent project and agent still exist."
    ),
    "bad_request": (
        "Check SDK compatibility and whether the agent accepts the requested "
        "manual smoke invocation shape."
    ),
    "sdk_missing": (
        "Install the optional Foundry Agent SDK packages in the local manual "
        "smoke environment."
    ),
    "parsing": (
        "Check whether the agent response still matches the structured JSON "
        "contract."
    ),
    "unknown": (
        "Check local Foundry Agent settings, SDK compatibility, Azure login, "
        "RBAC, and agent availability."
    ),
}
SAFE_RESULT_HINTS = {
    "missing_configuration": "Check required Foundry Agent environment settings.",
    "sdk_unavailable": "Install the optional Azure AI Foundry Agent SDK packages.",
    "authentication_or_authorization_failed": (
        "Check Azure login, tenant access, and project RBAC permissions."
    ),
    "azure_request_failed": (
        "Check local Foundry Agent settings, SDK compatibility, and agent availability."
    ),
    "contract_invalid": "Check that the agent response matches the expected contract.",
    "response_parse_failed": "Check that the agent returned valid structured JSON.",
    "unexpected_error": (
        "Check local settings and rerun with a clean manual smoke environment."
    ),
    "success": "No action needed for this manual smoke result.",
}
SAFE_RESULT_MESSAGES = {
    "success": "Live Foundry Agent smoke validation completed successfully.",
    "missing_configuration": "Required Foundry Agent configuration is missing.",
    "sdk_unavailable": "The optional Foundry Agent SDK is unavailable.",
    "authentication_or_authorization_failed": (
        "Azure authentication or authorization failed."
    ),
    "azure_request_failed": "The Azure Foundry Agent request failed.",
    "response_parse_failed": "The agent response could not be parsed as JSON.",
    "contract_invalid": (
        "The parsed agent response did not satisfy the Nurse Intake Agent contract."
    ),
    "unexpected_error": "The live smoke path failed unexpectedly.",
}
LIVE_RESULT_CATEGORY_BY_LEGACY_CATEGORY = {
    "configuration": "missing_configuration",
    "credential": "authentication_or_authorization_failed",
    "authentication": "authentication_or_authorization_failed",
    "authorization": "authentication_or_authorization_failed",
    "not_found": "azure_request_failed",
    "bad_request": "azure_request_failed",
    "sdk_missing": "sdk_unavailable",
    "parsing": "contract_invalid",
    "unknown": "unexpected_error",
}
LIVE_JSON_CATEGORIES = frozenset(SAFE_RESULT_MESSAGES)
AGENT_PROVIDER_SETTING_NAME = "AGENT_PROVIDER"
FOUNDRY_AGENT_ENDPOINT_SETTING_NAME = "AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT"
FOUNDRY_PROJECT_ENDPOINT_SETTING_NAME = "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT"
FOUNDRY_AGENT_ID_SETTING_NAME = "AZURE_AI_FOUNDRY_AGENT_ID"


@dataclass(frozen=True)
class FoundryAgentSmokeResult:
    provider: str
    mode: str
    ok: bool
    category: Literal[
        "success",
        "missing_configuration",
        "sdk_unavailable",
        "authentication_or_authorization_failed",
        "azure_request_failed",
        "response_parse_failed",
        "contract_invalid",
        "unexpected_error",
    ]
    message: str
    agent_attempted: bool
    agent_output_valid: bool | None
    fallback_used: bool
    fields_present: list[str]
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "provider": self.provider,
            "category": self.category,
            "message": self.message,
            "agent_attempted": self.agent_attempted,
            "agent_output_valid": self.agent_output_valid,
            "fallback_used": self.fallback_used,
            "fields_present": self.fields_present,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class FoundryAgentEnvironmentReadiness:
    provider: str
    mode: Literal["check"]
    ready: bool
    required_settings_present: list[str]
    required_settings_missing: list[str]
    optional_settings_present: list[str]
    sdk_available: bool
    live_json_command_hint: str
    recommended_next_step: str


def main(argv: list[str] | None = None) -> int:
    """Run an opt-in manual Azure AI Foundry Agent smoke test."""

    args = _parse_args(argv)

    if args.print_agent_instructions:
        _print_agent_instruction_pack()
        return 0

    if not args.check and not args.live:
        print(
            "Foundry Agent smoke mode is explicit; rerun with --check, --live, "
            "or --print-agent-instructions.",
            file=sys.stderr,
        )
        print("No Foundry Agent client was created. No Azure call was made.", file=sys.stderr)
        return 2

    if args.env_file is not None:
        env_file_exit_code = _load_env_file(args.env_file)
        if env_file_exit_code != 0:
            return env_file_exit_code
        if not args.json:
            print("Loaded Foundry Agent smoke environment file.")

    settings = AppSettings()
    if args.live and args.json:
        result, exit_code = _run_live_json_smoke(settings)
        _print_json_result(result)
        return exit_code
    if args.live and args.diagnose:
        result, exit_code, error = _run_live_smoke(settings)
        _print_diagnostic_result(result, error)
        return exit_code

    if args.check:
        readiness = build_foundry_agent_environment_readiness(
            settings,
            sdk_available=foundry_agent_sdk_available(),
        )
        _print_check_readiness(readiness)
        return 0 if not readiness.required_settings_missing else 2

    configuration_exit_code = _validate_foundry_agent_configuration(settings)
    if configuration_exit_code != 0:
        return configuration_exit_code

    try:
        agent = create_nurse_intake_agent(settings)
        result = asyncio.run(agent.analyze_intake(FICTIONAL_AGENT_INTAKE_TEXT))
    except Exception as exc:
        failure_category = classify_live_agent_failure(exc)
        _print_safe_live_failure_summary(failure_category)
        print(f"Safe failure category: {failure_category}", file=sys.stderr)
        print(f"Next check: {SAFE_FAILURE_HINTS[failure_category]}", file=sys.stderr)
        return 1

    _print_safe_result(result)
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an explicit manual Azure AI Foundry Agent smoke test using "
            "fictional data only. This may call Azure when the configured "
            "agent provider is wired to a live agent."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate Foundry Agent configuration and optional SDK visibility "
            "without creating a Foundry Agent client or making an Azure call."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Run the explicit manual live smoke test using fictional input. "
            "This may create a Foundry Agent client and call Azure."
        ),
    )
    parser.add_argument(
        "--env-file",
        help=(
            "Load Foundry Agent smoke-test settings from a KEY=value file for "
            "this script process only. Existing shell environment variables win."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=(
            "Print a deterministic sanitized JSON result for --live manual "
            "validation."
        ),
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help=(
            "Print sanitized live troubleshooting metadata for --live without "
            "raw exception messages, stack traces, endpoints, agent IDs, or "
            "model output."
        ),
    )
    parser.add_argument(
        "--print-agent-instructions",
        action="store_true",
        help=(
            "Print versioned copyable Foundry Agent instructions without "
            "loading settings, creating clients, or calling Azure."
        ),
    )
    args = parser.parse_args(argv)
    if args.print_agent_instructions and (args.check or args.live):
        parser.error("--print-agent-instructions cannot be combined with --check or --live")
    if args.check and args.live:
        parser.error("--check and --live cannot be used together")
    if args.diagnose and not args.live:
        parser.error("--diagnose is only supported with --live")
    if args.json and args.diagnose:
        parser.error("--json and --diagnose cannot be used together")
    if args.json and not args.live:
        parser.error("--json is only supported with --live")
    return args


def _run_live_json_smoke(settings: AppSettings) -> tuple[FoundryAgentSmokeResult, int]:
    result, exit_code, _ = _run_live_smoke(settings)
    return result, exit_code


def _run_live_smoke(
    settings: AppSettings,
) -> tuple[FoundryAgentSmokeResult, int, BaseException | None]:
    sdk_available = foundry_agent_sdk_available()
    if not _foundry_agent_configured(settings):
        return (
            _failed_live_result(
                category="missing_configuration",
                agent_attempted=False,
                agent_output_valid=None,
            ),
            2,
            None,
        )

    if not sdk_available:
        return (
            _failed_live_result(
                category="sdk_unavailable",
                agent_attempted=False,
                agent_output_valid=None,
            ),
            1,
            None,
        )

    try:
        agent = create_nurse_intake_agent(settings)
    except Exception as exc:
        safe_category = _live_json_result_category(exc)
        return (
            _failed_live_result(
                category=safe_category,
                agent_attempted=False,
                agent_output_valid=None,
            ),
            1,
            exc,
        )

    try:
        agent_result = asyncio.run(agent.analyze_intake(FICTIONAL_AGENT_INTAKE_TEXT))
    except Exception as exc:
        safe_category = _live_json_result_category(exc)
        return (
            _failed_live_result(
                category=safe_category,
                agent_attempted=True,
                agent_output_valid=(
                    False
                    if safe_category in {"response_parse_failed", "contract_invalid"}
                    else None
                ),
            ),
            1,
            exc,
        )

    validation_result = validate_nurse_intake_agent_result(agent_result)
    fields_present = _agent_result_fields_present(agent_result)
    if not validation_result.is_valid:
        return (
            _failed_live_result(
                category="contract_invalid",
                agent_attempted=True,
                agent_output_valid=False,
                fields_present=fields_present,
            ),
            1,
            None,
        )

    return (
        FoundryAgentSmokeResult(
            mode="live",
            provider="foundry-agent",
            ok=True,
            category="success",
            message=SAFE_RESULT_MESSAGES["success"],
            agent_attempted=True,
            agent_output_valid=True,
            fallback_used=_result_fallback_used(agent_result),
            fields_present=fields_present,
            recommended_next_step=SAFE_RESULT_HINTS["success"],
        ),
        0,
        None,
    )


def _failed_live_result(
    *,
    category: str,
    agent_attempted: bool,
    agent_output_valid: bool | None,
    fields_present: list[str] | None = None,
) -> FoundryAgentSmokeResult:
    if category not in LIVE_JSON_CATEGORIES:
        category = "unexpected_error"
    return FoundryAgentSmokeResult(
        mode="live",
        provider="foundry-agent",
        ok=False,
        category=category,  # type: ignore[arg-type]
        message=SAFE_RESULT_MESSAGES[category],
        agent_attempted=agent_attempted,
        agent_output_valid=agent_output_valid,
        fallback_used=False,
        fields_present=fields_present or [],
        recommended_next_step=SAFE_RESULT_HINTS[category],
    )


def _print_json_result(result: FoundryAgentSmokeResult) -> None:
    print(json.dumps(result.to_json_dict(), separators=(",", ":")))


def _print_diagnostic_result(
    result: FoundryAgentSmokeResult,
    error: BaseException | None,
) -> None:
    print("Foundry Agent live diagnostic result")
    print("Provider: foundry-agent")
    print("Mode: live")
    print(f"Category: {result.category}")
    print(f"Agent attempted: {str(result.agent_attempted).lower()}")
    print(f"Agent output valid: {_format_optional_bool(result.agent_output_valid)}")
    print(f"Safe exception class: {_safe_exception_class_name(error)}")
    print(f"Safe status code: {_format_optional_status_code(_find_status_code(error))}")
    print(f"Recommended next step: {result.recommended_next_step}")
    print(
        "Sanitized diagnostic only: no endpoint, agent ID, token, prompt text, "
        "model response text, stack trace, request ID, email, phone, or PHI was printed."
    )


def _print_agent_instruction_pack() -> None:
    print("Foundry Agent Instruction Pack")
    print(f"Instruction version: {NURSE_INTAKE_AGENT_INSTRUCTION_VERSION}")
    print()
    print("Copyable agent instructions:")
    print(build_nurse_intake_agent_instructions())
    print()
    print("Expected JSON shape:")
    print(build_nurse_intake_agent_expected_json_shape())
    print()
    print("Fictional test input:")
    print(build_nurse_intake_agent_fictional_test_input())
    print()
    print("Manual validation commands:")
    print("python scripts/smoke_foundry_agent.py --env-file .env.foundry-agent.local --check")
    print(FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND)
    print()
    print("The local demo remains mock/offline by default.")
    print("Human nurse review remains mandatory before clinical action.")
    print("Restore AGENT_PROVIDER=mock after manual validation.")


def _foundry_agent_configured(settings: AppSettings) -> bool:
    if settings.agent_provider_normalized not in FOUNDRY_AGENT_PROVIDER_VALUES:
        return False
    return build_nurse_intake_agent_status(settings).ready


def build_foundry_agent_environment_readiness(
    settings: Any,
    *,
    sdk_available: bool,
) -> FoundryAgentEnvironmentReadiness:
    """Build a sanitized offline Foundry Agent live-smoke readiness summary."""

    provider = _safe_provider_name(
        getattr(settings, "agent_provider_normalized", "mock")
    )
    required_present: list[str] = []
    required_missing: list[str] = []
    optional_present: list[str] = []

    if provider in FOUNDRY_AGENT_PROVIDER_VALUES:
        required_present.append(AGENT_PROVIDER_SETTING_NAME)
    else:
        required_missing.append(AGENT_PROVIDER_SETTING_NAME)

    agent_endpoint_present = _has_setting(
        settings,
        "azure_ai_foundry_agent_project_endpoint",
    )
    fallback_endpoint_present = _has_setting(
        settings,
        "azure_ai_foundry_project_endpoint",
    )
    if agent_endpoint_present:
        required_present.append(FOUNDRY_AGENT_ENDPOINT_SETTING_NAME)
        if fallback_endpoint_present:
            optional_present.append(FOUNDRY_PROJECT_ENDPOINT_SETTING_NAME)
    elif fallback_endpoint_present:
        required_present.append(FOUNDRY_PROJECT_ENDPOINT_SETTING_NAME)
    else:
        required_missing.extend(
            [
                FOUNDRY_AGENT_ENDPOINT_SETTING_NAME,
                FOUNDRY_PROJECT_ENDPOINT_SETTING_NAME,
            ]
        )

    if _has_setting(settings, "azure_ai_foundry_agent_id"):
        required_present.append(FOUNDRY_AGENT_ID_SETTING_NAME)
    else:
        required_missing.append(FOUNDRY_AGENT_ID_SETTING_NAME)

    ready = not required_missing and sdk_available
    return FoundryAgentEnvironmentReadiness(
        provider=provider,
        mode="check",
        ready=ready,
        required_settings_present=required_present,
        required_settings_missing=required_missing,
        optional_settings_present=optional_present,
        sdk_available=sdk_available,
        live_json_command_hint=FOUNDRY_AGENT_MANUAL_VALIDATION_COMMAND,
        recommended_next_step=_check_recommended_next_step(
            required_missing,
            sdk_available,
        ),
    )


def _live_json_result_category(error: BaseException) -> str:
    if any(
        isinstance(candidate, FoundryExtractionParseError)
        for candidate in _walk_exception_chain(error)
    ):
        return "response_parse_failed"
    if any(
        isinstance(candidate, FoundryExtractionContractError)
        for candidate in _walk_exception_chain(error)
    ):
        return "contract_invalid"
    for candidate in _walk_exception_chain(error):
        if isinstance(candidate, FoundryAgentClientError):
            if candidate.category == FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY:
                return "sdk_unavailable"
            if candidate.category == FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY:
                return "missing_configuration"
            if candidate.category in {
                FOUNDRY_AGENT_REQUEST_FAILED_CATEGORY,
                FOUNDRY_AGENT_NOT_WIRED_CATEGORY,
            }:
                return "azure_request_failed"

    status_code = _find_status_code(error)
    if status_code in {401, 403}:
        return "authentication_or_authorization_failed"
    if status_code is not None:
        return "azure_request_failed"

    chain_class_text = " ".join(
        candidate.__class__.__name__ for candidate in _walk_exception_chain(error)
    ).casefold()
    if (
        "credential" in chain_class_text
        or "authentication" in chain_class_text
        or "authenticationrequired" in chain_class_text
        or "authorization" in chain_class_text
        or "forbidden" in chain_class_text
    ):
        return "authentication_or_authorization_failed"
    if (
        ("azure" in chain_class_text and "request" in chain_class_text)
        or "httpresponseerror" in chain_class_text
        or "resourcenotfound" in chain_class_text
        or "resourcemodified" in chain_class_text
        or "toomanyrequests" in chain_class_text
        or "servicerequest" in chain_class_text
        or "serviceresponse" in chain_class_text
        or "requestfailed" in chain_class_text
        or "httperror" in chain_class_text
    ):
        return "azure_request_failed"

    legacy_category = classify_live_agent_failure(error)
    return LIVE_RESULT_CATEGORY_BY_LEGACY_CATEGORY.get(
        legacy_category,
        "unexpected_error",
    )


def _agent_result_fields_present(agent_result: object) -> list[str]:
    fields = []
    for field_name in ("extraction", "urgency", "handoffNote"):
        if hasattr(agent_result, field_name):
            fields.append(field_name)
    return fields


def _result_fallback_used(agent_result: object) -> bool:
    metadata = getattr(agent_result, "metadata", None)
    fallback_used = getattr(metadata, "fallback_used", False)
    return bool(fallback_used)


def _safe_provider_name(value: object) -> str:
    provider = str(value or "mock").strip().lower() or "mock"
    if provider in {"mock", "foundry", "foundry-agent"}:
        return provider
    return "unsupported"


def _has_setting(settings: Any, attribute_name: str) -> bool:
    value = getattr(settings, attribute_name, None)
    return isinstance(value, str) and bool(value.strip())


def _check_recommended_next_step(
    missing_settings: list[str],
    sdk_available: bool,
) -> str:
    if missing_settings:
        return (
            "Add missing Foundry Agent setting name(s): "
            f"{', '.join(missing_settings)}."
        )
    if not sdk_available:
        return (
            "Install the optional Azure AI Foundry Agent SDK dependencies before "
            "manual live JSON validation."
        )
    return (
        "Run the manual live JSON validation command from a configured "
        "developer shell."
    )


def _validate_foundry_agent_configuration(settings: AppSettings) -> int:
    provider = settings.agent_provider_normalized
    if provider not in FOUNDRY_AGENT_PROVIDER_VALUES:
        _print_configuration_error(
            "Foundry Agent smoke test requires AGENT_PROVIDER=foundry-agent "
            "or AGENT_PROVIDER=foundry."
        )
        return 2

    agent_status = build_nurse_intake_agent_status(settings)
    if not agent_status.ready:
        _print_configuration_error(
            "Foundry Agent smoke test missing required setting(s): "
            f"{', '.join(agent_status.missingSettings)}."
        )
        return 2

    return 0


def _print_configuration_error(message: str) -> None:
    print(message, file=sys.stderr)
    print(
        "This manual script is opt-in and does not run in the automated test "
        "suite. It does not send email or SMS. Restore AGENT_PROVIDER=mock "
        "after any manual Foundry Agent smoke test.",
        file=sys.stderr,
    )


def _print_check_readiness(readiness: FoundryAgentEnvironmentReadiness) -> None:
    stream = sys.stdout if not readiness.required_settings_missing else sys.stderr
    if readiness.ready:
        print(
            "Foundry Agent smoke-test preflight passed. Required configuration "
            "and optional SDK visibility are present.",
            file=stream,
        )
    else:
        print("Foundry Agent smoke-test environment check needs attention.", file=stream)
    print("Mode: check", file=stream)
    print(f"Provider: {readiness.provider}", file=stream)
    print(
        "Required settings present: "
        f"{_format_setting_names(readiness.required_settings_present)}",
        file=stream,
    )
    print(
        "Required settings missing: "
        f"{_format_setting_names(readiness.required_settings_missing)}",
        file=stream,
    )
    print(
        "Optional settings present: "
        f"{_format_setting_names(readiness.optional_settings_present)}",
        file=stream,
    )
    sdk_message = (
        "Optional Foundry Agent SDK package appears importable."
        if readiness.sdk_available
        else "Optional Foundry Agent SDK package is not importable."
    )
    print(sdk_message, file=stream)
    print(
        "No Foundry Agent client was created. No Azure call was made.",
        file=stream,
    )
    print(
        f"Live JSON command hint: {readiness.live_json_command_hint}",
        file=stream,
    )
    print(f"Recommended next step: {readiness.recommended_next_step}", file=stream)
    print(
        "Restore AGENT_PROVIDER=mock after any manual Foundry Agent smoke test.",
        file=stream,
    )


def _format_setting_names(setting_names: list[str]) -> str:
    return ", ".join(setting_names) if setting_names else "none"


def _print_safe_live_failure_summary(failure_category: str) -> None:
    print(
        "Foundry Agent smoke test failed. Review local configuration and "
        "provider setup; no endpoint, agent ID, prompt, instructions, token, "
        "credential, raw exception, traceback, email, SMS, or PHI was printed.",
        file=sys.stderr,
    )


def _print_safe_result(result: Any) -> None:
    extraction = getattr(result, "extraction", None)
    urgency = getattr(result, "urgency", None)
    summary = getattr(extraction, "summary", "No summary returned.")
    reason = getattr(extraction, "reason_for_calling", "unknown")
    urgency_value = getattr(urgency, "urgency", "unknown")

    print("Foundry Agent smoke test completed.")
    print("A fictional demo intake was submitted to the configured NurseIntakeAgent path.")
    print(f"Urgency: {urgency_value}")
    print(f"Reason: {reason}")
    print(f"Summary: {summary}")
    print("no email or SMS was sent.")
    print("Restore AGENT_PROVIDER=mock after the manual smoke test.")


def _load_env_file(env_file: str) -> int:
    path = Path(env_file)
    if not path.exists():
        print("Foundry Agent smoke env file not found.", file=sys.stderr)
        print(
            "Create a local env file with Foundry Agent settings, or pass the "
            "correct --env-file path. No Azure call was made.",
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
                f"Invalid Foundry Agent smoke env file line {line_number}: "
                "expected KEY=value.",
                file=sys.stderr,
            )
            print("No environment values were printed. No Azure call was made.", file=sys.stderr)
            return 2

        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            print(
                f"Invalid Foundry Agent smoke env file line {line_number}: "
                "missing key.",
                file=sys.stderr,
            )
            print("No environment values were printed. No Azure call was made.", file=sys.stderr)
            return 2
        if key not in os.environ:
            os.environ[key] = _strip_optional_quotes(value.strip())

    return 0


def classify_live_agent_failure(error: BaseException) -> str:
    """Map live Foundry Agent smoke errors to safe, non-secret categories."""

    for candidate in _walk_exception_chain(error):
        if isinstance(candidate, FoundryExtractionContractError):
            return "parsing"
        if isinstance(candidate, FoundryAgentClientError):
            if candidate.category == FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY:
                return "sdk_missing"
            if candidate.category == FOUNDRY_AGENT_MISSING_CONFIGURATION_CATEGORY:
                return "configuration"

    status_code = _find_status_code(error)
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "authentication"
    if status_code == 403:
        return "authorization"
    if status_code == 404:
        return "not_found"

    chain_class_text = " ".join(
        candidate.__class__.__name__ for candidate in _walk_exception_chain(error)
    ).casefold()
    if "credentialunavailable" in chain_class_text:
        return "credential"
    if "clientauthentication" in chain_class_text or "authentication" in chain_class_text:
        return "authentication"
    if "authorization" in chain_class_text or "forbidden" in chain_class_text:
        return "authorization"
    if "notfound" in chain_class_text:
        return "not_found"
    if "badrequest" in chain_class_text:
        return "bad_request"

    return "unknown"


def _find_status_code(error: BaseException | None) -> int | None:
    if error is None:
        return None
    for candidate in _walk_exception_chain(error):
        status_code = _coerce_status_code(getattr(candidate, "status_code", None))
        if status_code is not None:
            return status_code
        status = _coerce_status_code(getattr(candidate, "status", None))
        if status is not None:
            return status
        response = getattr(candidate, "response", None)
        response_status_code = _coerce_status_code(getattr(response, "status_code", None))
        if response_status_code is not None:
            return response_status_code
        response_status = _coerce_status_code(getattr(response, "status", None))
        if response_status is not None:
            return response_status
    return None


def _coerce_status_code(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _safe_exception_class_name(error: BaseException | None) -> str:
    if error is None:
        return "none"
    class_name = error.__class__.__name__
    if class_name.isidentifier():
        return class_name
    return "unknown"


def _format_optional_status_code(status_code: int | None) -> str:
    return str(status_code) if status_code is not None else "none"


def _format_optional_bool(value: bool | None) -> str:
    if value is None:
        return "null"
    return str(value).lower()


def _walk_exception_chain(
    error: BaseException,
    max_depth: int = 5,
) -> list[BaseException]:
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < max_depth:
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
