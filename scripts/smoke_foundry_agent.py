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
    FOUNDRY_AGENT_SDK_UNAVAILABLE_CATEGORY,
    FoundryAgentClientError,
    foundry_agent_sdk_available,
)
from src.app.services.foundry_extraction_contract import (
    FoundryExtractionContractError,
)
from src.app.services.nurse_intake_agent_factory import create_nurse_intake_agent
from src.app.services.nurse_intake_agent_preflight import (
    build_nurse_intake_agent_status,
)


FICTIONAL_AGENT_INTAKE_TEXT = (
    "Demo patient Taylor Quinn requests a nurse callback about a routine "
    "medication refill. Callback number is demo-callback-002. No chest pain, "
    "shortness of breath, fainting, or severe symptoms reported."
)
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
    "authentication_failed": "Check Azure credential login and tenant access.",
    "authorization_failed": "Check project RBAC permissions for the signed-in identity.",
    "agent_not_found": "Check that the configured Foundry Agent still exists.",
    "bad_request": "Check the Foundry Agent request configuration.",
    "contract_invalid": "Check that the agent response matches the expected contract.",
    "response_parse_failed": "Check that the agent returned valid structured JSON.",
    "unknown_failure": "Check local settings, Azure login, RBAC, SDK compatibility, and agent availability.",
}
LIVE_RESULT_CATEGORY_BY_LEGACY_CATEGORY = {
    "configuration": "missing_configuration",
    "credential": "authentication_failed",
    "authentication": "authentication_failed",
    "authorization": "authorization_failed",
    "not_found": "agent_not_found",
    "bad_request": "bad_request",
    "sdk_missing": "sdk_unavailable",
    "parsing": "contract_invalid",
    "unknown": "unknown_failure",
}


@dataclass(frozen=True)
class FoundryAgentSmokeResult:
    provider: str
    mode: str
    configured: bool
    sdk_available: bool
    attempted: bool
    status: Literal["succeeded", "failed"]
    safe_failure_category: str | None
    next_step_hint: str | None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "configured": self.configured,
            "sdkAvailable": self.sdk_available,
            "attempted": self.attempted,
            "status": self.status,
            "safeFailureCategory": self.safe_failure_category,
            "nextStepHint": self.next_step_hint,
        }


def main(argv: list[str] | None = None) -> int:
    """Run an opt-in manual Azure AI Foundry Agent smoke test."""

    args = _parse_args(argv)

    if not args.check and not args.live:
        print(
            "Foundry Agent smoke mode is explicit; rerun with --check or --live.",
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

    configuration_exit_code = _validate_foundry_agent_configuration(settings)
    if configuration_exit_code != 0:
        return configuration_exit_code

    if args.check:
        _print_check_success()
        return 0

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
    args = parser.parse_args(argv)
    if args.check and args.live:
        parser.error("--check and --live cannot be used together")
    if args.json and not args.live:
        parser.error("--json is only supported with --live")
    return args


def _run_live_json_smoke(settings: AppSettings) -> tuple[FoundryAgentSmokeResult, int]:
    sdk_available = foundry_agent_sdk_available()
    if not _foundry_agent_configured(settings):
        return (
            _failed_live_result(
                configured=False,
                sdk_available=sdk_available,
                attempted=False,
                safe_failure_category="missing_configuration",
            ),
            2,
        )

    if not sdk_available:
        return (
            _failed_live_result(
                configured=True,
                sdk_available=False,
                attempted=False,
                safe_failure_category="sdk_unavailable",
            ),
            1,
        )

    try:
        agent = create_nurse_intake_agent(settings)
        asyncio.run(agent.analyze_intake(FICTIONAL_AGENT_INTAKE_TEXT))
    except Exception as exc:
        safe_category = _live_result_category(exc)
        return (
            _failed_live_result(
                configured=True,
                sdk_available=True,
                attempted=True,
                safe_failure_category=safe_category,
            ),
            1,
        )

    return (
        FoundryAgentSmokeResult(
            provider="foundry-agent",
            mode="live",
            configured=True,
            sdk_available=True,
            attempted=True,
            status="succeeded",
            safe_failure_category=None,
            next_step_hint=None,
        ),
        0,
    )


def _failed_live_result(
    *,
    configured: bool,
    sdk_available: bool,
    attempted: bool,
    safe_failure_category: str,
) -> FoundryAgentSmokeResult:
    return FoundryAgentSmokeResult(
        provider="foundry-agent",
        mode="live",
        configured=configured,
        sdk_available=sdk_available,
        attempted=attempted,
        status="failed",
        safe_failure_category=safe_failure_category,
        next_step_hint=SAFE_RESULT_HINTS[safe_failure_category],
    )


def _print_json_result(result: FoundryAgentSmokeResult) -> None:
    print(json.dumps(result.to_json_dict(), separators=(",", ":")))


def _foundry_agent_configured(settings: AppSettings) -> bool:
    if settings.agent_provider_normalized not in FOUNDRY_AGENT_PROVIDER_VALUES:
        return False
    return build_nurse_intake_agent_status(settings).ready


def _live_result_category(error: BaseException) -> str:
    legacy_category = classify_live_agent_failure(error)
    return LIVE_RESULT_CATEGORY_BY_LEGACY_CATEGORY.get(
        legacy_category,
        "unknown_failure",
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


def _print_check_success() -> None:
    sdk_message = (
        "Optional Foundry Agent SDK package appears importable."
        if foundry_agent_sdk_available()
        else "Optional Foundry Agent SDK package is not importable."
    )
    print(
        "Foundry Agent smoke-test preflight passed. Required configuration is "
        "present. No Foundry Agent client was created. No Azure call was made."
    )
    print(sdk_message)
    print("Restore AGENT_PROVIDER=mock after any manual Foundry Agent smoke test.")


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


def _find_status_code(error: BaseException) -> int | None:
    for candidate in _walk_exception_chain(error):
        status_code = getattr(candidate, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        response = getattr(candidate, "response", None)
        response_status_code = getattr(response, "status_code", None)
        if isinstance(response_status_code, int):
            return response_status_code
    return None


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
