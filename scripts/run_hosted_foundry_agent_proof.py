import argparse
from dataclasses import dataclass
import importlib
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.hosted_foundry_agent_proof import (
    HostedFoundryAgentProofResult,
    hosted_foundry_agent_proof_check_result_valid,
)


PACKAGED_MODULE = "src.app.operations.prove_hosted_foundry_agent"
FIXED_REMOTE_COMMAND = (
    "python",
    "-m",
    PACKAGED_MODULE,
    "--live",
    "--json",
)
OPERATION = "run_hosted_foundry_agent_proof"


@dataclass(frozen=True)
class HostedFoundryAgentProofCliResult:
    proof: HostedFoundryAgentProofResult
    packaged_operation_validated: bool
    remote_command_contract_validated: bool

    def to_json_dict(self) -> dict[str, object]:
        payload = self.proof.to_json_dict()
        payload.update(
            operation=OPERATION,
            packaged_operation_validated=self.packaged_operation_validated,
            remote_command_contract_validated=(
                self.remote_command_contract_validated
            ),
            ssh_connection_attempted=False,
            subprocess_attempted=False,
        )
        return payload


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the fixed future hosted proof command contract offline."
    )
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _remote_command_contract_valid() -> bool:
    return FIXED_REMOTE_COMMAND == (
        "python",
        "-m",
        "src.app.operations.prove_hosted_foundry_agent",
        "--live",
        "--json",
    )


def run_check() -> HostedFoundryAgentProofCliResult:
    try:
        operation = importlib.import_module(PACKAGED_MODULE)
        module_valid = bool(
            operation.__name__ == PACKAGED_MODULE
            and callable(getattr(operation, "run_hosted_foundry_agent_proof", None))
        )
        if not module_valid or not _remote_command_contract_valid():
            raise ValueError("invalid packaged proof contract")
        proof = operation.run_hosted_foundry_agent_proof("check")
        if not hosted_foundry_agent_proof_check_result_valid(proof):
            raise ValueError("invalid packaged proof result")
        return HostedFoundryAgentProofCliResult(
            proof=proof,
            packaged_operation_validated=True,
            remote_command_contract_validated=True,
        )
    except Exception:
        return HostedFoundryAgentProofCliResult(
            proof=HostedFoundryAgentProofResult.failure(
                "check", "dependency_check_failed"
            ),
            packaged_operation_validated=False,
            remote_command_contract_validated=False,
        )


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv)
    result = run_check()
    print(json.dumps(result.to_json_dict(), separators=(",", ":"), sort_keys=True))
    return 0 if result.proof.ok is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
