import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.web_app_authentication_verification import (
    check_web_app_authentication_contract,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check the local disabled or opt-in App Service Authentication v2 "
            "contract without calling Azure."
        )
    )
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--expect-enabled", action="store_true")
    parser.add_argument("--client-application-id", action="append")
    parser.add_argument("--tenant-id", action="append")
    args = parser.parse_args(argv)
    supplied = (args.client_application_id, args.tenant_id)
    if args.expect_enabled:
        if any(not isinstance(values, list) or len(values) != 1 for values in supplied):
            parser.error(
                "--expect-enabled requires exactly one --client-application-id "
                "and --tenant-id"
            )
        args.client_application_id = args.client_application_id[0]
        args.tenant_id = args.tenant_id[0]
    elif any(supplied):
        parser.error("Entra identifiers require --expect-enabled")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configuration = (
        {
            "mode": "enabled",
            "clientId": args.client_application_id,
            "tenantId": args.tenant_id,
        }
        if args.expect_enabled
        else {"mode": "disabled"}
    )
    result = check_web_app_authentication_contract(configuration)
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
