import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.foundry_agent_consumer_rbac_deployment import (
    CommandResult,
    DEPLOYMENT_NAME,
    EXPECTED_TEMPLATE,
    FoundryAgentConsumerRbacDeploymentEvidence,
    FoundryAgentConsumerRbacDeploymentRequest,
    deploy_foundry_agent_consumer_rbac,
    validate_foundry_agent_consumer_rbac_request,
)
from src.app.services.foundry_agent_consumer_rbac_verification import (
    FoundryAgentConsumerRbacVerificationRequest,
    verify_foundry_agent_consumer_rbac,
)
from src.app.services.daily_azure_environment_rebuild import (
    READINESS_RECEIPT_FILE,
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
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


def _create_azure_cli_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check, preview, or explicitly request the existing project-scoped "
            "Foundry Agent Consumer RBAC deployment."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--what-if", action="store_true")
    modes.add_argument("--live", action="store_true")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--readiness-receipt",
        type=Path,
        default=ROOT / READINESS_RECEIPT_FILE,
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _request(
    args: argparse.Namespace,
    *,
    resource_group: str,
    web_app_name: str,
    foundry_account_name: str,
    foundry_project_name: str,
    evidence: FoundryAgentConsumerRbacDeploymentEvidence | None = None,
) -> FoundryAgentConsumerRbacDeploymentRequest:
    mode = "check" if args.check else "what-if" if args.what_if else "live"
    return FoundryAgentConsumerRbacDeploymentRequest(
        mode=mode,
        resource_group=resource_group,
        web_app_name=web_app_name,
        foundry_account_name=foundry_account_name,
        foundry_project_name=foundry_project_name,
        template_file=EXPECTED_TEMPLATE,
        approved_evidence=evidence,
    )


def _safe_failure(
    category: str,
    mode: str,
    *,
    azure_operation_attempted: bool = False,
    rbac_handoff_validated: bool = False,
    azure_mutation_made: bool | None = False,
    deployment_request_accepted: bool = False,
    assignment_verified: bool = False,
) -> dict[str, object]:
    return {
        "ok": False,
        "category": category,
        "operation": "deploy_foundry_agent_consumer_rbac",
        "mode": mode,
        "rbac_handoff_validated": rbac_handoff_validated,
        "azure_operation_attempted": azure_operation_attempted,
        "azure_mutation_made": azure_mutation_made,
        "deployment_request_accepted": deployment_request_accepted,
        "assignment_verified": assignment_verified,
        "recommended_next_step": (
            "Stop and regenerate a matching coordinator readiness receipt."
        ),
    }


def prompt_for_rbac_approval(
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    destination.write(
        "Action: create one Foundry Agent Consumer role assignment\n"
        "Principal verified: yes\n"
        "Project scope verified: yes\n"
        "Fixed role verified: yes\n"
        "Deterministic assignment verified: yes\n"
        "Mutation required: yes\n"
        "\n"
        "Proceed? [y/N] "
    )
    destination.flush()
    return source.readline().strip().casefold() in {"y", "yes"}


def _verification_proves_exact_assignment(result: object) -> bool:
    return bool(
        getattr(result, "ok", False)
        and getattr(result, "category", None) == "success"
        and getattr(result, "web_app_identity_present", False)
        and getattr(result, "foundry_project_scope_resolved", False)
        and getattr(result, "consumer_assignment_present", False)
        and getattr(result, "consumer_assignment_scope_matches", False)
        and getattr(result, "consumer_role_matches", False)
        and getattr(result, "matching_assignment_count", None) == 1
    )


def _emit_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def _account_matches_handoff(
    runner: SubprocessAzureCliRunner,
    *,
    resource_group: str,
    foundry_account_name: str,
) -> bool:
    outcome = runner.run(
        [
            "az",
            "cognitiveservices",
            "account",
            "show",
            "--resource-group",
            resource_group,
            "--name",
            foundry_account_name,
            "--query",
            "{name:name,id:id}",
            "--output",
            "json",
            "--only-show-errors",
        ]
    )
    if outcome.return_code != 0:
        return False
    try:
        payload = json.loads(outcome.stdout)
    except (TypeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(payload, dict)
        or set(payload) != {"name", "id"}
        or payload.get("name") != foundry_account_name
        or not isinstance(payload.get("id"), str)
    ):
        return False
    parts = payload["id"].split("/")
    return bool(
        len(parts) == 9
        and parts[3].casefold() == "resourcegroups"
        and parts[4].casefold() == resource_group.casefold()
        and parts[5].casefold() == "providers"
        and parts[6].casefold() == "microsoft.cognitiveservices"
        and parts[7].casefold() == "accounts"
        and parts[8].casefold() == foundry_account_name.casefold()
    )


def _fresh_evidence(
    runner: SubprocessAzureCliRunner,
    *,
    resource_group: str,
    web_app_name: str,
    foundry_account_name: str,
    foundry_project_name: str,
) -> tuple[FoundryAgentConsumerRbacDeploymentEvidence | None, str | None]:
    verified = verify_foundry_agent_consumer_rbac(
        FoundryAgentConsumerRbacVerificationRequest(
            mode="live",
            resource_group=resource_group,
            web_app_name=web_app_name,
            foundry_account_name=foundry_account_name,
            foundry_project_name=foundry_project_name,
        ),
        runner=runner,
    )
    exact_present = _verification_proves_exact_assignment(verified)
    exact_missing = bool(
        not getattr(verified, "ok", True)
        and getattr(verified, "category", None) == "assignment_missing"
        and getattr(verified, "web_app_identity_present", False)
        and getattr(verified, "foundry_project_scope_resolved", False)
        and not getattr(verified, "consumer_assignment_present", False)
        and getattr(verified, "matching_assignment_count", None) == 0
    )
    identity_values = (
        getattr(verified, "subscription_id", None),
        getattr(verified, "foundry_project_resource_id", None),
        getattr(verified, "principal_id", None),
        getattr(verified, "role_definition_id", None),
    )
    if (
        not (exact_present or exact_missing)
        or not all(isinstance(value, str) and value for value in identity_values)
    ):
        category = getattr(verified, "category", None)
        return (
            None,
            category if isinstance(category, str) else "preverification_failed",
        )
    subscription_id, project_resource_id, principal_id, role_definition_id = (
        identity_values
    )
    assert isinstance(subscription_id, str)
    assert isinstance(project_resource_id, str)
    assert isinstance(principal_id, str)
    assert isinstance(role_definition_id, str)
    from src.app.services.foundry_agent_consumer_rbac_deployment import (
        deterministic_role_assignment_name,
    )

    return (
        FoundryAgentConsumerRbacDeploymentEvidence(
            subscription_id=subscription_id,
            foundry_project_resource_id=project_resource_id,
            web_app_principal_id=principal_id,
            role_definition_id=role_definition_id,
            role_assignment_name=deterministic_role_assignment_name(
                project_resource_id,
                principal_id,
                role_definition_id,
            ),
            deployment_name=DEPLOYMENT_NAME,
        ),
        "assignment_present" if exact_present else "assignment_missing",
    )


def _handoff_binding(receipt: object) -> tuple[object, ...]:
    return tuple(
        getattr(receipt, field, None)
        for field in (
            "requested_foundry_account_name",
            "foundry_account_name",
            "foundry_account_name_generated",
            "resource_group",
            "foundry_project_name",
            "web_app_name",
        )
    )


def _bicep_contract_snapshot() -> tuple[bytes, bytes] | None:
    from src.app.services.foundry_agent_consumer_rbac_deployment import (
        EXPECTED_MODULE,
    )

    try:
        return EXPECTED_TEMPLATE.read_bytes(), EXPECTED_MODULE.read_bytes()
    except OSError:
        return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    mode = "check" if args.check else "what-if" if args.what_if else "live"
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
    except ConfigValidationError:
        result_payload = _safe_failure("invalid_configuration", mode)
        _emit_json(result_payload)
        return 2
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    if receipt is None:
        result_payload = _safe_failure("rbac_handoff_invalid", mode)
        _emit_json(result_payload)
        return 2
    evidence = None
    assignment_state = None
    runner = None
    if mode != "check":
        runner = _create_azure_cli_runner()
        if not _account_matches_handoff(
            runner,
            resource_group=receipt.resource_group,
            foundry_account_name=receipt.foundry_account_name,
        ):
            result_payload = _safe_failure(
                "rbac_handoff_account_mismatch",
                mode,
                azure_operation_attempted=True,
            )
            _emit_json(result_payload)
            return 2
        local_contract_request = FoundryAgentConsumerRbacDeploymentRequest(
            mode="check",
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
            foundry_account_name=receipt.foundry_account_name,
            foundry_project_name=receipt.foundry_project_name,
            template_file=EXPECTED_TEMPLATE,
        )
        local_contract_invalid = validate_foundry_agent_consumer_rbac_request(
            local_contract_request
        )
        if local_contract_invalid is not None:
            _emit_json(
                _safe_failure(
                    getattr(
                        local_contract_invalid,
                        "category",
                        "template_contract_invalid",
                    ),
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        evidence, assignment_state = _fresh_evidence(
            runner,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
            foundry_account_name=receipt.foundry_account_name,
            foundry_project_name=receipt.foundry_project_name,
        )
        if (
            evidence is None
            or assignment_state
            not in {"assignment_present", "assignment_missing"}
        ):
            result_payload = _safe_failure(
                "consumer_rbac_preverification_failed",
                mode,
                azure_operation_attempted=True,
                rbac_handoff_validated=True,
            )
            _emit_json(result_payload)
            return 2
    request = _request(
        args,
        resource_group=receipt.resource_group,
        web_app_name=receipt.web_app_name,
        foundry_account_name=receipt.foundry_account_name,
        foundry_project_name=receipt.foundry_project_name,
        evidence=evidence,
    )
    invalid = validate_foundry_agent_consumer_rbac_request(request)
    if invalid is not None:
        if mode == "check":
            result = invalid
        else:
            _emit_json(
                _safe_failure(
                    getattr(invalid, "category", "template_contract_invalid"),
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
    elif mode == "check":
        result = deploy_foundry_agent_consumer_rbac(request)
    if mode == "live":
        assert runner is not None
        assert evidence is not None
        if assignment_state == "assignment_present":
            result_payload = {
                "ok": True,
                "category": "success",
                "operation": "deploy_foundry_agent_consumer_rbac",
                "mode": mode,
                "rbac_handoff_validated": True,
                "assignment_reused": True,
                "assignment_verified": True,
                "azure_operation_attempted": True,
                "azure_mutation_made": False,
                "deployment_request_accepted": False,
            }
            _emit_json(result_payload)
            return 0
        if assignment_state != "assignment_missing":
            _emit_json(
                _safe_failure(
                    "consumer_rbac_preverification_failed",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        approved_handoff = _handoff_binding(receipt)
        approved_contract = _bicep_contract_snapshot()
        if approved_contract is None:
            _emit_json(
                _safe_failure(
                    "template_contract_invalid",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        if not prompt_for_rbac_approval():
            _emit_json(
                _safe_failure(
                    "consumer_rbac_operator_declined",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        fresh_receipt = load_matching_daily_azure_readiness_receipt(
            args.readiness_receipt,
            config,
        )
        if (
            fresh_receipt is None
            or _handoff_binding(fresh_receipt) != approved_handoff
            or _bicep_contract_snapshot() != approved_contract
        ):
            _emit_json(
                _safe_failure(
                    "approval_evidence_stale",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        if not _account_matches_handoff(
            runner,
            resource_group=receipt.resource_group,
            foundry_account_name=receipt.foundry_account_name,
        ):
            _emit_json(
                _safe_failure(
                    "approval_evidence_stale",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        fresh_evidence, fresh_assignment_state = _fresh_evidence(
            runner,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
            foundry_account_name=receipt.foundry_account_name,
            foundry_project_name=receipt.foundry_project_name,
        )
        fresh_request = _request(
            args,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
            foundry_account_name=receipt.foundry_account_name,
            foundry_project_name=receipt.foundry_project_name,
            evidence=fresh_evidence,
        )
        if (
            fresh_assignment_state != "assignment_missing"
            or fresh_evidence != evidence
            or fresh_request != request
            or validate_foundry_agent_consumer_rbac_request(fresh_request)
            is not None
        ):
            _emit_json(
                _safe_failure(
                    "approval_evidence_stale",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        result = deploy_foundry_agent_consumer_rbac(
            fresh_request,
            runner=runner,
        )
        accepted = bool(
            getattr(result, "ok", False)
            and getattr(result, "deployment_request_accepted", False)
        )
        if not accepted:
            _emit_json(
                _safe_failure(
                    getattr(result, "category", "deployment_failed"),
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                    azure_mutation_made=None,
                    deployment_request_accepted=bool(
                        getattr(
                            result,
                            "deployment_request_accepted",
                            False,
                        )
                    ),
                )
            )
            return 2
        verified = verify_foundry_agent_consumer_rbac(
            FoundryAgentConsumerRbacVerificationRequest(
                mode="live",
                resource_group=receipt.resource_group,
                web_app_name=receipt.web_app_name,
                foundry_account_name=receipt.foundry_account_name,
                foundry_project_name=receipt.foundry_project_name,
            ),
            runner=runner,
        )
        if not _verification_proves_exact_assignment(verified):
            _emit_json(
                _safe_failure(
                    "consumer_rbac_verification_failed",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                    azure_mutation_made=True,
                    deployment_request_accepted=True,
                )
            )
            return 2
        _emit_json(
            {
                "ok": True,
                "category": "success",
                "operation": "deploy_foundry_agent_consumer_rbac",
                "mode": mode,
                "rbac_handoff_validated": True,
                "assignment_reused": False,
                "assignment_verified": True,
                "azure_operation_attempted": True,
                "azure_mutation_made": True,
                "deployment_request_accepted": True,
            }
        )
        return 0

    if mode == "what-if":
        assert runner is not None
        result = deploy_foundry_agent_consumer_rbac(request, runner=runner)

    result_payload = result.to_json_dict()
    result_payload.update(
        {
            "rbac_handoff_validated": True,
        }
    )
    if args.json:
        _emit_json(result_payload)
    else:
        print(result.message)
        if result.ok and result.mode == "what-if":
            print(
                f"Creates: {result.create_count}, modifies: {result.modify_count}, "
                f"deletes: {result.delete_count}, unchanged: {result.no_change_count}, "
                f"ignored: {result.ignore_count}, deploy-uncertain: {result.deploy_count}, "
                f"unsupported: {result.unsupported_count}."
            )
            if result.manual_review_required:
                print(
                    "Manual review is required for Delete, Deploy, or Unsupported "
                    "preview entries; no deployment ran."
                )
    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
