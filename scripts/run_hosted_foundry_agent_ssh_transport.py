import argparse
import json
from pathlib import Path
import sys
from typing import TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.hosted_foundry_agent_ssh_transport import (
    HostedFoundryAgentSshTransport,
    HostedFoundryAgentSshTransportApprovals,
    HostedFoundryAgentSshTransportRequest,
    HostedFoundryAgentSshTransportResult,
    build_hosted_foundry_agent_ssh_transport_check_request,
)
from src.app.services.daily_azure_environment_rebuild import (
    READINESS_RECEIPT_FILE,
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the owned App Service tunnel contract offline."
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live-tunnel", action="store_true")
    parser.add_argument("--config", type=Path)
    parser.add_argument(
        "--readiness-receipt",
        type=Path,
        default=PROJECT_ROOT / READINESS_RECEIPT_FILE,
    )
    parser.add_argument("--json", action="store_true", required=True)
    args = parser.parse_args(argv)
    if args.check and args.config is not None:
        parser.error("--config is live-only")
    if args.live_tunnel and args.config is None:
        parser.error("--config is required for --live-tunnel")
    return args


def run_check() -> HostedFoundryAgentSshTransportResult:
    return HostedFoundryAgentSshTransport().check(
        build_hosted_foundry_agent_ssh_transport_check_request()
    )


def _prompt(
    summary: str,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> bool:
    output_stream.write(summary + "\n\nProceed? [y/N] ")
    output_stream.flush()
    try:
        return input_stream.readline().strip().casefold() in {"y", "yes"}
    except (EOFError, KeyboardInterrupt, OSError):
        return False


def _create_service() -> HostedFoundryAgentSshTransport:
    return HostedFoundryAgentSshTransport()


def run_live(
    args: argparse.Namespace,
    *,
    input_stream: TextIO,
    output_stream: TextIO,
) -> HostedFoundryAgentSshTransportResult:
    try:
        config = load_daily_azure_config(args.config, repository_root=PROJECT_ROOT)
    except ConfigValidationError:
        return HostedFoundryAgentSshTransportResult.build(
            ok=False,
            category="configuration_invalid",
            mode="live-tunnel",
        )
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    if receipt is None:
        return HostedFoundryAgentSshTransportResult.build(
            ok=False,
            category="configuration_invalid",
            mode="live-tunnel",
        )
    approvals = HostedFoundryAgentSshTransportApprovals(
        approve_tunnel=lambda: _prompt(
            "Action: start one owned App Service TCP tunnel process\n"
            "Tunnel restart permitted: no\n"
            "Raw tunnel output retained: no",
            input_stream=input_stream,
            output_stream=output_stream,
        ),
        approve_probes=lambda: _prompt(
            "Remote commands: two fixed APP_PATH prerequisite probes\n"
            "Arbitrary shell exploration permitted: no\n"
            "Probe retry permitted: no",
            input_stream=input_stream,
            output_stream=output_stream,
        ),
        approve_remote_check=lambda: _prompt(
            "Remote execution count: one\n"
            "Mode: check\n"
            "Managed identity, metadata, and Agent activity: prohibited\n"
            "Retry permitted: no",
            input_stream=input_stream,
            output_stream=output_stream,
        ),
    )
    return _create_service().run_live_tunnel(
        HostedFoundryAgentSshTransportRequest(
            mode="live-tunnel",
            subscription=config.subscription_name,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
        ),
        approvals=approvals,
    )


def main(
    argv: list[str] | None = None,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> int:
    args = _parse_args(argv)
    result = (
        run_check()
        if args.check
        else run_live(
            args,
            input_stream=input_stream or sys.stdin,
            output_stream=output_stream or sys.stderr,
        )
    )
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.ok is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
