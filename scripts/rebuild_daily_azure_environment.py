import argparse
import json
from pathlib import Path
import sys
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.daily_azure_environment_rebuild import (
    ApprovalSummary,
    ConfigValidationError,
    DailyAzureEnvironmentRebuild,
    DailyAzureEnvironmentRebuildResult,
    RepositoryDailyAzureStageRunner,
    load_daily_azure_config,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline-check or guide an operator-approved rebuild of the disposable "
            "Nurse Intake Assistant Azure environment through verified application-hosting readiness."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--config", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def _create_live_runner(config):
    return RepositoryDailyAzureStageRunner(config, repository_root=ROOT)


def prompt_for_stage_approval(
    summary: ApprovalSummary,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    try:
        print(f"\n{summary.heading}", file=destination)
        for label, value in summary.facts:
            print(f"{label}: {value}", file=destination)
        print("Proceed? [y/N] ", end="", file=destination, flush=True)
        response = source.readline()
    except (EOFError, KeyboardInterrupt, OSError, TimeoutError):
        return False
    return response.strip().casefold() in {"y", "yes"}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "live"
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
        service = DailyAzureEnvironmentRebuild(
            config,
            repository_root=ROOT,
            runner_factory=(lambda: _create_live_runner(config)),
        )
        result = (
            service.check()
            if args.check
            else service.live(approver=prompt_for_stage_approval)
        )
    except ConfigValidationError as error:
        result = DailyAzureEnvironmentRebuildResult(
            ok=False,
            category=error.category,
            mode=mode,
        )
    except Exception:
        result = DailyAzureEnvironmentRebuildResult(
            ok=False,
            category="unexpected_error",
            mode=mode,
        )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    if result.ok:
        return 0
    return 2 if mode == "check" else 1


if __name__ == "__main__":
    raise SystemExit(main())
