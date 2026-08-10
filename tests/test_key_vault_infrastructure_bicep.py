from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"
MODULE = "modules/key-vault.bicep"


def _text(path: str) -> str:
    return (INFRA / path).read_text()


def test_main_makes_key_vault_optional_and_disabled_by_default() -> None:
    main = _text("main.bicep")

    assert re.search(r"param\s+deployKeyVault\s+bool\s*=\s*false", main)
    assert re.search(
        r"module\s+keyVault\s+'modules/key-vault\.bicep'\s*=\s*"
        r"if\s*\(deployKeyVault\)",
        main,
    )
    assert re.search(
        r"output\s+keyVaultName\s+string\s*=\s*"
        r"deployKeyVault\s*\?\s*keyVault!\.outputs\.keyVaultName\s*:\s*''",
        main,
    )

    # Ordinary application behavior remains opt-in and authorization remains separate.
    assert re.search(r"param\s+deployApp\s+bool\s*=\s*false", main)
    assert re.search(r"param\s+deployFoundry\s+bool\s*=\s*false", main)
    assert "Microsoft.Authorization/roleAssignments" not in main
    assert "enableKeyVaultRuntimeAuthorization" not in main
    assert "keyVaultRuntimeRbac" not in main
    assert "modules/key-vault-secrets-user-rbac.bicep" not in main


def test_main_derives_a_disposable_repository_owned_vault_name() -> None:
    main = _text("main.bicep")

    assert "var suffix = resourceNameSuffix ?? uniqueString(" in main
    assert "var keyVaultName = 'kv${suffix}'" in main
    assert "keyVaultName: keyVaultName" in main
    assert "newGuid(" not in main


def test_key_vault_module_uses_rbac_without_access_policies() -> None:
    module = _text(MODULE)

    assert "targetScope = 'resourceGroup'" in module
    assert re.search(
        r"resource\s+keyVault\s+'Microsoft\.KeyVault/vaults@[^']+'\s*=\s*\{",
        module,
    )
    assert "name: keyVaultName" in module
    assert "location: location" in module
    assert "tenantId: subscription().tenantId" in module
    assert re.search(r"enableRbacAuthorization\s*:\s*true", module)
    assert re.search(r"\baccessPolicies\b", module, re.IGNORECASE) is None


def test_key_vault_module_creates_no_secrets_or_credential_values() -> None:
    module = _text(MODULE)
    lowered = module.casefold()

    for forbidden in (
        "microsoft.keyvault/vaults/secrets",
        "resource secret",
        "secretvalue",
        "connectionstring",
        "accountkey",
        "apikey",
        "password",
        "listkeys(",
        "listsecrets(",
    ):
        assert forbidden not in lowered
    assert re.search(r"^\s*value\s*:", module, re.MULTILINE) is None


def test_key_vault_module_exposes_only_the_name_required_downstream() -> None:
    module = _text(MODULE)
    outputs = re.findall(r"^output\s+(\w+)\s+", module, re.MULTILINE)

    assert outputs == ["keyVaultName"]
    assert "output keyVaultName string = keyVault.name" in module
    for forbidden in ("vaultUri", "resourceId", "principalId", "secret"):
        assert all(forbidden.casefold() not in output.casefold() for output in outputs)


def test_key_vault_lifecycle_is_owned_by_the_disposable_resource_group() -> None:
    module = _text(MODULE)

    assert "targetScope = 'resourceGroup'" in module
    assert "targetScope = 'subscription'" not in module
    assert "scope: subscription()" not in module
    assert "existing =" not in module
