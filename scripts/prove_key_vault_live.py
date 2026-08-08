import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.daily_azure_environment_rebuild import (
    READINESS_RECEIPT_FILE,
    ConfigValidationError,
    load_daily_azure_config,
    load_matching_daily_azure_readiness_receipt,
)
from src.app.services.key_vault_live_proof import (
    KEY_VAULT_READER_ROLE_GUID,
    KEY_VAULT_SECRETS_USER_ROLE_GUID,
    READER_RBAC_TEMPLATE,
    RBAC_TEMPLATE,
    VAULT_TEMPLATE,
    AzureCliRunner,
    CommandResult,
    KeyVaultDeploymentEvidence,
    KeyVaultDeploymentRequest,
    KeyVaultRbacDeploymentRequest,
    KeyVaultRbacVerificationRequest,
    KeyVaultReaderApprovalEvidence,
    KeyVaultReaderDeploymentRequest,
    KeyVaultReaderVerificationRequest,
    KeyVaultVerificationRequest,
    OperatorIdentityRequest,
    OneUseApproval,
    deploy_operator_key_vault_reader,
    deploy_key_vault,
    deploy_key_vault_rbac,
    file_digest,
    key_vault_preview_command,
    key_vault_rbac_preview_command,
    key_vault_reader_preview_command,
    local_key_vault_reader_contract_valid,
    local_key_vault_contract_valid,
    private_subscription_id_from_resource_id,
    repository_key_vault_name,
    resolve_current_operator,
    sanitized_preview_safe,
    verify_key_vault,
    verify_key_vault_rbac,
    verify_operator_key_vault_reader,
)


PUBLIC_RESULT_FIELDS = (
    "ok",
    "category",
    "operation",
    "mode",
    "ready_verified",
    "account_verified",
    "vault_contract_valid",
    "azure_operation_attempted",
    "vault_deployment_requested",
    "vault_deployment_accepted",
    "vault_reused",
    "vault_verified",
    "resource_identity_verified",
    "rbac_authorization_enabled",
    "legacy_access_policies_absent",
    "zero_secrets_verified",
    "secret_metadata_count",
    "web_app_identity_verified",
    "operator_reader_contract_valid",
    "operator_identity_verified",
    "operator_assignment_reused",
    "operator_assignment_missing",
    "operator_rbac_deployment_requested",
    "operator_rbac_deployment_accepted",
    "operator_assignment_verified",
    "metadata_verification_attempted",
    "rbac_assignment_reused",
    "rbac_deployment_requested",
    "rbac_deployment_accepted",
    "rbac_assignment_verified",
    "matching_assignment_count",
    "preview_safe",
    "create_count",
    "modify_count",
    "delete_count",
    "no_change_count",
    "ignore_count",
    "deploy_count",
    "unsupported_count",
    "azure_mutation_made",
    "next_step",
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
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _create_runner() -> SubprocessAzureCliRunner:
    return SubprocessAzureCliRunner()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Check, independently verify, or explicitly deploy the frozen Key "
            "Vault infrastructure and exact Secrets User RBAC boundaries."
        )
    )
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--check", action="store_true")
    modes.add_argument("--verify-vault", action="store_true")
    modes.add_argument("--deploy-vault", action="store_true")
    modes.add_argument("--verify-rbac", action="store_true")
    modes.add_argument("--deploy-rbac", action="store_true")
    modes.add_argument("--check-operator-reader", action="store_true")
    modes.add_argument("--verify-operator-reader", action="store_true")
    modes.add_argument("--deploy-operator-reader", action="store_true")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--readiness-receipt",
        type=Path,
        default=ROOT / READINESS_RECEIPT_FILE,
    )
    parser.add_argument("--json", action="store_true", required=True)
    return parser.parse_args(argv)


def _base_payload(operation: str, mode: str) -> dict[str, object]:
    return {
        "ok": False,
        "category": "unexpected_error",
        "operation": operation,
        "mode": mode,
        "ready_verified": False,
        "account_verified": False,
        "vault_contract_valid": False,
        "azure_operation_attempted": False,
        "vault_deployment_requested": False,
        "vault_deployment_accepted": False,
        "vault_reused": False,
        "vault_verified": False,
        "resource_identity_verified": False,
        "rbac_authorization_enabled": False,
        "legacy_access_policies_absent": False,
        "zero_secrets_verified": False,
        "secret_metadata_count": None,
        "web_app_identity_verified": False,
        "operator_reader_contract_valid": False,
        "operator_identity_verified": False,
        "operator_assignment_reused": False,
        "operator_assignment_missing": False,
        "operator_rbac_deployment_requested": False,
        "operator_rbac_deployment_accepted": False,
        "operator_assignment_verified": False,
        "metadata_verification_attempted": False,
        "rbac_assignment_reused": False,
        "rbac_deployment_requested": False,
        "rbac_deployment_accepted": False,
        "rbac_assignment_verified": False,
        "matching_assignment_count": None,
        "preview_safe": False,
        "create_count": None,
        "modify_count": None,
        "delete_count": None,
        "no_change_count": None,
        "ignore_count": None,
        "deploy_count": None,
        "unsupported_count": None,
        "azure_mutation_made": False,
        "next_step": "Stop and review the sanitized category.",
    }


def _emit(payload: dict[str, object]) -> None:
    safe = {field: payload.get(field) for field in PUBLIC_RESULT_FIELDS}
    print(json.dumps(safe, separators=(",", ":"), sort_keys=True))


def _operation(args: argparse.Namespace) -> str:
    if args.check:
        return "check_key_vault_live_contract"
    if args.verify_vault:
        return "verify_key_vault"
    if args.deploy_vault:
        return "deploy_key_vault"
    if args.verify_rbac:
        return "verify_key_vault_rbac"
    if args.check_operator_reader:
        return "check_operator_key_vault_reader"
    if args.verify_operator_reader:
        return "verify_operator_key_vault_reader"
    if args.deploy_operator_reader:
        return "deploy_operator_key_vault_reader"
    return "deploy_key_vault_rbac"


def _receipt_context(args: argparse.Namespace):
    try:
        config = load_daily_azure_config(args.config, repository_root=ROOT)
    except ConfigValidationError:
        return None
    receipt = load_matching_daily_azure_readiness_receipt(
        args.readiness_receipt,
        config,
    )
    if receipt is None or receipt.application_insights_identity is None:
        return None
    subscription_id = private_subscription_id_from_resource_id(
        receipt.application_insights_identity.resource_id
    )
    if subscription_id is None:
        return None
    vault_name = repository_key_vault_name(
        receipt.resource_group,
        config.project_name,
        config.environment_name,
    )
    return config, receipt, subscription_id, vault_name


def _account_matches(runner: AzureCliRunner, subscription_id: str) -> bool:
    outcome = runner.run(
        [
            "az", "account", "show",
            "--query", "{id:id,state:state,isDefault:isDefault}",
            "--output", "json", "--only-show-errors",
        ]
    )
    if outcome.return_code != 0:
        return False
    try:
        payload = json.loads(outcome.stdout)
    except (TypeError, json.JSONDecodeError):
        return False
    return bool(
        isinstance(payload, dict)
        and set(payload) == {"id", "state", "isDefault"}
        and isinstance(payload.get("id"), str)
        and payload["id"].casefold() == subscription_id.casefold()
        and payload.get("state") == "Enabled"
        and payload.get("isDefault") is True
    )


def prompt_for_approval(
    boundary: str,
    *,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> bool:
    source = input_stream or sys.stdin
    destination = output_stream or sys.stderr
    destination.write(
        f"Action: create one repository-owned {boundary} deployment\n"
        "READY evidence current: yes\n"
        "Account and exact resource evidence verified: yes\n"
        "Sanitized preview safe: yes\n"
        "Mutation required: yes\n\n"
        "Proceed? [y/N] "
    )
    destination.flush()
    return source.readline().strip().casefold() in {"y", "yes"}


def _vault_request(config, receipt, subscription_id: str, vault_name: str, mode: str = "live"):
    return KeyVaultVerificationRequest(
        mode=mode,
        subscription_id=subscription_id,
        resource_group=receipt.resource_group,
        vault_name=vault_name,
        repository_root=ROOT,
    )


def _rbac_request(config, receipt, subscription_id: str, vault_name: str, mode: str = "live"):
    return KeyVaultRbacVerificationRequest(
        mode=mode,
        subscription_id=subscription_id,
        resource_group=receipt.resource_group,
        vault_name=vault_name,
        web_app_name=receipt.web_app_name,
        repository_root=ROOT,
    )


def _operator_identity_request(config, subscription_id: str, mode: str = "live"):
    return OperatorIdentityRequest(
        mode=mode,
        subscription_id=subscription_id,
    )


def _reader_request(
    receipt,
    subscription_id: str,
    vault_name: str,
    operator_principal_id: str,
    mode: str = "live",
):
    return KeyVaultReaderVerificationRequest(
        mode=mode,
        subscription_id=subscription_id,
        resource_group=receipt.resource_group,
        vault_name=vault_name,
        operator_principal_id=operator_principal_id,
        repository_root=ROOT,
    )


def _reader_deployment_request(
    receipt,
    subscription_id: str,
    vault_name: str,
    operator_principal_id: str,
):
    return KeyVaultReaderDeploymentRequest(
        mode="live",
        subscription_id=subscription_id,
        resource_group=receipt.resource_group,
        vault_name=vault_name,
        operator_principal_id=operator_principal_id,
        repository_root=ROOT,
    )


def _vault_deployment_request(config, receipt, subscription_id: str, vault_name: str):
    return KeyVaultDeploymentRequest(
        mode="live",
        subscription_id=subscription_id,
        resource_group=receipt.resource_group,
        location=config.location,
        project_name=config.project_name,
        environment_name=config.environment_name,
        vault_name=vault_name,
        web_app_name=receipt.web_app_name,
        repository_root=ROOT,
    )


def _rbac_deployment_request(receipt, subscription_id: str, vault_name: str):
    return KeyVaultRbacDeploymentRequest(
        mode="live",
        subscription_id=subscription_id,
        resource_group=receipt.resource_group,
        vault_name=vault_name,
        web_app_name=receipt.web_app_name,
        repository_root=ROOT,
    )


def _merge_vault(payload: dict[str, object], result) -> None:
    payload.update(
        category=result.category,
        vault_contract_valid=result.vault_contract_valid,
        azure_operation_attempted=result.azure_request_attempted,
        vault_verified=result.vault_verified,
        resource_identity_verified=result.resource_identity_verified,
        rbac_authorization_enabled=result.rbac_authorization_enabled,
        legacy_access_policies_absent=result.legacy_access_policies_absent,
        zero_secrets_verified=result.zero_secrets_verified,
        secret_metadata_count=result.secret_metadata_count,
    )


def _vault_control_plane_verified(result) -> bool:
    return bool(
        result.vault_contract_valid
        and result.resource_identity_verified
        and result.rbac_authorization_enabled
        and result.legacy_access_policies_absent
        and result.category in {"success", "secret_metadata_read_failed"}
    )


def _merge_rbac(payload: dict[str, object], result) -> None:
    payload.update(
        category=result.category,
        azure_operation_attempted=result.azure_request_attempted,
        web_app_identity_verified=result.web_app_identity_verified,
        rbac_assignment_verified=result.assignment_verified,
        matching_assignment_count=result.matching_assignment_count,
    )


def _merge_reader(payload: dict[str, object], result) -> None:
    payload.update(
        category=result.category,
        operator_reader_contract_valid=result.role_contract_valid,
        azure_operation_attempted=result.azure_request_attempted,
        operator_identity_verified=result.operator_identity_verified,
        resource_identity_verified=result.vault_identity_verified,
        operator_assignment_missing=result.assignment_missing_conclusive,
        operator_assignment_verified=result.assignment_verified,
        matching_assignment_count=result.matching_assignment_count,
    )


def _preview(
    runner: AzureCliRunner,
    command: list[str],
    *,
    allowed: set[str],
) -> tuple[bool, dict[str, int]]:
    outcome = runner.run(command)
    if outcome.return_code != 0:
        return False, {}
    return sanitized_preview_safe(outcome.stdout, allowed_resource_types=allowed)


def _reader_preview(
    runner: AzureCliRunner,
    request: KeyVaultReaderDeploymentRequest,
) -> tuple[bool, dict[str, int]]:
    return _preview(
        runner,
        key_vault_reader_preview_command(request),
        allowed={
            "Microsoft.Resources/deployments",
            "Microsoft.Authorization/roleAssignments",
            "Microsoft.KeyVault/vaults",
        },
    )


def _fresh_context_matches(args: argparse.Namespace, original) -> bool:
    current = _receipt_context(args)
    return current is not None and current == original


def _evidence(receipt, subscription_id: str, vault_name: str, rbac_result, template: Path):
    digest = file_digest(ROOT / template)
    if digest is None:
        return None
    role_id = getattr(rbac_result, "role_definition_id", None) or (
        f"/subscriptions/{subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"{KEY_VAULT_SECRETS_USER_ROLE_GUID}"
    )
    principal = getattr(rbac_result, "web_app_principal_id", None)
    vault_id = getattr(rbac_result, "vault_resource_id", None) or (
        f"/subscriptions/{subscription_id}/resourceGroups/{receipt.resource_group}/"
        f"providers/Microsoft.KeyVault/vaults/{vault_name}"
    )
    if not isinstance(principal, str):
        return None
    return KeyVaultDeploymentEvidence(
        subscription_id=subscription_id,
        resource_group=receipt.resource_group,
        vault_name=vault_name,
        web_app_name=receipt.web_app_name,
        role_definition_id=role_id,
        web_app_principal_id=principal,
        vault_resource_id=vault_id,
        template_digest=digest,
        run_epoch=receipt.run_epoch,
    )


def _reader_evidence(
    config,
    receipt,
    subscription_id: str,
    vault_name: str,
    identity,
    reader,
):
    digest = file_digest(ROOT / READER_RBAC_TEMPLATE)
    if (
        digest is None
        or not identity.ok
        or not isinstance(identity.operator_principal_id, str)
        or not isinstance(identity.operator_tenant_id, str)
        or not isinstance(identity.operator_account_name, str)
        or identity.operator_principal_type != "User"
        or not isinstance(reader.vault_resource_id, str)
        or not isinstance(reader.role_definition_id, str)
    ):
        return None
    return KeyVaultReaderApprovalEvidence(
        subscription_id=subscription_id,
        tenant_id=identity.operator_tenant_id,
        resource_group=receipt.resource_group,
        vault_name=vault_name,
        vault_resource_id=reader.vault_resource_id,
        operator_principal_id=identity.operator_principal_id,
        operator_account_name=identity.operator_account_name,
        operator_principal_type=identity.operator_principal_type,
        role_definition_id=reader.role_definition_id,
        template_digest=digest,
        run_epoch=receipt.run_epoch,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    operation = _operation(args)
    mode = "check" if args.check or args.check_operator_reader else "live"
    payload = _base_payload(operation, mode)
    context = _receipt_context(args)
    if context is None:
        payload["category"] = "ready_invalid"
        _emit(payload)
        return 2
    config, receipt, subscription_id, vault_name = context
    payload["ready_verified"] = True

    if args.check_operator_reader:
        identity = resolve_current_operator(
            _operator_identity_request(config, subscription_id, "check")
        )
        contract_valid = local_key_vault_reader_contract_valid(ROOT)
        payload.update(
            ok=identity.ok and contract_valid,
            category=(
                "success"
                if identity.ok and contract_valid
                else "local_contract_invalid"
            ),
            operator_reader_contract_valid=contract_valid,
            next_step="Run explicit live operator Reader verification.",
        )
        _emit(payload)
        return 0 if payload["ok"] else 2

    if args.check:
        vault = verify_key_vault(
            _vault_request(config, receipt, subscription_id, vault_name, "check")
        )
        rbac = verify_key_vault_rbac(
            _rbac_request(config, receipt, subscription_id, vault_name, "check")
        )
        payload.update(
            ok=vault.ok and rbac.ok,
            category="success" if vault.ok and rbac.ok else "local_contract_invalid",
            vault_contract_valid=vault.ok and rbac.ok,
            next_step="Run an explicit read-only live vault verification.",
        )
        _emit(payload)
        return 0 if payload["ok"] else 2

    runner = _create_runner()
    payload["azure_operation_attempted"] = True
    if not _account_matches(runner, subscription_id):
        payload["category"] = "account_mismatch"
        _emit(payload)
        return 2
    payload["account_verified"] = True

    if args.verify_operator_reader or args.deploy_operator_reader:
        identity_request = _operator_identity_request(config, subscription_id)
        identity = resolve_current_operator(identity_request, runner=runner)
        payload.update(
            category=identity.category,
            operator_identity_verified=identity.operator_identity_verified,
            azure_operation_attempted=identity.azure_request_attempted,
        )
        if not identity.ok or not isinstance(identity.operator_principal_id, str):
            _emit(payload)
            return 2
        control_plane_vault = verify_key_vault(
            _vault_request(config, receipt, subscription_id, vault_name),
            runner=runner,
            verify_secret_metadata=False,
        )
        _merge_vault(payload, control_plane_vault)
        if not _vault_control_plane_verified(control_plane_vault):
            payload["category"] = (
                "secrets_present"
                if control_plane_vault.category == "secrets_present"
                else "vault_control_plane_unverified"
            )
            _emit(payload)
            return 2
        reader_request = _reader_request(
            receipt,
            subscription_id,
            vault_name,
            identity.operator_principal_id,
        )
        reader = verify_operator_key_vault_reader(reader_request, runner=runner)
        _merge_reader(payload, reader)
        if args.verify_operator_reader:
            payload["ok"] = reader.ok
            _emit(payload)
            return 0 if reader.ok else 2

        if reader.ok:
            payload.update(
                operator_assignment_reused=True,
                operator_assignment_verified=True,
                metadata_verification_attempted=True,
            )
            vault = verify_key_vault(
                _vault_request(config, receipt, subscription_id, vault_name),
                runner=runner,
            )
            _merge_vault(payload, vault)
            payload["ok"] = vault.ok
            payload["category"] = vault.category
            payload["next_step"] = (
                "Stop before Web App runtime RBAC."
                if vault.ok
                else payload["next_step"]
            )
            _emit(payload)
            return 0 if vault.ok else 2
        if not reader.assignment_missing_conclusive:
            _emit(payload)
            return 2
        evidence = _reader_evidence(
            config,
            receipt,
            subscription_id,
            vault_name,
            identity,
            reader,
        )
        if evidence is None:
            payload["category"] = "operator_reader_evidence_invalid"
            _emit(payload)
            return 2
        deployment_request = _reader_deployment_request(
            receipt,
            subscription_id,
            vault_name,
            identity.operator_principal_id,
        )
        safe, counts = _reader_preview(runner, deployment_request)
        payload.update(
            preview_safe=safe,
            **{f"{key}_count": value for key, value in counts.items()},
        )
        if not safe:
            payload["category"] = "operator_reader_preview_unsafe"
            _emit(payload)
            return 2
        approval = OneUseApproval.bind(evidence)
        if not prompt_for_approval("operator Key Vault Reader RBAC"):
            payload["category"] = "operator_declined"
            _emit(payload)
            return 2
        if not _fresh_context_matches(args, context) or not _account_matches(
            runner, subscription_id
        ):
            payload["category"] = "approval_evidence_stale"
            _emit(payload)
            return 2
        fresh_identity = resolve_current_operator(identity_request, runner=runner)
        if not fresh_identity.ok or not isinstance(
            fresh_identity.operator_principal_id, str
        ):
            payload["category"] = "approval_evidence_stale"
            _emit(payload)
            return 2
        fresh_request = _reader_request(
            receipt,
            subscription_id,
            vault_name,
            fresh_identity.operator_principal_id,
        )
        fresh_reader = verify_operator_key_vault_reader(
            fresh_request, runner=runner
        )
        fresh_control_plane_vault = verify_key_vault(
            _vault_request(config, receipt, subscription_id, vault_name),
            runner=runner,
            verify_secret_metadata=False,
        )
        if not _vault_control_plane_verified(fresh_control_plane_vault):
            payload["category"] = "approval_evidence_stale"
            _emit(payload)
            return 2
        fresh_evidence = _reader_evidence(
            config,
            receipt,
            subscription_id,
            vault_name,
            fresh_identity,
            fresh_reader,
        )
        if (
            not fresh_reader.assignment_missing_conclusive
            or fresh_evidence is None
            or not approval.consume(fresh_evidence)
        ):
            payload["category"] = "approval_evidence_stale"
            _emit(payload)
            return 2
        deployed = deploy_operator_key_vault_reader(
            deployment_request, runner=runner
        )
        payload.update(
            operator_rbac_deployment_requested=deployed.deployment_requested,
            operator_rbac_deployment_accepted=deployed.deployment_request_accepted,
            azure_mutation_made=deployed.azure_mutation_made,
        )
        if not deployed.ok:
            payload["category"] = deployed.category
            _emit(payload)
            return 2
        verified = verify_operator_key_vault_reader(
            reader_request, runner=runner
        )
        _merge_reader(payload, verified)
        if not verified.ok:
            payload["category"] = "operator_reader_postdeployment_verification_failed"
            _emit(payload)
            return 2
        payload.update(
            operator_assignment_verified=True,
            metadata_verification_attempted=True,
        )
        vault = verify_key_vault(
            _vault_request(config, receipt, subscription_id, vault_name),
            runner=runner,
        )
        _merge_vault(payload, vault)
        payload["ok"] = vault.ok
        payload["category"] = vault.category
        payload["next_step"] = (
            "Stop before Web App runtime RBAC."
            if vault.ok
            else payload["next_step"]
        )
        _emit(payload)
        return 0 if vault.ok else 2

    if args.verify_vault:
        vault = verify_key_vault(
            _vault_request(config, receipt, subscription_id, vault_name), runner=runner
        )
        _merge_vault(payload, vault)
        payload["ok"] = vault.ok
        _emit(payload)
        return 0 if vault.ok else 2

    if args.verify_rbac:
        rbac = verify_key_vault_rbac(
            _rbac_request(config, receipt, subscription_id, vault_name), runner=runner
        )
        _merge_rbac(payload, rbac)
        payload["ok"] = rbac.ok
        _emit(payload)
        return 0 if rbac.ok else 2

    if args.deploy_vault:
        vault_request = _vault_request(config, receipt, subscription_id, vault_name)
        vault = verify_key_vault(vault_request, runner=runner)
        _merge_vault(payload, vault)
        if vault.ok:
            payload.update(ok=True, category="success", vault_reused=True, next_step="Proceed to independent exact RBAC verification.")
            _emit(payload)
            return 0
        if not vault.vault_missing_conclusive:
            _emit(payload)
            return 2
        rbac_probe = verify_key_vault_rbac(
            _rbac_request(config, receipt, subscription_id, vault_name), runner=runner
        )
        evidence = _evidence(receipt, subscription_id, vault_name, rbac_probe, VAULT_TEMPLATE)
        if evidence is None:
            payload["category"] = "web_app_identity_unverified"
            _emit(payload)
            return 2
        deployment_request = _vault_deployment_request(config, receipt, subscription_id, vault_name)
        safe, counts = _preview(
            runner,
            key_vault_preview_command(deployment_request),
            allowed={"Microsoft.KeyVault/vaults"},
        )
        payload.update(preview_safe=safe, **{f"{key}_count": value for key, value in counts.items()})
        if not safe:
            payload["category"] = "vault_preview_unsafe"
            _emit(payload)
            return 2
        approval = OneUseApproval.bind(evidence)
        if not prompt_for_approval("Key Vault infrastructure"):
            payload["category"] = "operator_declined"
            _emit(payload)
            return 2
        if not _fresh_context_matches(args, context) or not _account_matches(runner, subscription_id):
            payload["category"] = "approval_evidence_stale"
            _emit(payload)
            return 2
        fresh_vault = verify_key_vault(vault_request, runner=runner)
        fresh_rbac_probe = verify_key_vault_rbac(
            _rbac_request(config, receipt, subscription_id, vault_name), runner=runner
        )
        fresh_evidence = _evidence(receipt, subscription_id, vault_name, fresh_rbac_probe, VAULT_TEMPLATE)
        if not fresh_vault.vault_missing_conclusive or fresh_evidence is None or not approval.consume(fresh_evidence):
            payload["category"] = "approval_evidence_stale"
            _emit(payload)
            return 2
        deployed = deploy_key_vault(deployment_request, runner=runner)
        payload.update(
            vault_deployment_requested=deployed.deployment_requested,
            vault_deployment_accepted=deployed.deployment_request_accepted,
            azure_mutation_made=deployed.azure_mutation_made,
        )
        if not deployed.ok:
            payload["category"] = deployed.category
            _emit(payload)
            return 2
        verified = verify_key_vault(vault_request, runner=runner)
        _merge_vault(payload, verified)
        payload["ok"] = verified.ok
        payload["category"] = "success" if verified.ok else "vault_postdeployment_verification_failed"
        payload["next_step"] = "Proceed to independent exact RBAC verification." if verified.ok else payload["next_step"]
        _emit(payload)
        return 0 if verified.ok else 2

    rbac_request = _rbac_request(config, receipt, subscription_id, vault_name)
    rbac = verify_key_vault_rbac(rbac_request, runner=runner)
    _merge_rbac(payload, rbac)
    if rbac.ok:
        payload.update(ok=True, category="success", rbac_assignment_reused=True, next_step="Stop before secret retrieval.")
        _emit(payload)
        return 0
    if not rbac.assignment_missing_conclusive:
        _emit(payload)
        return 2
    evidence = _evidence(receipt, subscription_id, vault_name, rbac, RBAC_TEMPLATE)
    if evidence is None:
        payload["category"] = "rbac_evidence_invalid"
        _emit(payload)
        return 2
    deployment_request = _rbac_deployment_request(receipt, subscription_id, vault_name)
    safe, counts = _preview(
        runner,
        key_vault_rbac_preview_command(deployment_request),
        allowed={
            "Microsoft.Resources/deployments",
            "Microsoft.Authorization/roleAssignments",
            "Microsoft.KeyVault/vaults",
            "Microsoft.Web/sites",
        },
    )
    payload.update(preview_safe=safe, **{f"{key}_count": value for key, value in counts.items()})
    if not safe:
        payload["category"] = "rbac_preview_unsafe"
        _emit(payload)
        return 2
    approval = OneUseApproval.bind(evidence)
    if not prompt_for_approval("Key Vault Secrets User RBAC"):
        payload["category"] = "operator_declined"
        _emit(payload)
        return 2
    if not _fresh_context_matches(args, context) or not _account_matches(runner, subscription_id):
        payload["category"] = "approval_evidence_stale"
        _emit(payload)
        return 2
    fresh = verify_key_vault_rbac(rbac_request, runner=runner)
    fresh_evidence = _evidence(receipt, subscription_id, vault_name, fresh, RBAC_TEMPLATE)
    if not fresh.assignment_missing_conclusive or fresh_evidence is None or not approval.consume(fresh_evidence):
        payload["category"] = "approval_evidence_stale"
        _emit(payload)
        return 2
    deployed = deploy_key_vault_rbac(deployment_request, runner=runner)
    payload.update(
        rbac_deployment_requested=deployed.deployment_requested,
        rbac_deployment_accepted=deployed.deployment_request_accepted,
        azure_mutation_made=deployed.azure_mutation_made,
    )
    if not deployed.ok:
        payload["category"] = deployed.category
        _emit(payload)
        return 2
    verified = verify_key_vault_rbac(rbac_request, runner=runner)
    _merge_rbac(payload, verified)
    payload["ok"] = verified.ok
    payload["category"] = "success" if verified.ok else "rbac_postdeployment_verification_failed"
    payload["next_step"] = "Stop before secret retrieval." if verified.ok else payload["next_step"]
    _emit(payload)
    return 0 if verified.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
