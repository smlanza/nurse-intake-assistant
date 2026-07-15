import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.web_app_readiness_verification import (
    UrllibWebAppReadinessTransport,
    check_web_app_readiness_configuration,
    verify_web_app_readiness,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or explicitly verify an existing Nurse Intake Assistant Web "
            "App through its read-only public readiness endpoints."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument(
        "--check",
        action="store_true",
        help="Validate the HTTPS base URL without creating an HTTP transport.",
    )
    modes.add_argument(
        "--live",
        action="store_true",
        help="GET the three hosted readiness endpoints without mutation or retries.",
    )
    parser.add_argument("--base-url")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def _create_live_transport(base_url: str) -> UrllibWebAppReadinessTransport:
    return UrllibWebAppReadinessTransport(base_url)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.check:
        result = check_web_app_readiness_configuration(args.base_url)
    else:
        result = verify_web_app_readiness(
            args.base_url,
            transport_factory=_create_live_transport,
        )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    if result.ok:
        return 0
    if result.category in {"missing_configuration", "invalid_configuration"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

