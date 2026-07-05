import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.config.settings import AppSettings
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


def main(argv: list[str] | None = None) -> int:
    """Run an opt-in manual Azure AI Foundry Agent smoke test."""

    args = _parse_args(argv)
    if args.env_file is not None:
        env_file_exit_code = _load_env_file(args.env_file)
        if env_file_exit_code != 0:
            return env_file_exit_code
        print("Loaded Foundry Agent smoke environment file.")

    settings = AppSettings()
    if settings.agent_provider_normalized not in FOUNDRY_AGENT_PROVIDER_VALUES:
        _print_configuration_error(
            "Foundry Agent smoke test requires AGENT_PROVIDER=foundry."
        )
        return 2

    agent_status = build_nurse_intake_agent_status(settings)
    if not agent_status.ready:
        _print_configuration_error(
            "Foundry Agent smoke test missing required setting(s): "
            f"{', '.join(agent_status.missingSettings)}."
        )
        return 2

    try:
        agent = create_nurse_intake_agent(settings)
        result = asyncio.run(agent.analyze_intake(FICTIONAL_AGENT_INTAKE_TEXT))
    except Exception as exc:
        print("Foundry Agent smoke test failed.", file=sys.stderr)
        print(
            "No endpoint, agent ID, token, credential, traceback, raw exception, "
            "email, SMS, or PHI was printed.",
            file=sys.stderr,
        )
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
        "--env-file",
        help=(
            "Load Foundry Agent smoke-test settings from a KEY=value file for "
            "this script process only. Existing shell environment variables win."
        ),
    )
    return parser.parse_args(argv)


def _print_configuration_error(message: str) -> None:
    print(message, file=sys.stderr)
    print(
        "This manual script is opt-in and does not run in the automated test "
        "suite. It does not send email or SMS. Restore AGENT_PROVIDER=mock "
        "after any manual Foundry Agent smoke test.",
        file=sys.stderr,
    )


def _print_safe_result(result: Any) -> None:
    extraction = getattr(result, "extraction", None)
    urgency = getattr(result, "urgency", None)
    summary = getattr(extraction, "summary", "No summary returned.")
    reason = getattr(extraction, "reason_for_calling", "unknown")
    urgency_value = getattr(urgency, "urgency", "unknown")

    print("Foundry Agent smoke test completed.")
    print("Fictional intake was submitted to the configured NurseIntakeAgent path.")
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


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
