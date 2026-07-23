import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.hosted_foundry_agent_webjob_state_recovery import (
    HostedWebJobStateRecoveryRequest,
    inspect_hosted_webjob_state,
    recover_hosted_webjob_state,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect or manually archive immutable hosted WebJob evidence offline."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--inspect", action="store_true")
    modes.add_argument("--archive", action="store_true")
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-environment-fingerprint")
    parser.add_argument("--manifest-digest")
    parser.add_argument(
        "--reason",
        choices=(
            "stale_environment_evidence",
            "completed_generation_retirement",
        ),
    )
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _request(args: argparse.Namespace) -> HostedWebJobStateRecoveryRequest:
    mode = "check" if args.check else "inspect" if args.inspect else "archive"
    return HostedWebJobStateRecoveryRequest(
        mode=mode,
        source_root=args.source_root.absolute(),
        expected_environment_fingerprint=args.expected_environment_fingerprint,
        manifest_digest=args.manifest_digest,
        reason=args.reason,
    )


def _approval() -> bool:
    sys.stderr.write(
        "Archive the exact inspected immutable WebJob evidence? [y/N]: "
    )
    sys.stderr.flush()
    try:
        answer = sys.stdin.readline()
    except KeyboardInterrupt:
        return False
    except Exception:
        return False
    return isinstance(answer, str) and answer.strip().casefold() in {"y", "yes"}


def _declined() -> dict[str, object]:
    return {
        "ok": False,
        "mode": "archive",
        "category": "approval_required",
        "state": "unchanged",
        "manifest_digest": None,
        "environment_fingerprint_digest": None,
        "files": [],
        "archive_relative_path": None,
        "retirement_receipt_relative_path": None,
        "azure_operation_attempted": False,
        "webjob_triggered": False,
        "daily_environment_ready": False,
        "recommended_next_step": "Review the manifest and issue a new explicit archive command.",
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    request = _request(args)
    if request.mode == "archive" and not _approval():
        payload = _declined()
        code = 2
    else:
        result = (
            recover_hosted_webjob_state(request)
            if request.mode == "archive"
            else inspect_hosted_webjob_state(request)
        )
        payload = result.to_json_dict()
        code = 0 if result.ok else 2
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
