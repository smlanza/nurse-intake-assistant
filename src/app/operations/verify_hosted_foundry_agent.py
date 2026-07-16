import argparse
from dataclasses import replace
import json

from src.app.config.settings import AppSettings
from src.app.services.hosted_foundry_agent_verification import (
    HostedFoundryAgentVerification,
    HostedFoundryAgentVerificationResult,
    build_hosted_foundry_agent_verification_request,
    hosted_verification_sdk_available,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check or explicitly run read-only managed identity verification of "
            "the configured Foundry prompt agent and immutable version."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _create_live_verifier() -> HostedFoundryAgentVerification:
    return HostedFoundryAgentVerification()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "live"
    request = build_hosted_foundry_agent_verification_request(
        AppSettings(),
        mode=mode,
    )
    contract_check = HostedFoundryAgentVerification(
        sdk_available=hosted_verification_sdk_available
    ).check(request if mode == "check" else replace(request, mode="check"))
    if not contract_check.ok:
        result = HostedFoundryAgentVerificationResult.failure(
            mode,
            contract_check.category,
            local_contract_validated=contract_check.local_contract_validated,
        )
    elif mode == "check":
        result = contract_check
    else:
        result = _create_live_verifier().verify(request)
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    if result.ok:
        return 0
    if result.category in {
        "missing_configuration",
        "sdk_unavailable",
        "not_running_in_hosted_environment",
    }:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
