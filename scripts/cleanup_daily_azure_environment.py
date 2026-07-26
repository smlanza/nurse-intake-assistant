import argparse
import json
from pathlib import Path
import sys
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.daily_azure_environment_cleanup import (
    CleanupApprovalSummary,
    CleanupCommandResult,
    CleanupPurpose,
    CleanupResult,
    DailyAzureEnvironmentCleanup,
)
from src.app.services.daily_azure_environment_rebuild import (
    ConfigValidationError,
    _SubprocessRunner,
    load_daily_azure_config,
)


class _CleanupSubprocessRunner:
    def __init__(self) -> None:
        self._runner = _SubprocessRunner()

    def run(self, args: list[str]) -> CleanupCommandResult:
        outcome = self._runner.run(args)
        return CleanupCommandResult(
            outcome.return_code,
            outcome.stdout,
            outcome.stderr,
            outcome.timed_out,
        )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate, inspect, or explicitly clean the configured daily "
            "disposable Nurse Intake Assistant Azure environment."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--inspect", action="store_true")
    modes.add_argument("--cleanup", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--config", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.check and args.live:
        parser.error("--check cannot be combined with --live")
    if (args.inspect or args.cleanup) and not args.live:
        parser.error("--inspect and --cleanup require --live")
    if args.live and not args.json:
        parser.error("live modes require --json")
    return args


def _create_live_runner() -> _CleanupSubprocessRunner:
    return _CleanupSubprocessRunner()


def prompt_for_cleanup_approval(
    summary: CleanupApprovalSummary,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    purpose = (
        "startup preflight"
        if summary.purpose is CleanupPurpose.STARTUP_PREFLIGHT
        else "end of day"
    )
    try:
        print("\nDAILY DISPOSABLE AZURE CLEANUP", file=destination)
        print(f"Purpose: {purpose}", file=destination)
        print(
            "Owned resource group present: "
            + ("yes" if summary.owned_resource_group_present else "no"),
            file=destination,
        )
        print(
            "Resource group deletion required: "
            + ("yes" if summary.resource_group_deletion_required else "no"),
            file=destination,
        )
        print(
            "Matching soft-deleted Foundry accounts: "
            f"{summary.soft_deleted_foundry_account_count}",
            file=destination,
        )
        print(
            "Foundry purge required: "
            + ("yes" if summary.foundry_purge_required else "no"),
            file=destination,
        )
        print(
            "Healthy reusable environment: "
            + ("yes" if summary.healthy_reusable_environment else "no"),
            file=destination,
        )
        print(
            "Manual review required: "
            + ("yes" if summary.manual_review_required else "no"),
            file=destination,
        )
        print(
            "Destructive changes: "
            + ("yes" if summary.destructive_changes else "no"),
            file=destination,
        )
        print("Proceed? [y/N] ", end="", file=destination, flush=True)
        response = source.readline()
    except (EOFError, KeyboardInterrupt, OSError, TimeoutError):
        return False
    return response.strip().casefold() in {"y", "yes"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    purpose = CleanupPurpose.END_OF_DAY
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
        service = DailyAzureEnvironmentCleanup(
            config,
            repository_root=ROOT,
        )
        if args.check:
            result = service.check()
        else:
            runner = _create_live_runner()
            result = (
                service.inspect(purpose, runner=runner)
                if args.inspect
                else service.cleanup(
                    purpose,
                    runner=runner,
                    approver=prompt_for_cleanup_approval,
                )
            )
    except ConfigValidationError as error:
        result = CleanupResult(
            ok=False,
            category=error.category,
            purpose="local_check" if args.check else purpose.value,
        )
    except Exception:
        result = CleanupResult(
            ok=False,
            category="unexpected_error",
            purpose="local_check" if args.check else purpose.value,
            azure_mutation_made=None if args.cleanup else False,
        )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    if result.ok:
        return 0
    return 2 if args.check else 1


if __name__ == "__main__":
    raise SystemExit(main())
