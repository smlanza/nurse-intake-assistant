import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.smoke_acs_email import acs_email_sdk_available
from scripts.smoke_acs_sms import acs_sms_sdk_available
from scripts.smoke_foundry_agent import foundry_agent_sdk_available
from scripts.smoke_foundry_extraction import foundry_live_sdk_available
from scripts.smoke_speech_transcription import azure_speech_sdk_available
from src.app.config.settings import AppSettings
from src.app.services.nurse_intake_agent_preflight import (
    build_nurse_intake_agent_status,
)


PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


@dataclass(frozen=True)
class PreflightResult:
    name: str
    status: str
    message: str
    next_step: str


def main(argv: list[str] | None = None) -> int:
    """Run consolidated offline-safe provider readiness checks."""

    args = _parse_args(argv)
    settings = AppSettings()

    if args.all:
        results = run_all_checks(settings)
    elif args.foundry_agent:
        results = [_check_foundry_agent(settings, explicit=True)]
    else:
        print(
            "Run consolidated provider readiness checks with --all or a specific "
            "provider option such as --foundry-agent.",
            file=sys.stderr,
        )
        return 2

    _print_results(results)
    return 1 if any(result.status == FAIL for result in results) else 0


def run_all_checks(settings: AppSettings) -> list[PreflightResult]:
    return [
        _check_cosmos(settings),
        _check_foundry(settings),
        _check_foundry_agent(settings),
        _check_speech(settings),
        _check_acs_email(settings),
        _check_acs_sms(settings),
    ]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run offline-safe Nurse Intake Assistant provider preflight checks. "
            "This command validates local configuration only."
        )
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Run Cosmos, Foundry, Foundry Agent, Speech, ACS Email, and ACS "
            "SMS readiness checks without creating Azure clients, making Azure "
            "calls, processing audio, calling models or agents, reading or "
            "writing repositories, or sending notifications."
        ),
    )
    parser.add_argument(
        "--foundry-agent",
        action="store_true",
        help=(
            "Run the Foundry Agent readiness check only. This validates "
            "configuration and optional SDK visibility without creating a "
            "Foundry Agent client, invoking an agent, or making an Azure call."
        ),
    )
    return parser.parse_args(argv)


def _check_cosmos(settings: AppSettings) -> PreflightResult:
    if _app_mode_normalized(settings) != "cosmos":
        return _skip(
            "Cosmos Repository",
            "APP_MODE is not cosmos.",
            "Keep APP_MODE=mock for local demo.",
        )

    missing = _missing_required(
        [
            ("COSMOS_ENDPOINT", settings.cosmos_endpoint),
            ("COSMOS_KEY", settings.cosmos_key),
            ("COSMOS_DATABASE_NAME", settings.cosmos_database_name),
            ("COSMOS_CONTAINER_NAME", settings.cosmos_container_name),
        ]
    )
    if missing:
        return _fail(
            "Cosmos Repository",
            missing,
            "Set missing Cosmos variables or restore APP_MODE=mock.",
        )

    return _pass(
        "Cosmos Repository",
        "Required Cosmos configuration is present. No Cosmos client was created, no Azure call was made, and no Cosmos read, write, or query was performed.",
        "Keep APP_MODE=mock for local demo unless you are running the manual Cosmos smoke test.",
    )


def _check_foundry(settings: AppSettings) -> PreflightResult:
    if settings.ai_provider_normalized != "foundry":
        return _skip("Foundry", "AI_PROVIDER is not foundry.", "Keep AI_PROVIDER=mock for local demo.")

    missing = _missing_required(
        [
            ("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", settings.azure_ai_foundry_project_endpoint),
            (
                "AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME",
                settings.azure_ai_foundry_model_deployment_name,
            ),
        ]
    )
    if missing:
        return _fail("Foundry", missing, "Set missing Foundry variables or restore AI_PROVIDER=mock.")

    return _pass(
        "Foundry",
        "Required Foundry configuration is present. No AI service was created and no model call was made.",
        _sdk_next_step(foundry_live_sdk_available, "Foundry SDK imports"),
    )


def _check_foundry_agent(
    settings: AppSettings,
    *,
    explicit: bool = False,
) -> PreflightResult:
    agent_status = build_nurse_intake_agent_status(settings)
    provider = agent_status.provider

    if provider == "mock":
        if explicit:
            return PreflightResult(
                name="Foundry Agent",
                status=FAIL,
                message=(
                    "Foundry Agent preflight requires "
                    "AGENT_PROVIDER=foundry-agent or AGENT_PROVIDER=foundry."
                ),
                next_step=(
                    "Set AGENT_PROVIDER=foundry-agent only for manual Foundry "
                    "Agent checks, or keep AGENT_PROVIDER=mock for local demo."
                ),
            )
        return _skip(
            "Foundry Agent",
            "AGENT_PROVIDER is mock.",
            "Keep AGENT_PROVIDER=mock for local demo.",
        )

    if provider not in {"foundry", "foundry-agent"}:
        return PreflightResult(
            name="Foundry Agent",
            status=FAIL,
            message=(
                "Unsupported AGENT_PROVIDER for Foundry Agent preflight. "
                "Use AGENT_PROVIDER=foundry-agent or AGENT_PROVIDER=foundry."
            ),
            next_step="Restore AGENT_PROVIDER=mock for local demo.",
        )

    if not agent_status.ready:
        return _fail(
            "Foundry Agent",
            agent_status.missingSettings,
            (
                "Set missing Foundry Agent variables or restore "
                "AGENT_PROVIDER=mock."
            ),
        )

    return _pass(
        "Foundry Agent",
        (
            "Required Foundry Agent configuration is present. "
            "Readiness is configuration-only. No Foundry Agent client was "
            "created, no agent was invoked, and no Azure call was made."
        ),
        _sdk_next_step(
            foundry_agent_sdk_available,
            "Foundry Agent SDK package",
        ),
    )


def _check_speech(settings: AppSettings) -> PreflightResult:
    if settings.speech_provider_normalized != "azure":
        return _skip(
            "Azure Speech",
            "SPEECH_PROVIDER is not azure.",
            "Keep SPEECH_PROVIDER=mock for local demo.",
        )

    missing = _missing_required(
        [
            ("AZURE_SPEECH_ENDPOINT", settings.azure_speech_endpoint),
            ("AZURE_SPEECH_REGION", settings.azure_speech_region),
        ]
    )
    if missing:
        return _fail(
            "Azure Speech",
            missing,
            "Set missing Azure Speech variables or restore SPEECH_PROVIDER=mock.",
        )

    return _pass(
        "Azure Speech",
        "Required Speech configuration is present. No Speech client was created, no audio was processed, and no Azure call was made.",
        _sdk_next_step(azure_speech_sdk_available, "Azure Speech SDK package"),
    )


def _check_acs_email(settings: AppSettings) -> PreflightResult:
    if settings.email_provider_normalized != "acs":
        return _skip(
            "ACS Email",
            "EMAIL_PROVIDER is not acs.",
            "Keep EMAIL_PROVIDER=mock for local demo.",
        )

    missing = _missing_required(
        [
            ("ACS_EMAIL_CONNECTION_STRING", settings.acs_email_connection_string),
            ("ACS_EMAIL_SENDER_ADDRESS", settings.acs_email_sender_address),
            ("NURSE_NOTIFICATION_EMAIL", settings.nurse_notification_email),
        ]
    )
    if missing:
        return _fail(
            "ACS Email",
            missing,
            "Set missing ACS Email variables or restore EMAIL_PROVIDER=mock.",
        )

    return _pass(
        "ACS Email",
        "Required ACS Email configuration is present. No ACS Email client was created, no Azure call was made, and no email was sent.",
        _sdk_next_step(acs_email_sdk_available, "Azure Communication Email SDK package"),
    )


def _check_acs_sms(settings: AppSettings) -> PreflightResult:
    if settings.sms_provider_normalized != "acs":
        return _skip(
            "ACS SMS",
            "SMS_PROVIDER is not acs.",
            "Keep SMS_PROVIDER=mock for local demo.",
        )

    missing = _missing_required(
        [
            ("ACS_SMS_CONNECTION_STRING", settings.acs_sms_connection_string),
            ("ACS_SMS_FROM_PHONE_NUMBER", settings.acs_sms_from_phone_number),
            ("NURSE_NOTIFICATION_PHONE_NUMBER", settings.nurse_notification_phone_number),
        ]
    )
    if missing:
        return _fail(
            "ACS SMS",
            missing,
            "Set missing ACS SMS variables or restore SMS_PROVIDER=mock.",
        )

    return _pass(
        "ACS SMS",
        "Required ACS SMS configuration is present. No ACS SMS client was created, no Azure call was made, and no SMS was sent.",
        (
            _sdk_next_step(acs_sms_sdk_available, "Azure Communication SMS SDK package")
            + " Live handset delivery remains deferred until toll-free verification, carrier, and Azure regulatory workflow are complete."
        ),
    )


def _app_mode_normalized(settings: AppSettings) -> str:
    configured = getattr(settings, "app_mode_normalized", settings.app_mode)
    return configured.strip().lower() or "mock"


def _missing_required(settings: list[tuple[str, str | None]]) -> list[str]:
    return [name for name, value in settings if value is None or not value.strip()]


def _skip(name: str, message: str, next_step: str) -> PreflightResult:
    return PreflightResult(name=name, status=SKIP, message=message, next_step=next_step)


def _fail(name: str, missing: list[str], next_step: str) -> PreflightResult:
    return PreflightResult(
        name=name,
        status=FAIL,
        message=f"Missing required configuration: {', '.join(missing)}.",
        next_step=next_step,
    )


def _pass(name: str, message: str, next_step: str) -> PreflightResult:
    return PreflightResult(name=name, status=PASS, message=message, next_step=next_step)


def _sdk_next_step(sdk_available: Callable[[], bool], package_name: str) -> str:
    if sdk_available():
        return f"Optional {package_name} appears importable."
    return f"Optional {package_name} is not importable; live behavior remains outside this preflight."


def _print_results(results: list[PreflightResult]) -> None:
    print("Nurse Intake Assistant Preflight")
    print(
        "Offline-safe checks only. No Azure clients, Azure calls, model calls, "
        "agent calls, audio processing, repository reads/writes/queries, email "
        "sends, or SMS sends are performed."
    )
    for result in results:
        print(f"{result.status} {result.name}: {result.message}")
    print(_format_summary(results))
    print(_format_guidance(results))


def _format_summary(results: list[PreflightResult]) -> str:
    pass_count = _count_status(results, PASS)
    skip_count = _count_status(results, SKIP)
    fail_count = _count_status(results, FAIL)
    outcome = (
        "Completed safely with no failed checks."
        if fail_count == 0
        else "One or more checks failed."
    )
    return (
        f"Preflight summary: PASS={pass_count}, SKIP={skip_count}, "
        f"FAIL={fail_count}. {outcome}"
    )


def _format_guidance(results: list[PreflightResult]) -> str:
    lines = ["Guidance:"]
    failed_results = [result for result in results if result.status == FAIL]
    pass_results = [result for result in results if result.status == PASS]

    if failed_results:
        lines.extend(
            f"- {result.name}: {result.next_step}"
            for result in failed_results
        )
        lines.append(
            "- A FAIL result means the requested provider is not enabled or required local configuration is missing; this preflight did not call Azure."
        )
        return "\n".join(lines)

    lines.append(
        "- For the local demo, keep APP_MODE, AI_PROVIDER, AGENT_PROVIDER, "
        "SPEECH_PROVIDER, EMAIL_PROVIDER, and SMS_PROVIDER set to mock."
    )
    lines.append(
        "- Enable one live provider at a time only for explicit manual smoke testing."
    )

    lines.extend(
        f"- {result.name}: {result.next_step}"
        for result in pass_results
    )

    lines.append("- This preflight remains offline-safe and does not call Azure.")
    return "\n".join(lines)


def _count_status(results: list[PreflightResult], status: str) -> int:
    return sum(1 for result in results if result.status == status)


if __name__ == "__main__":
    raise SystemExit(main())
