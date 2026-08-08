from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import secrets
from typing import Protocol
from uuid import UUID

from src.app.services.azure_what_if_evidence import parse_sanitized_what_if


KEY_VAULT_SECRETS_USER_ROLE_GUID = "4633458b-17de-408a-b874-0445c86b69e6"
KEY_VAULT_READER_ROLE_GUID = "21090545-7ca7-4776-b22c-e363652d74d2"
VAULT_DEPLOYMENT_NAME = "nurse-intake-key-vault-infra"
RBAC_DEPLOYMENT_NAME = "nurse-intake-key-vault-secrets-user-rbac"
READER_RBAC_DEPLOYMENT_NAME = "nurse-intake-key-vault-reader-rbac"
VAULT_TEMPLATE = Path("infra/modules/key-vault.bicep")
RBAC_TEMPLATE = Path("infra/key-vault-secrets-user-rbac.bicep")
READER_RBAC_TEMPLATE = Path("infra/key-vault-reader-rbac.bicep")

DAILY_ENVIRONMENT_IGNORED_RESOURCE_TYPES = frozenset(
    {
        "microsoft.alertsmanagement/smartDetectorAlertRules",
        "Microsoft.CognitiveServices/accounts",
        "Microsoft.CognitiveServices/accounts/projects",
        "Microsoft.DocumentDB/databaseAccounts",
        "microsoft.insights/actiongroups",
        "Microsoft.Insights/components",
        "Microsoft.OperationalInsights/workspaces",
        "Microsoft.Storage/storageAccounts",
        "Microsoft.Web/serverFarms",
        "Microsoft.Web/sites",
    }
)

_SAFE_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9_.()\-]*[A-Za-z0-9])?")
_RESOURCE_NAME = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?")
_VAULT_NAME = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_RUN_EPOCH = re.compile(r"[0-9a-f]{32}")


@dataclass(frozen=True)
class CommandResult:
    return_code: int
    stdout: str
    stderr: str


class AzureCliRunner(Protocol):
    def run(self, args: list[str]) -> CommandResult: ...


@dataclass(frozen=True)
class KeyVaultVerificationRequest:
    mode: str
    subscription_id: str = field(repr=False)
    resource_group: str
    vault_name: str
    repository_root: Path


@dataclass(frozen=True)
class KeyVaultVerificationResult:
    ok: bool
    category: str
    operation: str
    mode: str
    vault_contract_valid: bool
    azure_request_attempted: bool
    vault_missing_conclusive: bool
    vault_verified: bool
    resource_identity_verified: bool
    provisioning_succeeded: bool
    rbac_authorization_enabled: bool
    legacy_access_policies_absent: bool
    zero_secrets_verified: bool
    secret_metadata_count: int | None
    recommended_next_step: str
    vault_resource_id: str | None = field(default=None, repr=False)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "vault_contract_valid": self.vault_contract_valid,
            "azure_request_attempted": self.azure_request_attempted,
            "vault_missing_conclusive": self.vault_missing_conclusive,
            "vault_verified": self.vault_verified,
            "resource_identity_verified": self.resource_identity_verified,
            "provisioning_succeeded": self.provisioning_succeeded,
            "rbac_authorization_enabled": self.rbac_authorization_enabled,
            "legacy_access_policies_absent": self.legacy_access_policies_absent,
            "zero_secrets_verified": self.zero_secrets_verified,
            "secret_metadata_count": self.secret_metadata_count,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class KeyVaultRbacVerificationRequest:
    mode: str
    subscription_id: str = field(repr=False)
    resource_group: str
    vault_name: str
    web_app_name: str
    repository_root: Path


@dataclass(frozen=True)
class KeyVaultRbacVerificationResult:
    ok: bool
    category: str
    operation: str
    mode: str
    role_contract_valid: bool
    azure_request_attempted: bool
    web_app_identity_verified: bool
    vault_identity_verified: bool
    assignment_missing_conclusive: bool
    assignment_verified: bool
    matching_assignment_count: int | None
    recommended_next_step: str
    subscription_id: str | None = field(default=None, repr=False)
    web_app_principal_id: str | None = field(default=None, repr=False)
    web_app_resource_id: str | None = field(default=None, repr=False)
    vault_resource_id: str | None = field(default=None, repr=False)
    role_definition_id: str | None = field(default=None, repr=False)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "role_contract_valid": self.role_contract_valid,
            "azure_request_attempted": self.azure_request_attempted,
            "web_app_identity_verified": self.web_app_identity_verified,
            "vault_identity_verified": self.vault_identity_verified,
            "assignment_missing_conclusive": self.assignment_missing_conclusive,
            "assignment_verified": self.assignment_verified,
            "matching_assignment_count": self.matching_assignment_count,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class OperatorIdentityRequest:
    mode: str
    subscription_id: str = field(repr=False)
    tenant_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class OperatorIdentityVerificationResult:
    ok: bool
    category: str
    operation: str
    mode: str
    azure_request_attempted: bool
    operator_identity_verified: bool
    recommended_next_step: str
    operator_tenant_id: str | None = field(default=None, repr=False)
    operator_principal_id: str | None = field(default=None, repr=False)
    operator_account_name: str | None = field(default=None, repr=False)
    operator_principal_type: str | None = field(default=None, repr=False)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "azure_request_attempted": self.azure_request_attempted,
            "operator_identity_verified": self.operator_identity_verified,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class KeyVaultReaderVerificationRequest:
    mode: str
    subscription_id: str = field(repr=False)
    resource_group: str
    vault_name: str
    operator_principal_id: str = field(repr=False)
    repository_root: Path


@dataclass(frozen=True)
class KeyVaultReaderVerificationResult:
    ok: bool
    category: str
    operation: str
    mode: str
    role_contract_valid: bool
    azure_request_attempted: bool
    vault_identity_verified: bool
    operator_identity_verified: bool
    assignment_missing_conclusive: bool
    assignment_verified: bool
    matching_assignment_count: int | None
    recommended_next_step: str
    vault_resource_id: str | None = field(default=None, repr=False)
    role_definition_id: str | None = field(default=None, repr=False)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "role_contract_valid": self.role_contract_valid,
            "azure_request_attempted": self.azure_request_attempted,
            "vault_identity_verified": self.vault_identity_verified,
            "operator_identity_verified": self.operator_identity_verified,
            "assignment_missing_conclusive": self.assignment_missing_conclusive,
            "assignment_verified": self.assignment_verified,
            "matching_assignment_count": self.matching_assignment_count,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class KeyVaultReaderDeploymentRequest:
    mode: str
    subscription_id: str = field(repr=False)
    resource_group: str
    vault_name: str
    operator_principal_id: str = field(repr=False)
    repository_root: Path


@dataclass(frozen=True)
class OperatorZeroSecretProofResult:
    ok: bool
    category: str
    operation: str
    mode: str
    operator_assignment_verified: bool
    metadata_verification_attempted: bool
    zero_secrets_verified: bool
    secret_metadata_count: int | None
    recommended_next_step: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "operator_assignment_verified": self.operator_assignment_verified,
            "metadata_verification_attempted": self.metadata_verification_attempted,
            "zero_secrets_verified": self.zero_secrets_verified,
            "secret_metadata_count": self.secret_metadata_count,
            "recommended_next_step": self.recommended_next_step,
        }


@dataclass(frozen=True)
class KeyVaultDeploymentRequest:
    mode: str
    subscription_id: str = field(repr=False)
    resource_group: str
    location: str
    project_name: str
    environment_name: str
    vault_name: str
    web_app_name: str
    repository_root: Path


@dataclass(frozen=True)
class KeyVaultRbacDeploymentRequest:
    mode: str
    subscription_id: str = field(repr=False)
    resource_group: str
    vault_name: str
    web_app_name: str
    repository_root: Path


@dataclass(frozen=True)
class KeyVaultDeploymentResult:
    ok: bool
    category: str
    operation: str
    mode: str
    local_contract_valid: bool
    azure_operation_attempted: bool
    deployment_requested: bool
    deployment_request_accepted: bool
    azure_mutation_made: bool | None
    vault_verified: bool = False
    assignment_verified: bool = False

    def to_json_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "category": self.category,
            "operation": self.operation,
            "mode": self.mode,
            "local_contract_valid": self.local_contract_valid,
            "azure_operation_attempted": self.azure_operation_attempted,
            "deployment_requested": self.deployment_requested,
            "deployment_request_accepted": self.deployment_request_accepted,
            "azure_mutation_made": self.azure_mutation_made,
            "vault_verified": self.vault_verified,
            "assignment_verified": self.assignment_verified,
        }


@dataclass(frozen=True, repr=False)
class KeyVaultDeploymentEvidence:
    subscription_id: str
    resource_group: str
    vault_name: str
    web_app_name: str
    role_definition_id: str
    web_app_principal_id: str
    vault_resource_id: str
    template_digest: str
    run_epoch: str

    def binding(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "subscription_id": self.subscription_id.casefold(),
                    "resource_group": self.resource_group.casefold(),
                    "vault_name": self.vault_name.casefold(),
                    "web_app_name": self.web_app_name.casefold(),
                    "role_definition_id": self.role_definition_id.casefold(),
                    "web_app_principal_id": self.web_app_principal_id.casefold(),
                    "vault_resource_id": self.vault_resource_id.casefold(),
                    "template_digest": self.template_digest,
                    "run_epoch": self.run_epoch,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()


@dataclass(frozen=True, repr=False)
class KeyVaultReaderApprovalEvidence:
    subscription_id: str
    tenant_id: str
    resource_group: str
    vault_name: str
    vault_resource_id: str
    operator_principal_id: str
    operator_account_name: str
    operator_principal_type: str
    role_definition_id: str
    template_digest: str
    run_epoch: str

    def binding(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {
                    "subscription_id": self.subscription_id.casefold(),
                    "tenant_id": self.tenant_id.casefold(),
                    "resource_group": self.resource_group.casefold(),
                    "vault_name": self.vault_name.casefold(),
                    "vault_resource_id": self.vault_resource_id.casefold(),
                    "operator_principal_id": self.operator_principal_id.casefold(),
                    "operator_account_name": self.operator_account_name.casefold(),
                    "operator_principal_type": self.operator_principal_type,
                    "role_definition_id": self.role_definition_id.casefold(),
                    "template_digest": self.template_digest,
                    "run_epoch": self.run_epoch,
                },
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        ).hexdigest()


@dataclass
class OneUseApproval:
    _binding: str = field(repr=False)
    _consumed: bool = field(default=False, repr=False)

    @classmethod
    def bind(cls, evidence: KeyVaultDeploymentEvidence) -> OneUseApproval:
        return cls(evidence.binding())

    def consume(self, evidence: KeyVaultDeploymentEvidence) -> bool:
        if self._consumed or not secrets.compare_digest(
            self._binding, evidence.binding()
        ):
            return False
        self._consumed = True
        return True


def repository_resource_name_suffix(
    resource_group: str, project_name: str, environment_name: str
) -> str:
    identity = "\x00".join(
        (resource_group.casefold(), project_name.casefold(), environment_name.casefold())
    ).encode()
    return hashlib.sha256(identity).hexdigest()[:13]


def repository_key_vault_name(
    resource_group: str, project_name: str, environment_name: str
) -> str:
    return f"kv{repository_resource_name_suffix(resource_group, project_name, environment_name)}"


def private_subscription_id_from_resource_id(resource_id: str) -> str | None:
    parts = resource_id.split("/")
    if len(parts) < 3 or parts[0] != "" or parts[1].casefold() != "subscriptions":
        return None
    return _canonical_uuid(parts[2])


def local_key_vault_contract_valid(repository_root: Path) -> bool:
    try:
        vault = (repository_root / VAULT_TEMPLATE).read_text()
        entry = (repository_root / RBAC_TEMPLATE).read_text()
        rbac = (
            repository_root / "infra/modules/key-vault-secrets-user-rbac.bicep"
        ).read_text()
    except OSError:
        return False
    return all(
        (
            "Microsoft.KeyVault/vaults@2023-07-01" in vault,
            "enableRbacAuthorization: true" in vault,
            "accessPolicies" not in vault,
            "Microsoft.KeyVault/vaults/secrets" not in vault,
            "output keyVaultName string = keyVault.name" in vault,
            "webAppPrincipalId: webApp.identity.principalId" in entry,
            "modules/key-vault-secrets-user-rbac.bicep" in entry,
            KEY_VAULT_SECRETS_USER_ROLE_GUID in rbac,
            "scope: keyVault" in rbac,
            "principalType: 'ServicePrincipal'" in rbac,
            "newGuid(" not in rbac,
        )
    )


def local_key_vault_reader_contract_valid(repository_root: Path) -> bool:
    try:
        entry = (repository_root / READER_RBAC_TEMPLATE).read_text()
        module = (
            repository_root / "infra/modules/key-vault-reader-rbac.bicep"
        ).read_text()
    except OSError:
        return False
    combined = entry + module
    return all(
        (
            "modules/key-vault-reader-rbac.bicep" in entry,
            "Microsoft.KeyVault/vaults@2023-07-01" in module,
            "existing =" in module,
            KEY_VAULT_READER_ROLE_GUID in module,
            "scope: keyVault" in module,
            "principalId: operatorPrincipalId" in module,
            "principalType: 'User'" in module,
            "newGuid(" not in combined,
            "Microsoft.KeyVault/vaults/secrets" not in combined,
            "Microsoft.Web/sites" not in combined,
            KEY_VAULT_SECRETS_USER_ROLE_GUID not in combined,
        )
    )


def verify_key_vault(
    request: KeyVaultVerificationRequest,
    *,
    runner: AzureCliRunner | None = None,
    verify_secret_metadata: bool = True,
) -> KeyVaultVerificationResult:
    valid = _verification_request_valid(request) and local_key_vault_contract_valid(
        request.repository_root
    )
    if not valid:
        return _vault_result(request, "local_contract_invalid")
    if request.mode == "check":
        return _vault_result(request, "success", ok=True, vault_contract_valid=True)
    if runner is None:
        return _vault_result(
            request, "unexpected_error", vault_contract_valid=True
        )
    payload, failure = _read_json(
        runner,
        [
            "az", "keyvault", "show",
            "--resource-group", request.resource_group,
            "--name", request.vault_name,
            "--query",
            "{name:name,id:id,type:type,provisioningState:properties.provisioningState,enableRbacAuthorization:properties.enableRbacAuthorization,accessPolicyCount:length(properties.accessPolicies)}",
            "--output", "json", "--only-show-errors",
        ],
        missing="vault_missing",
    )
    common = {"vault_contract_valid": True, "azure_request_attempted": True}
    if failure:
        return _vault_result(
            request,
            failure,
            vault_missing_conclusive=failure == "vault_missing",
            **common,
        )
    expected_keys = {
        "name", "id", "type", "provisioningState",
        "enableRbacAuthorization", "accessPolicyCount",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return _vault_result(request, "response_parse_failed", **common)
    resource_id = payload.get("id")
    if not _exact_resource_id(
        resource_id,
        request.subscription_id,
        request.resource_group,
        "Microsoft.KeyVault/vaults",
        request.vault_name,
    ) or payload.get("name") != request.vault_name or str(payload.get("type", "")).casefold() != "microsoft.keyvault/vaults":
        return _vault_result(request, "vault_identity_mismatch", **common)
    identity = {**common, "resource_identity_verified": True, "vault_resource_id": resource_id}
    if payload.get("provisioningState") != "Succeeded":
        return _vault_result(request, "vault_provisioning_failed", **identity)
    provisioned = {**identity, "provisioning_succeeded": True}
    if payload.get("enableRbacAuthorization") is not True:
        return _vault_result(request, "rbac_authorization_disabled", **provisioned)
    authorized = {**provisioned, "rbac_authorization_enabled": True}
    if type(payload.get("accessPolicyCount")) is not int:
        return _vault_result(request, "response_parse_failed", **authorized)
    if payload["accessPolicyCount"] != 0:
        return _vault_result(request, "legacy_access_policy_present", **authorized)
    policies = {**authorized, "legacy_access_policies_absent": True}
    if not verify_secret_metadata:
        return _vault_result(
            request,
            "success",
            ok=True,
            recommended_next_step="Proceed to exact operator Reader preflight.",
            **policies,
        )
    count, failure = _read_json(
        runner,
        [
            "az", "keyvault", "secret", "list",
            "--vault-name", request.vault_name,
            "--maxresults", "1",
            "--query", "length(@)",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _vault_result(request, "secret_metadata_read_failed", **policies)
    if type(count) is not int or count < 0:
        return _vault_result(request, "secret_metadata_parse_failed", **policies)
    counted = {**policies, "secret_metadata_count": count}
    if count != 0:
        return _vault_result(request, "secrets_present", **counted)
    return _vault_result(
        request,
        "success",
        ok=True,
        vault_verified=True,
        zero_secrets_verified=True,
        **counted,
    )


def verify_key_vault_rbac(
    request: KeyVaultRbacVerificationRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> KeyVaultRbacVerificationResult:
    valid = _rbac_verification_request_valid(request) and local_key_vault_contract_valid(
        request.repository_root
    )
    if not valid:
        return _rbac_result(request, "local_contract_invalid")
    if request.mode == "check":
        return _rbac_result(request, "success", ok=True, role_contract_valid=True)
    if runner is None:
        return _rbac_result(request, "unexpected_error", role_contract_valid=True)
    common: dict[str, object] = {
        "role_contract_valid": True,
        "azure_request_attempted": True,
        "subscription_id": request.subscription_id,
    }
    identity, failure = _read_json(
        runner,
        [
            "az", "webapp", "show",
            "--resource-group", request.resource_group,
            "--name", request.web_app_name,
            "--query", "{principalId:identity.principalId,type:identity.type,webAppId:id}",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _rbac_result(request, "web_app_identity_missing", **common)
    if not isinstance(identity, dict) or set(identity) != {"principalId", "type", "webAppId"}:
        return _rbac_result(request, "response_parse_failed", **common)
    principal = _canonical_uuid(identity.get("principalId"))
    web_app_id = identity.get("webAppId")
    if identity.get("type") != "SystemAssigned" or principal is None:
        return _rbac_result(request, "web_app_identity_missing", **common)
    if not _exact_resource_id(
        web_app_id,
        request.subscription_id,
        request.resource_group,
        "Microsoft.Web/sites",
        request.web_app_name,
    ):
        return _rbac_result(request, "response_parse_failed", **common)
    common.update(
        web_app_identity_verified=True,
        web_app_principal_id=principal,
        web_app_resource_id=web_app_id,
    )
    vault, failure = _read_json(
        runner,
        [
            "az", "keyvault", "show",
            "--resource-group", request.resource_group,
            "--name", request.vault_name,
            "--query", "{name:name,id:id,type:type}",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _rbac_result(request, "vault_missing", **common)
    if not isinstance(vault, dict) or set(vault) != {"name", "id", "type"}:
        return _rbac_result(request, "response_parse_failed", **common)
    vault_id = vault.get("id")
    if vault.get("name") != request.vault_name or str(vault.get("type", "")).casefold() != "microsoft.keyvault/vaults" or not _exact_resource_id(
        vault_id,
        request.subscription_id,
        request.resource_group,
        "Microsoft.KeyVault/vaults",
        request.vault_name,
    ):
        return _rbac_result(request, "vault_identity_mismatch", **common)
    role_id = (
        f"/subscriptions/{request.subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"{KEY_VAULT_SECRETS_USER_ROLE_GUID}"
    )
    common.update(
        vault_identity_verified=True,
        vault_resource_id=vault_id,
        role_definition_id=role_id,
    )
    assignments, failure = _read_json(
        runner,
        [
            "az", "role", "assignment", "list",
            "--assignee-object-id", principal,
            "--scope", str(vault_id),
            "--include-inherited",
            "--query", "[].{principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _rbac_result(request, "assignment_read_failed", **common)
    if not isinstance(assignments, list) or any(
        not isinstance(item, dict)
        or set(item) != {"principalId", "roleDefinitionId", "scope"}
        or not all(isinstance(value, str) and value for value in item.values())
        for item in assignments
    ):
        return _rbac_result(request, "response_parse_failed", **common)
    exact = [
        item for item in assignments
        if item["principalId"].casefold() == principal.casefold()
        and item["roleDefinitionId"].casefold() == role_id.casefold()
        and item["scope"].casefold() == str(vault_id).casefold()
    ]
    common["matching_assignment_count"] = len(exact)
    if len(exact) > 1:
        return _rbac_result(request, "assignment_ambiguous", **common)
    if len(exact) == 1:
        return _rbac_result(
            request, "success", ok=True, assignment_verified=True, **common
        )
    if not assignments:
        return _rbac_result(
            request,
            "assignment_missing",
            assignment_missing_conclusive=True,
            **common,
        )
    if any(item["principalId"].casefold() != principal.casefold() for item in assignments):
        return _rbac_result(request, "principal_mismatch", **common)
    if any(item["scope"].casefold() != str(vault_id).casefold() for item in assignments):
        return _rbac_result(request, "assignment_scope_mismatch", **common)
    return _rbac_result(request, "role_mismatch", **common)


def resolve_current_operator(
    request: OperatorIdentityRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> OperatorIdentityVerificationResult:
    valid = bool(
        request.mode in {"check", "live"}
        and _canonical_uuid(request.subscription_id) is not None
        and (
            request.tenant_id is None
            or _canonical_uuid(request.tenant_id) is not None
        )
    )
    if not valid:
        return _operator_identity_result(request, "local_contract_invalid")
    if request.mode == "check":
        return _operator_identity_result(request, "success", ok=True)
    if runner is None:
        return _operator_identity_result(request, "unexpected_error")
    common = {"azure_request_attempted": True}
    account, failure = _read_json(
        runner,
        [
            "az", "account", "show",
            "--query", "{id:id,tenantId:tenantId,name:user.name,type:user.type}",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _operator_identity_result(request, "account_read_failed", **common)
    if not isinstance(account, dict) or set(account) != {"id", "tenantId", "name", "type"}:
        return _operator_identity_result(request, "response_parse_failed", **common)
    if (
        not isinstance(account.get("id"), str)
        or account["id"].casefold() != request.subscription_id.casefold()
        or _canonical_uuid(account.get("tenantId")) is None
        or (
            request.tenant_id is not None
            and account["tenantId"].casefold() != request.tenant_id.casefold()
        )
    ):
        return _operator_identity_result(request, "account_mismatch", **common)
    if account.get("type") != "user":
        return _operator_identity_result(
            request, "operator_identity_unsupported", **common
        )
    account_name = account.get("name")
    if not isinstance(account_name, str) or not account_name or len(account_name) > 320:
        return _operator_identity_result(request, "response_parse_failed", **common)
    signed_in, failure = _read_json(
        runner,
        [
            "az", "ad", "signed-in-user", "show",
            "--query", "{id:id}",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _operator_identity_result(request, "operator_identity_read_failed", **common)
    if not isinstance(signed_in, dict) or set(signed_in) != {"id"}:
        return _operator_identity_result(request, "response_parse_failed", **common)
    principal = _canonical_uuid(signed_in.get("id"))
    if principal is None:
        return _operator_identity_result(request, "operator_identity_mismatch", **common)
    return _operator_identity_result(
        request,
        "success",
        ok=True,
        operator_identity_verified=True,
        operator_tenant_id=str(account["tenantId"]),
        operator_principal_id=principal,
        operator_account_name=account_name,
        operator_principal_type="User",
        **common,
    )


def verify_operator_key_vault_reader(
    request: KeyVaultReaderVerificationRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> KeyVaultReaderVerificationResult:
    valid = bool(
        request.mode in {"check", "live"}
        and _canonical_uuid(request.subscription_id) is not None
        and _safe_group(request.resource_group)
        and _safe_vault(request.vault_name)
        and _canonical_uuid(request.operator_principal_id) is not None
        and local_key_vault_reader_contract_valid(request.repository_root)
    )
    if not valid:
        return _reader_result(request, "local_contract_invalid")
    if request.mode == "check":
        return _reader_result(request, "success", ok=True, role_contract_valid=True)
    if runner is None:
        return _reader_result(request, "unexpected_error", role_contract_valid=True)
    common: dict[str, object] = {
        "role_contract_valid": True,
        "azure_request_attempted": True,
        "operator_identity_verified": True,
    }
    vault, failure = _read_json(
        runner,
        [
            "az", "keyvault", "show",
            "--resource-group", request.resource_group,
            "--name", request.vault_name,
            "--query", "{name:name,id:id,type:type}",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _reader_result(request, "vault_missing", **common)
    if not isinstance(vault, dict) or set(vault) != {"name", "id", "type"}:
        return _reader_result(request, "response_parse_failed", **common)
    vault_id = vault.get("id")
    if (
        vault.get("name") != request.vault_name
        or str(vault.get("type", "")).casefold() != "microsoft.keyvault/vaults"
        or not _exact_resource_id(
            vault_id,
            request.subscription_id,
            request.resource_group,
            "Microsoft.KeyVault/vaults",
            request.vault_name,
        )
    ):
        return _reader_result(request, "vault_identity_mismatch", **common)
    role_id = (
        f"/subscriptions/{request.subscription_id}/providers/"
        "Microsoft.Authorization/roleDefinitions/"
        f"{KEY_VAULT_READER_ROLE_GUID}"
    )
    common.update(
        vault_identity_verified=True,
        vault_resource_id=vault_id,
        role_definition_id=role_id,
    )
    assignments, failure = _read_json(
        runner,
        [
            "az", "role", "assignment", "list",
            "--assignee-object-id", request.operator_principal_id,
            "--scope", str(vault_id),
            "--include-inherited",
            "--query", "[].{principalId:principalId,roleDefinitionId:roleDefinitionId,scope:scope}",
            "--output", "json", "--only-show-errors",
        ],
    )
    if failure:
        return _reader_result(request, "assignment_read_failed", **common)
    if not isinstance(assignments, list) or any(
        not isinstance(item, dict)
        or set(item) != {"principalId", "roleDefinitionId", "scope"}
        or not all(isinstance(value, str) and value for value in item.values())
        for item in assignments
    ):
        return _reader_result(request, "response_parse_failed", **common)
    exact = [
        item
        for item in assignments
        if item["principalId"].casefold() == request.operator_principal_id.casefold()
        and item["roleDefinitionId"].casefold() == role_id.casefold()
        and item["scope"].casefold() == str(vault_id).casefold()
    ]
    common["matching_assignment_count"] = len(exact)
    if len(exact) > 1:
        return _reader_result(request, "assignment_ambiguous", **common)
    if len(exact) == 1:
        return _reader_result(
            request, "success", ok=True, assignment_verified=True, **common
        )
    if not assignments:
        return _reader_result(
            request,
            "assignment_missing",
            assignment_missing_conclusive=True,
            **common,
        )
    if any(
        item["principalId"].casefold()
        != request.operator_principal_id.casefold()
        for item in assignments
    ):
        return _reader_result(request, "principal_mismatch", **common)
    if any(item["scope"].casefold() != str(vault_id).casefold() for item in assignments):
        return _reader_result(request, "authorization_scope_mismatch", **common)
    return _reader_result(request, "role_mismatch", **common)


def verify_zero_secrets_after_operator_reader(
    reader_request: KeyVaultReaderVerificationRequest,
    vault_request: KeyVaultVerificationRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> OperatorZeroSecretProofResult:
    if runner is None:
        return _zero_secret_proof_result(reader_request.mode, "unexpected_error")
    reader = verify_operator_key_vault_reader(reader_request, runner=runner)
    if not reader.ok:
        return _zero_secret_proof_result(reader_request.mode, reader.category)
    vault = verify_key_vault(vault_request, runner=runner)
    return _zero_secret_proof_result(
        reader_request.mode,
        vault.category,
        ok=vault.ok,
        operator_assignment_verified=True,
        metadata_verification_attempted=True,
        zero_secrets_verified=vault.zero_secrets_verified,
        secret_metadata_count=vault.secret_metadata_count,
        recommended_next_step=(
            "Stop before Web App runtime RBAC."
            if vault.ok
            else vault.recommended_next_step
        ),
    )


def key_vault_deployment_command(request: KeyVaultDeploymentRequest) -> list[str]:
    return [
        "az", "deployment", "group", "create",
        "--resource-group", request.resource_group,
        "--name", VAULT_DEPLOYMENT_NAME,
        "--template-file", str(request.repository_root / VAULT_TEMPLATE),
        "--parameters", f"location={request.location}", f"keyVaultName={request.vault_name}",
        "--output", "none", "--only-show-errors",
    ]


def key_vault_rbac_deployment_command(request: KeyVaultRbacDeploymentRequest) -> list[str]:
    return [
        "az", "deployment", "group", "create",
        "--resource-group", request.resource_group,
        "--name", RBAC_DEPLOYMENT_NAME,
        "--template-file", str(request.repository_root / RBAC_TEMPLATE),
        "--parameters", f"webAppName={request.web_app_name}", f"keyVaultName={request.vault_name}",
        "--output", "none", "--only-show-errors",
    ]


def key_vault_reader_deployment_command(
    request: KeyVaultReaderDeploymentRequest,
) -> list[str]:
    return [
        "az", "deployment", "group", "create",
        "--resource-group", request.resource_group,
        "--name", READER_RBAC_DEPLOYMENT_NAME,
        "--template-file", str(request.repository_root / READER_RBAC_TEMPLATE),
        "--parameters",
        f"keyVaultName={request.vault_name}",
        f"operatorPrincipalId={request.operator_principal_id}",
        "--output", "none", "--only-show-errors",
    ]


def key_vault_preview_command(request: KeyVaultDeploymentRequest) -> list[str]:
    command = key_vault_deployment_command(request)
    command[3] = "what-if"
    del command[command.index("--name"):command.index("--name") + 2]
    output = command.index("--output")
    command[output + 1] = "json"
    command[output:output] = ["--no-pretty-print", "--result-format", "ResourceIdOnly"]
    return command


def key_vault_rbac_preview_command(request: KeyVaultRbacDeploymentRequest) -> list[str]:
    command = key_vault_rbac_deployment_command(request)
    command[3] = "what-if"
    del command[command.index("--name"):command.index("--name") + 2]
    output = command.index("--output")
    command[output + 1] = "json"
    command[output:output] = ["--no-pretty-print", "--result-format", "ResourceIdOnly"]
    return command


def key_vault_reader_preview_command(
    request: KeyVaultReaderDeploymentRequest,
) -> list[str]:
    command = key_vault_reader_deployment_command(request)
    command[3] = "what-if"
    del command[command.index("--name"):command.index("--name") + 2]
    output = command.index("--output")
    command[output + 1] = "json"
    command[output:output] = [
        "--no-pretty-print", "--result-format", "ResourceIdOnly"
    ]
    return command


def sanitized_preview_safe(stdout: str, *, allowed_resource_types: set[str]) -> tuple[bool, dict[str, int]]:
    counts = {name: 0 for name in ("create", "modify", "delete", "no_change", "ignore", "deploy", "unsupported")}
    allowlist = {
        resource_type: resource_type
        for resource_type in (
            allowed_resource_types | DAILY_ENVIRONMENT_IGNORED_RESOURCE_TYPES
        )
    }
    summary = parse_sanitized_what_if(
        stdout,
        boundary="key_vault_live_proof",
        allowlisted_resource_types=allowlist,
    )
    if summary is None:
        return False, counts
    for action, key in (
        ("Create", "create"),
        ("Modify", "modify"),
        ("Delete", "delete"),
        ("NoChange", "no_change"),
        ("Ignore", "ignore"),
        ("Deploy", "deploy"),
        ("Unsupported", "unsupported"),
    ):
        counts[key] = summary.count(action)
    mutable_types = {
        "microsoft.keyvault/vaults",
        "microsoft.resources/deployments",
        "microsoft.authorization/roleassignments",
    }
    creates_are_narrow = all(
        change.action != "Create"
        or change.resource_type.casefold() in mutable_types
        for change in summary.changes
    )
    return bool(summary.all_changes_allowlisted and creates_are_narrow), counts


def deploy_key_vault(
    request: KeyVaultDeploymentRequest, *, runner: AzureCliRunner | None = None
) -> KeyVaultDeploymentResult:
    valid = _deployment_request_valid(request) and local_key_vault_contract_valid(request.repository_root)
    if not valid:
        return _deployment_result(request.mode, "deploy_key_vault", "local_contract_invalid")
    if request.mode == "check":
        return _deployment_result(request.mode, "deploy_key_vault", "success", ok=True, local_contract_valid=True)
    if runner is None:
        return _deployment_result(request.mode, "deploy_key_vault", "unexpected_error", local_contract_valid=True)
    outcome = runner.run(key_vault_deployment_command(request))
    accepted = outcome.return_code == 0
    return _deployment_result(
        request.mode, "deploy_key_vault",
        "success" if accepted else "deployment_failed",
        ok=accepted, local_contract_valid=True, azure_operation_attempted=True,
        deployment_requested=True, deployment_request_accepted=accepted,
        azure_mutation_made=True if accepted else None,
    )


def deploy_key_vault_rbac(
    request: KeyVaultRbacDeploymentRequest, *, runner: AzureCliRunner | None = None
) -> KeyVaultDeploymentResult:
    valid = _rbac_deployment_request_valid(request) and local_key_vault_contract_valid(request.repository_root)
    if not valid:
        return _deployment_result(request.mode, "deploy_key_vault_rbac", "local_contract_invalid")
    if request.mode == "check":
        return _deployment_result(request.mode, "deploy_key_vault_rbac", "success", ok=True, local_contract_valid=True)
    if runner is None:
        return _deployment_result(request.mode, "deploy_key_vault_rbac", "unexpected_error", local_contract_valid=True)
    outcome = runner.run(key_vault_rbac_deployment_command(request))
    accepted = outcome.return_code == 0
    return _deployment_result(
        request.mode, "deploy_key_vault_rbac",
        "success" if accepted else "deployment_failed",
        ok=accepted, local_contract_valid=True, azure_operation_attempted=True,
        deployment_requested=True, deployment_request_accepted=accepted,
        azure_mutation_made=True if accepted else None,
    )


def deploy_operator_key_vault_reader(
    request: KeyVaultReaderDeploymentRequest,
    *,
    runner: AzureCliRunner | None = None,
) -> KeyVaultDeploymentResult:
    valid = bool(
        request.mode in {"check", "live"}
        and _canonical_uuid(request.subscription_id) is not None
        and _safe_group(request.resource_group)
        and _safe_vault(request.vault_name)
        and _canonical_uuid(request.operator_principal_id) is not None
        and local_key_vault_reader_contract_valid(request.repository_root)
    )
    if not valid:
        return _deployment_result(
            request.mode,
            "deploy_operator_key_vault_reader",
            "local_contract_invalid",
        )
    if request.mode == "check":
        return _deployment_result(
            request.mode,
            "deploy_operator_key_vault_reader",
            "success",
            ok=True,
            local_contract_valid=True,
        )
    if runner is None:
        return _deployment_result(
            request.mode,
            "deploy_operator_key_vault_reader",
            "unexpected_error",
            local_contract_valid=True,
        )
    outcome = runner.run(key_vault_reader_deployment_command(request))
    accepted = outcome.return_code == 0
    return _deployment_result(
        request.mode,
        "deploy_operator_key_vault_reader",
        "success" if accepted else "deployment_failed",
        ok=accepted,
        local_contract_valid=True,
        azure_operation_attempted=True,
        deployment_requested=True,
        deployment_request_accepted=accepted,
        azure_mutation_made=True if accepted else None,
    )


def file_digest(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def evidence_valid(evidence: KeyVaultDeploymentEvidence) -> bool:
    return bool(
        _canonical_uuid(evidence.subscription_id)
        and _safe_group(evidence.resource_group)
        and _safe_vault(evidence.vault_name)
        and _safe_resource(evidence.web_app_name, 60)
        and _exact_resource_id(evidence.vault_resource_id, evidence.subscription_id, evidence.resource_group, "Microsoft.KeyVault/vaults", evidence.vault_name)
        and _canonical_uuid(evidence.web_app_principal_id)
        and evidence.role_definition_id.casefold().endswith("/" + KEY_VAULT_SECRETS_USER_ROLE_GUID)
        and _HEX_64.fullmatch(evidence.template_digest)
        and _RUN_EPOCH.fullmatch(evidence.run_epoch)
    )


def _vault_result(request: KeyVaultVerificationRequest, category: str, **overrides: object) -> KeyVaultVerificationResult:
    values: dict[str, object] = {
        "ok": False, "category": category, "operation": "verify_key_vault",
        "mode": request.mode if request.mode in {"check", "live"} else "invalid",
        "vault_contract_valid": False, "azure_request_attempted": False,
        "vault_missing_conclusive": False, "vault_verified": False,
        "resource_identity_verified": False, "provisioning_succeeded": False,
        "rbac_authorization_enabled": False, "legacy_access_policies_absent": False,
        "zero_secrets_verified": False, "secret_metadata_count": None,
        "recommended_next_step": "Stop and review the sanitized category.",
        "vault_resource_id": None,
    }
    values.update(overrides)
    return KeyVaultVerificationResult(**values)


def _rbac_result(request: KeyVaultRbacVerificationRequest, category: str, **overrides: object) -> KeyVaultRbacVerificationResult:
    values: dict[str, object] = {
        "ok": False, "category": category, "operation": "verify_key_vault_rbac",
        "mode": request.mode if request.mode in {"check", "live"} else "invalid",
        "role_contract_valid": False, "azure_request_attempted": False,
        "web_app_identity_verified": False, "vault_identity_verified": False,
        "assignment_missing_conclusive": False, "assignment_verified": False,
        "matching_assignment_count": None,
        "recommended_next_step": "Stop and review the sanitized category.",
        "subscription_id": None, "web_app_principal_id": None,
        "web_app_resource_id": None, "vault_resource_id": None,
        "role_definition_id": None,
    }
    values.update(overrides)
    return KeyVaultRbacVerificationResult(**values)


def _operator_identity_result(
    request: OperatorIdentityRequest, category: str, **overrides: object
) -> OperatorIdentityVerificationResult:
    values: dict[str, object] = {
        "ok": False,
        "category": category,
        "operation": "resolve_current_operator",
        "mode": request.mode if request.mode in {"check", "live"} else "invalid",
        "azure_request_attempted": False,
        "operator_identity_verified": False,
        "recommended_next_step": "Stop and review the sanitized category.",
        "operator_tenant_id": None,
        "operator_principal_id": None,
        "operator_account_name": None,
        "operator_principal_type": None,
    }
    values.update(overrides)
    return OperatorIdentityVerificationResult(**values)


def _reader_result(
    request: KeyVaultReaderVerificationRequest, category: str, **overrides: object
) -> KeyVaultReaderVerificationResult:
    values: dict[str, object] = {
        "ok": False,
        "category": category,
        "operation": "verify_operator_key_vault_reader",
        "mode": request.mode if request.mode in {"check", "live"} else "invalid",
        "role_contract_valid": False,
        "azure_request_attempted": False,
        "vault_identity_verified": False,
        "operator_identity_verified": False,
        "assignment_missing_conclusive": False,
        "assignment_verified": False,
        "matching_assignment_count": None,
        "recommended_next_step": "Stop and review the sanitized category.",
        "vault_resource_id": None,
        "role_definition_id": None,
    }
    values.update(overrides)
    return KeyVaultReaderVerificationResult(**values)


def _zero_secret_proof_result(
    mode: str, category: str, **overrides: object
) -> OperatorZeroSecretProofResult:
    values: dict[str, object] = {
        "ok": False,
        "category": category,
        "operation": "verify_zero_secrets_after_operator_reader",
        "mode": mode if mode in {"check", "live"} else "invalid",
        "operator_assignment_verified": False,
        "metadata_verification_attempted": False,
        "zero_secrets_verified": False,
        "secret_metadata_count": None,
        "recommended_next_step": "Stop and review the sanitized category.",
    }
    values.update(overrides)
    return OperatorZeroSecretProofResult(**values)


def _deployment_result(mode: str, operation: str, category: str, **overrides: object) -> KeyVaultDeploymentResult:
    values: dict[str, object] = {
        "ok": False, "category": category, "operation": operation,
        "mode": mode if mode in {"check", "live"} else "invalid",
        "local_contract_valid": False, "azure_operation_attempted": False,
        "deployment_requested": False, "deployment_request_accepted": False,
        "azure_mutation_made": False, "vault_verified": False,
        "assignment_verified": False,
    }
    values.update(overrides)
    return KeyVaultDeploymentResult(**values)


def _read_json(runner: AzureCliRunner, command: list[str], *, missing: str | None = None) -> tuple[object | None, str | None]:
    try:
        result = runner.run(command)
    except Exception:
        return None, "unexpected_error"
    if result.return_code != 0:
        return None, missing if missing is not None and result.return_code == 3 else "azure_request_failed"
    try:
        return json.loads(result.stdout), None
    except (TypeError, json.JSONDecodeError):
        return None, "response_parse_failed"


def _verification_request_valid(request: KeyVaultVerificationRequest) -> bool:
    return request.mode in {"check", "live"} and _canonical_uuid(request.subscription_id) is not None and _safe_group(request.resource_group) and _safe_vault(request.vault_name)


def _rbac_verification_request_valid(request: KeyVaultRbacVerificationRequest) -> bool:
    return _verification_request_valid(KeyVaultVerificationRequest(request.mode, request.subscription_id, request.resource_group, request.vault_name, request.repository_root)) and _safe_resource(request.web_app_name, 60)


def _deployment_request_valid(request: KeyVaultDeploymentRequest) -> bool:
    return request.mode in {"check", "live"} and _canonical_uuid(request.subscription_id) is not None and _safe_group(request.resource_group) and _safe_resource(request.location, 90) and _safe_resource(request.project_name, 20) and _safe_resource(request.environment_name, 10) and _safe_vault(request.vault_name) and _safe_resource(request.web_app_name, 60) and request.vault_name == repository_key_vault_name(request.resource_group, request.project_name, request.environment_name)


def _rbac_deployment_request_valid(request: KeyVaultRbacDeploymentRequest) -> bool:
    return request.mode in {"check", "live"} and _canonical_uuid(request.subscription_id) is not None and _safe_group(request.resource_group) and _safe_vault(request.vault_name) and _safe_resource(request.web_app_name, 60)


def _safe_group(value: object) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= 90 and value == value.strip() and _SAFE_NAME.fullmatch(value) is not None and not value.endswith(".")


def _safe_resource(value: object, maximum: int) -> bool:
    return isinstance(value, str) and 2 <= len(value) <= maximum and value == value.strip() and _RESOURCE_NAME.fullmatch(value) is not None


def _safe_vault(value: object) -> bool:
    return isinstance(value, str) and 3 <= len(value) <= 24 and _VAULT_NAME.fullmatch(value) is not None


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = str(UUID(value))
    except (ValueError, AttributeError):
        return None
    return parsed if parsed == value.casefold() else None


def _exact_resource_id(value: object, subscription_id: str, resource_group: str, resource_type: str, resource_name: str) -> bool:
    if not isinstance(value, str):
        return False
    expected = f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/{resource_type}/{resource_name}"
    return value.casefold() == expected.casefold()
