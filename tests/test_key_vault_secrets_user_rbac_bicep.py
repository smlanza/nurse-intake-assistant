from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
ENTRY_POINT = "key-vault-secrets-user-rbac.bicep"
MODULE = "modules/key-vault-secrets-user-rbac.bicep"
ROLE_GUID = "4633458b-17de-408a-b874-0445c86b69e6"


def _text(path: str) -> str:
    return (INFRA / path).read_text()


def test_authorization_is_composed_daily_and_retains_explicit_repair_boundary() -> None:
    main = _text("main.bicep")
    entry_point = _text(ENTRY_POINT)

    assert "Microsoft.Authorization/roleAssignments" not in main
    assert ROLE_GUID not in main
    assert re.search(
        r"module\s+keyVaultRuntimeRbac\s+"
        r"'modules/key-vault-secrets-user-rbac\.bicep'\s*=\s*"
        r"if\s*\(enableKeyVaultRuntimeAuthorization\s*&&\s*"
        r"deployApp\s*&&\s*deployKeyVault\)",
        main,
    )
    assert "targetScope = 'resourceGroup'" in entry_point
    assert re.search(
        r"module\s+keyVaultSecretsUserRbac\s+"
        r"'modules/key-vault-secrets-user-rbac\.bicep'",
        entry_point,
    )


def test_entry_point_resolves_the_existing_web_app_system_identity() -> None:
    entry_point = _text(ENTRY_POINT)

    assert "resource webApp 'Microsoft.Web/sites@2024-04-01' existing" in entry_point
    assert "resource keyVault 'Microsoft.KeyVault/vaults@" in entry_point
    assert "existing =" in entry_point
    assert "webAppPrincipalId: webApp.identity.principalId" in entry_point
    assert "keyVaultName: keyVault.name" in entry_point
    assert re.findall(r"^param\s+(\w+)\s+", entry_point, re.MULTILINE) == [
        "webAppName",
        "keyVaultName",
    ]


def test_module_assigns_exact_secrets_user_role_at_exact_vault_scope() -> None:
    module = _text(MODULE)

    assert f"var keyVaultSecretsUserRoleDefinitionGuid = '{ROLE_GUID}'" in module
    assert "subscriptionResourceId(" in module
    assert "'Microsoft.Authorization/roleDefinitions'" in module
    assert "Microsoft.Authorization/roleAssignments@" in module
    assert "scope: keyVault" in module
    assert "roleDefinitionId: keyVaultSecretsUserRoleDefinitionId" in module
    assert "principalId: webAppPrincipalId" in module
    assert "principalType: 'ServicePrincipal'" in module
    assert "scope: subscription()" not in module
    assert "scope: resourceGroup()" not in module


def test_assignment_name_deterministically_binds_vault_principal_and_role() -> None:
    module = _text(MODULE)

    assert re.search(
        r"name:\s*guid\(\s*keyVault\.id,\s*webAppPrincipalId,\s*"
        r"keyVaultSecretsUserRoleDefinitionId\s*\)",
        module,
        re.DOTALL,
    )
    assert "newGuid(" not in module


def test_rbac_boundary_contains_no_broader_key_or_certificate_role() -> None:
    combined = _text(ENTRY_POINT) + _text(MODULE)
    role_guids = set(
        re.findall(
            r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])",
            combined.casefold(),
        )
    )

    assert role_guids == {ROLE_GUID}
    for forbidden in (
        "Owner",
        "Contributor",
        "Administrator",
        "User Access Administrator",
        "Secrets Officer",
        "Certificates Officer",
        "Crypto Officer",
        "customRole",
    ):
        assert re.search(rf"\b{re.escape(forbidden)}\b", combined, re.IGNORECASE) is None


def test_rbac_boundary_serializes_no_identity_or_resource_identifiers() -> None:
    combined = _text(ENTRY_POINT) + _text(MODULE)

    assert re.findall(r"^output\s+(\w+)\s+", combined, re.MULTILINE) == []
    assert "listSecrets(" not in combined
    assert "getSecret" not in combined
