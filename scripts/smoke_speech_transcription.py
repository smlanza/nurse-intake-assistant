import argparse
import importlib.util
import os
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

    if args.env_file is not None:
        env_file_exit_code = _load_env_file(args.env_file)
        if env_file_exit_code != 0:
            return env_file_exit_code
        print("Loaded Azure Speech smoke environment file.")

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
    parser.add_argument(
        "--env-file",
        help=(
            "Load Azure Speech smoke-test settings from a KEY=value file for "
            "this script process only. Existing shell environment variables win."
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


def _load_env_file(env_file: str) -> int:
    path = Path(env_file)
    if not path.exists():
        print("Azure Speech smoke env file not found.", file=sys.stderr)
        print(
            "Create a local .env.speech.local file from the example, or pass "
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
                f"Invalid Azure Speech smoke env file line {line_number}: "
                "expected KEY=value.",
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
                f"Invalid Azure Speech smoke env file line {line_number}: "
                "missing key.",
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


if __name__ == "__main__":
    raise SystemExit(main())
