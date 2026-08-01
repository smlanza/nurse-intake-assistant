import argparse
import json

from src.app.config.settings import AppSettings
from src.app.services.hosted_foundry_agent_proof import (
    HostedFoundryAgentProof,
    HostedFoundryAgentProofResult,
    build_hosted_foundry_agent_proof_check_request,
    build_hosted_foundry_agent_proof_request,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or run the packaged synchronous hosted Foundry proof operation."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _create_proof_service() -> HostedFoundryAgentProof:
    return HostedFoundryAgentProof()


def run_hosted_foundry_agent_proof(mode: str) -> HostedFoundryAgentProofResult:
    try:
        if mode == "check":
            request = build_hosted_foundry_agent_proof_check_request(mode="check")
            return _create_proof_service().check(request)
        if mode == "live":
            request = build_hosted_foundry_agent_proof_request(
                AppSettings(),
                mode="live",
            )
            return _create_proof_service().prove(request)
        return HostedFoundryAgentProofResult.failure(
            mode,
            "configuration_invalid",
            local_contract_validated=False,
        )
    except Exception:
        return HostedFoundryAgentProofResult.failure(mode, "unexpected_error")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "live"
    result = run_hosted_foundry_agent_proof(mode)
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    if result.ok is True:
        return 0
    if result.category in {
        "configuration_invalid",
        "dependency_check_failed",
        "not_running_in_hosted_environment",
    }:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
