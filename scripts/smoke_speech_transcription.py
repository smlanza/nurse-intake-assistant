import argparse
import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings


def azure_speech_sdk_available() -> bool:
    """Return whether the optional Azure Speech SDK module appears importable."""

    try:
        return importlib.util.find_spec("azure.cognitiveservices.speech") is not None
    except ModuleNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    """Run offline-safe Azure Speech smoke-test preparation checks."""

    args = _parse_args(argv)
    settings = AppSettings()

    if not args.check:
        print(
            "Azure Speech live transcription is deferred. Run this manual "
            "preflight with --check; no live Speech path is implemented.",
            file=sys.stderr,
        )
        print(
            "Restore SPEECH_PROVIDER=mock after any manual Speech preparation.",
            file=sys.stderr,
        )
        return 2

    configuration_exit_code = _validate_speech_configuration(settings)
    if configuration_exit_code != 0:
        return configuration_exit_code

    print(
        "Azure Speech smoke-test preflight passed. Required configuration is "
        "present. No Speech client was created and no Azure call was made."
    )
    if azure_speech_sdk_available():
        print("Optional Azure Speech SDK package appears importable.")
    else:
        print(
            "Optional Azure Speech SDK package is not importable; live "
            "transcription remains deferred."
        )
    print("Restore SPEECH_PROVIDER=mock after any manual Speech preparation.")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run an offline-safe Azure Speech smoke-test preflight. This "
            "script validates local configuration only and does not transcribe "
            "audio."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate Azure Speech configuration and optional SDK visibility "
            "without creating a Speech client or making an Azure call."
        ),
    )
    return parser.parse_args(argv)


def _validate_speech_configuration(settings: AppSettings) -> int:
    if settings.speech_provider_normalized != "azure":
        _print_configuration_error(
            "Azure Speech smoke-test preflight requires SPEECH_PROVIDER=azure."
        )
        return 2

    if settings.azure_speech_endpoint is None:
        _print_configuration_error(
            "Azure Speech smoke-test preflight requires AZURE_SPEECH_ENDPOINT."
        )
        return 2

    if settings.azure_speech_region is None:
        _print_configuration_error(
            "Azure Speech smoke-test preflight requires AZURE_SPEECH_REGION."
        )
        return 2

    return 0


def _print_configuration_error(message: str) -> None:
    print(message, file=sys.stderr)
    print(
        "This manual preflight is opt-in and does not run in the automated "
        "test suite. Restore SPEECH_PROVIDER=mock after any manual Speech "
        "preparation.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    raise SystemExit(main())
