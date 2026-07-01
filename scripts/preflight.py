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
from scripts.smoke_foundry_extraction import foundry_live_sdk_available
from scripts.smoke_speech_transcription import azure_speech_sdk_available
from src.app.config.settings import AppSettings


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

    if not args.all:
        print(
            "Run consolidated provider readiness checks with --all.",
            file=sys.stderr,
        )
        return 2

    results = run_all_checks(settings)
    _print_results(results)
    return 1 if any(result.status == FAIL for result in results) else 0


def run_all_checks(settings: AppSettings) -> list[PreflightResult]:
    return [
        _check_foundry(settings),
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
            "Run Foundry, Speech, ACS Email, and ACS SMS readiness checks "
            "without creating Azure clients, making Azure calls, processing "
            "audio, calling models, or sending notifications."
        ),
    )
    return parser.parse_args(argv)


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


def _missing_required(settings: list[tuple[str, str | None]]) -> list[str]:
    return [name for name, value in settings if value is None]


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
    print("Offline-safe checks only. No Azure clients, Azure calls, model calls, audio processing, email sends, or SMS sends are performed.")
    for result in results:
        print(f"{result.status} {result.name}: {result.message}")
        print(f"Next step: {result.next_step}")


if __name__ == "__main__":
    raise SystemExit(main())
