import argparse
import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings


def acs_sms_sdk_available() -> bool:
    """Return whether the optional Azure Communication SMS SDK is importable."""

    try:
        return importlib.util.find_spec("azure.communication.sms") is not None
    except ModuleNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    """Run offline-safe ACS SMS smoke-test preparation checks."""

    args = _parse_args(argv)
    settings = AppSettings()

    if not args.check:
        print(
            "live ACS SMS smoke mode is not implemented in this slice. Run "
            "this manual preflight with --check; no SMS send path is "
            "implemented here.",
            file=sys.stderr,
        )
        print(
            "Restore SMS_PROVIDER=mock after any manual ACS SMS preparation.",
            file=sys.stderr,
        )
        return 2

    configuration_exit_code = _validate_acs_sms_configuration(settings)
    if configuration_exit_code != 0:
        return configuration_exit_code

    print(
        "ACS SMS smoke-test preflight passed. Required configuration is "
        "present. No ACS SMS client was created, no Azure call was made, "
        "and no SMS was sent."
    )
    if acs_sms_sdk_available():
        print("Optional Azure Communication SMS SDK package appears importable.")
    else:
        print(
            "Optional Azure Communication SMS SDK package is not importable; "
            "live SMS sending remains outside this preflight."
        )
    print(
        "Live handset delivery remains deferred until toll-free verification, "
        "carrier, and Azure regulatory workflow are complete."
    )
    print("Restore SMS_PROVIDER=mock after any manual ACS SMS preparation.")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an offline-safe ACS SMS smoke-test preflight. This script "
            "validates local configuration only and does not send SMS."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate ACS SMS configuration and optional SDK visibility "
            "without creating an ACS SMS client, making an Azure call, or "
            "sending SMS."
        ),
    )
    return parser.parse_args(argv)


def _validate_acs_sms_configuration(settings: AppSettings) -> int:
    if settings.sms_provider_normalized != "acs":
        _print_configuration_error(
            "ACS SMS smoke-test preflight requires SMS_PROVIDER=acs."
        )
        return 2

    if settings.acs_sms_connection_string is None:
        _print_configuration_error(
            "ACS SMS smoke-test preflight requires ACS_SMS_CONNECTION_STRING."
        )
        return 2

    if settings.acs_sms_from_phone_number is None:
        _print_configuration_error(
            "ACS SMS smoke-test preflight requires ACS_SMS_FROM_PHONE_NUMBER."
        )
        return 2

    if settings.nurse_notification_phone_number is None:
        _print_configuration_error(
            "ACS SMS smoke-test preflight requires NURSE_NOTIFICATION_PHONE_NUMBER."
        )
        return 2

    return 0


def _print_configuration_error(message: str) -> None:
    print(message, file=sys.stderr)
    print(
        "This manual preflight is opt-in and does not run in the automated "
        "test suite. It creates no ACS SMS client, makes no Azure calls, "
        "sends no SMS, and prints no configured values. Restore "
        "SMS_PROVIDER=mock after any manual ACS SMS preparation.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
