import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.web_app_configuration_verification import (
    CommandResult,
    WebAppConfigurationVerificationResult,
    check_web_app_configuration_contract,
    verify_web_app_configuration,
)


class SubprocessAzureCliRunner:
    def run(self, args: list[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                args,
                shell=False,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return CommandResult(127, "", "")
        return CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


def _create_live_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check the local contract or explicitly read an existing Azure Web "
            "App configuration."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--resource-group")
    parser.add_argument("--web-app-name")
    args = parser.parse_args(argv)
    if args.live:
        if not args.json:
            parser.error("--live requires --json")
        if not args.resource_group or not args.web_app_name:
            parser.error("--live requires --resource-group and --web-app-name")
    elif args.resource_group or args.web_app_name:
        parser.error("resource arguments are valid only with --live")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.check:
        result = check_web_app_configuration_contract()
    else:
        contract_check = check_web_app_configuration_contract()
        if not contract_check.ok:
            result = WebAppConfigurationVerificationResult.local_contract_failure(
                "live"
            )
        else:
            try:
                runner = _create_live_runner()
                result = verify_web_app_configuration(
                    args.resource_group,
                    args.web_app_name,
                    runner=runner,
                )
            except Exception:
                result = WebAppConfigurationVerificationResult.failure(
                    "unexpected_error",
                    local_contract_validated=True,
                )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
