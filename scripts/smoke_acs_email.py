import argparse
import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings


def acs_email_sdk_available() -> bool:
    """Return whether the optional Azure Communication Email SDK is importable."""

    try:
        return importlib.util.find_spec("azure.communication.email") is not None
    except ModuleNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    """Run offline-safe ACS Email smoke-test preparation checks."""

    args = _parse_args(argv)
    settings = AppSettings()

    if not args.check:
        print(
            "live ACS Email smoke mode is not implemented in this slice. Run "
            "this manual preflight with --check; no email send path is "
            "implemented here.",
            file=sys.stderr,
        )
        print(
            "Restore EMAIL_PROVIDER=mock after any manual ACS Email "
            "preparation.",
            file=sys.stderr,
        )
        return 2

    configuration_exit_code = _validate_acs_email_configuration(settings)
    if configuration_exit_code != 0:
        return configuration_exit_code

    print(
        "ACS Email smoke-test preflight passed. Required configuration is "
        "present. No ACS Email client was created, no Azure call was made, "
        "and no email was sent."
    )
    if acs_email_sdk_available():
        print("Optional Azure Communication Email SDK package appears importable.")
    else:
        print(
            "Optional Azure Communication Email SDK package is not importable; "
            "live email sending remains outside this preflight."
        )
    print("Restore EMAIL_PROVIDER=mock after any manual ACS Email preparation.")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an offline-safe ACS Email smoke-test preflight. This script "
            "validates local configuration only and does not send email."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate ACS Email configuration and optional SDK visibility "
            "without creating an ACS Email client, making an Azure call, or "
            "sending email."
        ),
    )
    return parser.parse_args(argv)


def _validate_acs_email_configuration(settings: AppSettings) -> int:
    if settings.email_provider_normalized != "acs":
        _print_configuration_error(
            "ACS Email smoke-test preflight requires EMAIL_PROVIDER=acs."
        )
        return 2

    if settings.acs_email_connection_string is None:
        _print_configuration_error(
            "ACS Email smoke-test preflight requires ACS_EMAIL_CONNECTION_STRING."
        )
        return 2

    if settings.acs_email_sender_address is None:
        _print_configuration_error(
            "ACS Email smoke-test preflight requires ACS_EMAIL_SENDER_ADDRESS."
        )
        return 2

    if settings.nurse_notification_email is None:
        _print_configuration_error(
            "ACS Email smoke-test preflight requires NURSE_NOTIFICATION_EMAIL."
        )
        return 2

    return 0


def _print_configuration_error(message: str) -> None:
    print(message, file=sys.stderr)
    print(
        "This manual preflight is opt-in and does not run in the automated "
        "test suite. It creates no ACS Email client, makes no Azure calls, "
        "sends no email, and prints no configured values. Restore "
        "EMAIL_PROVIDER=mock after any manual ACS Email preparation.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
