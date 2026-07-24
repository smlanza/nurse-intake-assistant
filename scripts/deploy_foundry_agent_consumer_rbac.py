import argparse
from dataclasses import replace
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
        "FOUNDRY AGENT CONSUMER RBAC\n"
        "\n"
        "Coordinator readiness verified: yes\n"
        "Web App system identity verified: yes\n"
        "Foundry project scope verified: yes\n"
        "Existing exact direct assignment: no\n"
        "Assignment required: yes\n"
        "Exact assignment independently proved: yes\n"
        "Other unsupported records: 0\n"
        "Destructive or unrelated changes: no\n"
        "\n"
        "Proceed? [y/N] "
    )
    destination.flush()
    return source.readline().strip().casefold() in {"y", "yes"}


def _preview_proves_exact_assignment(result: object) -> bool:
    topology = getattr(result, "preview_topology", None)
    counts = (
        getattr(result, "create_count", None),
        getattr(result, "modify_count", None),
        getattr(result, "no_change_count", None),
        getattr(result, "delete_count", None),
        getattr(result, "ignore_count", None),
        getattr(result, "deploy_count", None),
        getattr(result, "unsupported_count", None),
    )
    topology_counts = {
        "exact_create": (1, 0, 0, 0, 0, 0, 0),
        "expected_ignore_plus_unsupported": (0, 0, 0, 0, 10, 0, 1),
    }
    expected_counts = topology_counts.get(topology)
    return bool(
        getattr(result, "ok", False)
        and getattr(result, "category", None) == "success"
        and getattr(result, "mode", None) == "what-if"
        and getattr(result, "template_valid", False)
        and getattr(result, "azure_operation_attempted", False)
        and not getattr(result, "deployment_request_accepted", True)
        and getattr(result, "assignment_contents_proved", False) is True
        and expected_counts is not None
        and counts == expected_counts
        and getattr(result, "manual_review_required", None)
        is (topology == "expected_ignore_plus_unsupported")
        and len(getattr(result, "change_evidence", ())) == sum(counts)
    )


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
    if verified.ok and verified.matching_assignment_count == 1:
        return None, "consumer_rbac_assignment_already_present"
    required = (
        verified.category == "assignment_missing",
        verified.web_app_identity_present,
        verified.foundry_project_scope_resolved,
        verified.matching_assignment_count == 0,
        isinstance(verified.subscription_id, str),
        isinstance(verified.foundry_project_resource_id, str),
        isinstance(verified.principal_id, str),
        isinstance(verified.role_definition_id, str),
    )
    if not all(required):
        return None, "rbac_handoff_azure_scope_mismatch"
    assert verified.subscription_id is not None
    assert verified.foundry_project_resource_id is not None
    assert verified.principal_id is not None
    assert verified.role_definition_id is not None
    from src.app.services.foundry_agent_consumer_rbac_deployment import (
        deterministic_role_assignment_name,
    )

    return (
        FoundryAgentConsumerRbacDeploymentEvidence(
            subscription_id=verified.subscription_id,
            foundry_project_resource_id=verified.foundry_project_resource_id,
            web_app_principal_id=verified.principal_id,
            role_definition_id=verified.role_definition_id,
            role_assignment_name=deterministic_role_assignment_name(
                verified.foundry_project_resource_id,
                verified.principal_id,
                verified.role_definition_id,
            ),
            deployment_name=DEPLOYMENT_NAME,
        ),
        None,
    )


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
        evidence, evidence_failure = _fresh_evidence(
            runner,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
            foundry_account_name=receipt.foundry_account_name,
            foundry_project_name=receipt.foundry_project_name,
        )
        if evidence_failure == "consumer_rbac_assignment_already_present":
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
                "requested_foundry_account_name": (
                    receipt.requested_foundry_account_name
                ),
                "foundry_account_name": receipt.foundry_account_name,
            }
            _emit_json(result_payload)
            return 0
        if evidence_failure is not None or evidence is None:
            result_payload = _safe_failure(
                evidence_failure or "rbac_handoff_azure_scope_mismatch",
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
    if mode == "live":
        assert runner is not None
        assert evidence is not None
        preview_request = replace(request, mode="what-if")
        preview_invalid = validate_foundry_agent_consumer_rbac_request(
            preview_request
        )
        preview = (
            preview_invalid
            if preview_invalid is not None
            else deploy_foundry_agent_consumer_rbac(
                preview_request,
                runner=runner,
            )
        )
        if not _preview_proves_exact_assignment(preview):
            _emit_json(
                _safe_failure(
                    "consumer_rbac_preview_unsafe",
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
        fresh_evidence, fresh_failure = _fresh_evidence(
            runner,
            resource_group=receipt.resource_group,
            web_app_name=receipt.web_app_name,
            foundry_account_name=receipt.foundry_account_name,
            foundry_project_name=receipt.foundry_project_name,
        )
        if fresh_failure is not None or fresh_evidence != evidence:
            _emit_json(
                _safe_failure(
                    "approval_evidence_stale",
                    mode,
                    azure_operation_attempted=True,
                    rbac_handoff_validated=True,
                )
            )
            return 2
        live_request = replace(request, approved_evidence=fresh_evidence)
        invalid = validate_foundry_agent_consumer_rbac_request(live_request)
        result = (
            invalid
            if invalid is not None
            else deploy_foundry_agent_consumer_rbac(
                live_request,
                runner=runner,
            )
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
                "requested_foundry_account_name": (
                    receipt.requested_foundry_account_name
                ),
                "foundry_account_name": receipt.foundry_account_name,
            }
        )
        return 0

    invalid = validate_foundry_agent_consumer_rbac_request(request)
    if invalid is not None:
        result = invalid
    elif request.mode == "check":
        result = deploy_foundry_agent_consumer_rbac(request)
    else:
        result = deploy_foundry_agent_consumer_rbac(request, runner=runner)

    result_payload = result.to_json_dict()
    result_payload.update(
        {
            "rbac_handoff_validated": True,
            "requested_foundry_account_name": (
                receipt.requested_foundry_account_name
            ),
            "foundry_account_name": receipt.foundry_account_name,
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
