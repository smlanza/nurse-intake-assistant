import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.hosted_foundry_agent_webjob_execution import (
    AzureCliProcessNotStarted,
    CommandResult,
    HostedFoundryAgentWebJobExecutionRequest,
    execute_hosted_foundry_agent_webjob,
)
from src.app.services.daily_azure_environment_rebuild import (
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)
from src.app.services.hosted_foundry_agent_webjob_handoff import (
    load_hosted_foundry_agent_webjob_handoff,
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
        except OSError as error:
            raise AzureCliProcessNotStarted() from error
        return CommandResult(
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )


def _create_azure_cli_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check, discover, trigger, or read one receipt-correlated status "
            "for the fixed hosted Foundry metadata-verification WebJob."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live-discover", action="store_true")
    modes.add_argument("--live-trigger", action="store_true")
    modes.add_argument("--live-status", action="store_true")
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--web-app-name", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--readiness-receipt", type=Path)
    parser.add_argument("--environment-fingerprint")
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _generation_handoff_failure(mode: str) -> dict[str, object]:
    return {
        "ok": False,
        "mode": mode,
        "category": "generation_handoff_invalid",
        "operation": "execute_hosted_foundry_agent_webjob",
        "local_entrypoint_present": False,
        "remote_webjob_discovered": False,
        "configuration_contract_valid": False,
        "package_contract_valid": False,
        "azure_operation_attempted": False,
        "trigger_request_accepted": False,
        "trigger_reservation_active": False,
        "trigger_receipt_valid": False,
        "trigger_blocked": False,
        "correlated_run_observed": False,
        "correlated_run_terminal": False,
        "correlated_run_succeeded": False,
        "terminal_outcome_recorded": False,
        "metadata_verification_proven": False,
        "invocation_attempted": False,
        "recommended_next_step": (
            "Stop and prepare a current private WebJob generation handoff."
        ),
    }


def _live_environment_fingerprint(args: argparse.Namespace) -> str | None:
    if args.config is None or args.readiness_receipt is None:
        return None
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
    except ConfigValidationError:
        return None
    if (
        config.resource_group != args.resource_group
        or config.web_app_name != args.web_app_name
    ):
        return None
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    if receipt is None:
        return None
    handoff = load_hosted_foundry_agent_webjob_handoff(
        ROOT,
        receipt,
        resource_group=args.resource_group,
        web_app_name=args.web_app_name,
    )
    if handoff is None:
        return None
    if (
        args.environment_fingerprint is not None
        and args.environment_fingerprint != handoff.environment_fingerprint
    ):
        return None
    return handoff.environment_fingerprint


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = (
        "check"
        if args.check
        else "live-discover"
        if args.live_discover
        else "live-trigger"
        if args.live_trigger
        else "live-status"
    )
    environment_fingerprint = (
        None if mode == "check" else _live_environment_fingerprint(args)
    )
    if mode != "check" and environment_fingerprint is None:
        print(
            json.dumps(
                _generation_handoff_failure(mode),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 2
    request = HostedFoundryAgentWebJobExecutionRequest(
        mode=mode,
        resource_group=args.resource_group,
        web_app_name=args.web_app_name,
        source_root=ROOT,
        environment_fingerprint=environment_fingerprint,
    )
    if mode == "check":
        result = execute_hosted_foundry_agent_webjob(request)
    else:
        result = execute_hosted_foundry_agent_webjob(
            request,
            runner_factory=_create_azure_cli_runner,
        )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
