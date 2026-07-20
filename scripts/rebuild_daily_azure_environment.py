import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.daily_azure_environment_rebuild import (
    ConfigValidationError,
    DailyAzureEnvironmentRebuild,
    DailyAzureEnvironmentRebuildResult,
    RepositoryDailyAzureStageRunner,
    load_daily_azure_config,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline-check or explicitly rebuild the disposable Nurse Intake "
            "Assistant Azure environment without invocation."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--config", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--skip-webjob-discovery", action="store_true")
    args = parser.parse_args(argv)
    if args.live and not args.json:
        parser.error("--live requires --json")
    return args


def _create_live_runner(config):
    return RepositoryDailyAzureStageRunner(config, repository_root=ROOT)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "live"
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
        if args.skip_webjob_discovery:
            config = replace(config, discover_hosted_foundry_webjob=False)
        service = DailyAzureEnvironmentRebuild(
            config,
            repository_root=ROOT,
            runner_factory=(lambda: _create_live_runner(config)),
        )
        result = service.check() if args.check else service.live()
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
