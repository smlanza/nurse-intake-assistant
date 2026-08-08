from dataclasses import replace
import importlib
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
RESOURCE_GROUP = "fictional-daily-rg"
VAULT_NAME = "kv123456789abcd"
WEB_APP_NAME = "fictional-web-app"
PRINCIPAL_ID = "00000000-0000-0000-0000-000000000002"
ROLE_GUID = "4633458b-17de-408a-b874-0445c86b69e6"
VAULT_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/"
    f"Microsoft.KeyVault/vaults/{VAULT_NAME}"
)
WEB_APP_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/"
    f"Microsoft.Web/sites/{WEB_APP_NAME}"
)
ROLE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/providers/"
    f"Microsoft.Authorization/roleDefinitions/{ROLE_GUID}"
)


def _service():
    return importlib.import_module("src.app.services.key_vault_live_proof")


class FakeRunner:
    def __init__(self, results: list[object]) -> None:
        self.results = list(results)
        self.calls: list[list[str]] = []

    def run(self, args: list[str]):
        self.calls.append(args)
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _result(code: int, payload: object = None):
    service = _service()
    stdout = json.dumps(payload)
    return service.CommandResult(code, stdout, "private stderr")


def _vault_request(mode: str = "live"):
    service = _service()
    return service.KeyVaultVerificationRequest(
        mode=mode,
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        vault_name=VAULT_NAME,
        repository_root=ROOT,
    )


def _rbac_request(mode: str = "live"):
    service = _service()
    return service.KeyVaultRbacVerificationRequest(
        mode=mode,
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        vault_name=VAULT_NAME,
        web_app_name=WEB_APP_NAME,
        repository_root=ROOT,
    )


def _vault_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": VAULT_NAME,
        "id": VAULT_ID,
        "type": "Microsoft.KeyVault/vaults",
        "provisioningState": "Succeeded",
        "enableRbacAuthorization": True,
        "accessPolicyCount": 0,
    }
    payload.update(overrides)
    return payload


def _identity_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "principalId": PRINCIPAL_ID,
        "type": "SystemAssigned",
        "webAppId": WEB_APP_ID,
    }
    payload.update(overrides)
    return payload


def _assignment(
    *,
    principal_id: str = PRINCIPAL_ID,
    role_definition_id: str = ROLE_ID,
    scope: str = VAULT_ID,
) -> dict[str, str]:
    return {
        "principalId": principal_id,
        "roleDefinitionId": role_definition_id,
        "scope": scope,
    }


def test_check_modes_are_offline_and_validate_the_frozen_bicep_contract() -> None:
    service = _service()
    runner = FakeRunner([AssertionError("check must not call Azure")])

    vault = service.verify_key_vault(_vault_request("check"), runner=runner)
    rbac = service.verify_key_vault_rbac(_rbac_request("check"), runner=runner)

    assert vault.ok is True and vault.vault_contract_valid is True
    assert rbac.ok is True and rbac.role_contract_valid is True
    assert vault.azure_request_attempted is False
    assert rbac.azure_request_attempted is False
    assert runner.calls == []


def test_invalid_contract_fails_before_runner_use(tmp_path: Path) -> None:
    service = _service()
    runner = FakeRunner([])
    (tmp_path / "infra/modules").mkdir(parents=True)
    request = replace(_vault_request(), repository_root=tmp_path)

    result = service.verify_key_vault(request, runner=runner)

    assert result.category == "local_contract_invalid"
    assert result.azure_request_attempted is False
    assert runner.calls == []


@pytest.mark.parametrize(
    ("overrides", "category"),
    [
        ({"name": "wrong-vault"}, "vault_identity_mismatch"),
        ({"id": VAULT_ID.replace(RESOURCE_GROUP, "wrong-rg")}, "vault_identity_mismatch"),
        ({"type": "Microsoft.Storage/storageAccounts"}, "vault_identity_mismatch"),
        ({"provisioningState": "Failed"}, "vault_provisioning_failed"),
        ({"enableRbacAuthorization": False}, "rbac_authorization_disabled"),
        ({"accessPolicyCount": 1}, "legacy_access_policy_present"),
        ({"raw": "unexpected"}, "response_parse_failed"),
    ],
)
def test_vault_verification_fails_closed_for_contract_mismatch(
    overrides: dict[str, object], category: str
) -> None:
    service = _service()
    runner = FakeRunner([_result(0, _vault_payload(**overrides))])

    result = service.verify_key_vault(_vault_request(), runner=runner)

    assert result.ok is False
    assert result.category == category
    assert len(runner.calls) == 1


def test_missing_or_malformed_vault_fails_safely() -> None:
    service = _service()
    missing = service.verify_key_vault(
        _vault_request(), runner=FakeRunner([_result(3, "")])
    )
    malformed = service.verify_key_vault(
        _vault_request(), runner=FakeRunner([_result(0, [])])
    )

    assert missing.category == "vault_missing"
    assert missing.vault_missing_conclusive is True
    assert malformed.category == "response_parse_failed"


def test_zero_secret_metadata_count_succeeds_without_value_or_version_read() -> None:
    service = _service()
    runner = FakeRunner([_result(0, _vault_payload()), _result(0, 0)])

    result = service.verify_key_vault(_vault_request(), runner=runner)

    assert result.ok is True
    assert result.vault_verified is True
    assert result.zero_secrets_verified is True
    assert len(runner.calls) == 2
    secret_call = runner.calls[1]
    assert secret_call[:4] == ["az", "keyvault", "secret", "list"]
    assert "show" not in secret_call
    assert "--maxresults" in secret_call
    assert all("version" not in value.casefold() for value in secret_call)


@pytest.mark.parametrize("count", [1, 2])
def test_any_secret_metadata_object_fails_zero_secret_proof(count: int) -> None:
    service = _service()
    result = service.verify_key_vault(
        _vault_request(),
        runner=FakeRunner([_result(0, _vault_payload()), _result(0, count)]),
    )

    assert result.category == "secrets_present"
    assert result.zero_secrets_verified is False


@pytest.mark.parametrize("payload", [None, True, "0", [], {}, -1])
def test_malformed_secret_metadata_count_fails_closed(payload: object) -> None:
    service = _service()
    result = service.verify_key_vault(
        _vault_request(),
        runner=FakeRunner([_result(0, _vault_payload()), _result(0, payload)]),
    )

    assert result.category == "secret_metadata_parse_failed"


def _rbac_runner(assignments: object) -> FakeRunner:
    return FakeRunner(
        [
            _result(0, _identity_payload()),
            _result(0, {"name": VAULT_NAME, "id": VAULT_ID, "type": "Microsoft.KeyVault/vaults"}),
            _result(0, assignments),
        ]
    )


def test_exact_one_direct_secrets_user_assignment_succeeds() -> None:
    service = _service()
    result = service.verify_key_vault_rbac(
        _rbac_request(), runner=_rbac_runner([_assignment()])
    )

    assert result.ok is True
    assert result.web_app_identity_verified is True
    assert result.assignment_verified is True
    assert result.matching_assignment_count == 1


def test_no_assignment_is_conclusively_missing() -> None:
    service = _service()
    result = service.verify_key_vault_rbac(
        _rbac_request(), runner=_rbac_runner([])
    )

    assert result.category == "assignment_missing"
    assert result.assignment_missing_conclusive is True
    assert result.matching_assignment_count == 0


@pytest.mark.parametrize(
    ("assignments", "category"),
    [
        ([_assignment(), _assignment()], "assignment_ambiguous"),
        ([_assignment(scope=f"/subscriptions/{SUBSCRIPTION_ID}")], "assignment_scope_mismatch"),
        ([_assignment(scope=f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}")], "assignment_scope_mismatch"),
        ([_assignment(role_definition_id=ROLE_ID.replace(ROLE_GUID, "00482a5a-887f-4fb3-b363-3b7fe8e74483"))], "role_mismatch"),
        ([_assignment(principal_id="00000000-0000-0000-0000-000000000099")], "principal_mismatch"),
        ([{"principalId": PRINCIPAL_ID}], "response_parse_failed"),
    ],
)
def test_rbac_verification_rejects_nonexact_or_malformed_assignments(
    assignments: object, category: str
) -> None:
    service = _service()
    result = service.verify_key_vault_rbac(
        _rbac_request(), runner=_rbac_runner(assignments)
    )

    assert result.ok is False
    assert result.category == category
    assert result.assignment_missing_conclusive is False


def test_rbac_result_serialization_contains_no_raw_identifiers() -> None:
    service = _service()
    result = service.verify_key_vault_rbac(
        _rbac_request(), runner=_rbac_runner([_assignment()])
    )
    serialized = json.dumps(result.to_json_dict())

    for private in (SUBSCRIPTION_ID, PRINCIPAL_ID, VAULT_ID, WEB_APP_ID, ROLE_ID):
        assert private not in serialized
    for forbidden_key in (
        "subscription_id",
        "principal_id",
        "resource_id",
        "role_assignment_id",
    ):
        assert forbidden_key not in result.to_json_dict()


def test_deployment_commands_are_bicep_only_and_have_no_secret_parameters() -> None:
    service = _service()
    vault = service.KeyVaultDeploymentRequest(
        mode="live",
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        location="eastus2",
        project_name="nurse-intake",
        environment_name="daily",
        vault_name=VAULT_NAME,
        web_app_name=WEB_APP_NAME,
        repository_root=ROOT,
    )
    rbac = service.KeyVaultRbacDeploymentRequest(
        mode="live",
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        vault_name=VAULT_NAME,
        web_app_name=WEB_APP_NAME,
        repository_root=ROOT,
    )

    vault_command = service.key_vault_deployment_command(vault)
    rbac_command = service.key_vault_rbac_deployment_command(rbac)

    assert vault_command[:4] == ["az", "deployment", "group", "create"]
    assert rbac_command[:4] == ["az", "deployment", "group", "create"]
    assert "infra/modules/key-vault.bicep" in " ".join(vault_command)
    assert "infra/key-vault-secrets-user-rbac.bicep" in " ".join(rbac_command)
    assert "az role assignment create" not in " ".join(rbac_command)
    combined = " ".join(vault_command + rbac_command).casefold()
    for forbidden in ("secretvalue", "password", "connectionstring", "credential"):
        assert forbidden not in combined


def test_approval_evidence_is_current_run_one_use_and_change_sensitive() -> None:
    service = _service()
    evidence = service.KeyVaultDeploymentEvidence(
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        vault_name=VAULT_NAME,
        web_app_name=WEB_APP_NAME,
        role_definition_id=ROLE_ID,
        web_app_principal_id=PRINCIPAL_ID,
        vault_resource_id=VAULT_ID,
        template_digest="a" * 64,
        run_epoch="b" * 32,
    )
    approval = service.OneUseApproval.bind(evidence)

    assert approval.consume(evidence) is True
    assert approval.consume(evidence) is False
    changed = replace(evidence, vault_name="kvdifferent12345")
    assert service.OneUseApproval.bind(evidence).consume(changed) is False


def test_preview_parser_accepts_vault_scoped_role_assignment_extension_resource() -> None:
    service = _service()
    role_assignment_id = (
        f"{VAULT_ID}/providers/Microsoft.Authorization/roleAssignments/"
        "00000000-0000-0000-0000-000000000003"
    )
    safe, counts = service.sanitized_preview_safe(
        json.dumps(
            {
                "changes": [
                    {
                        "changeType": "Create",
                        "resourceId": role_assignment_id,
                        "resourceType": "Microsoft.Authorization/roleAssignments",
                    }
                ]
            }
        ),
        allowed_resource_types={"Microsoft.Authorization/roleAssignments"},
    )

    assert safe is True
    assert counts["create"] == 1


def test_preview_parser_accepts_known_daily_environment_ignore_context() -> None:
    service = _service()
    safe, counts = service.sanitized_preview_safe(
        json.dumps(
            {
                "changes": [
                    {
                        "changeType": "Create",
                        "resourceId": VAULT_ID,
                        "resourceType": "Microsoft.KeyVault/vaults",
                    },
                    {
                        "changeType": "Ignore",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/"
                            f"{RESOURCE_GROUP}/providers/Microsoft.Web/sites/{WEB_APP_NAME}"
                        ),
                        "resourceType": "Microsoft.Web/sites",
                    },
                    {
                        "changeType": "Ignore",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/"
                            f"{RESOURCE_GROUP}/providers/microsoft.alertsmanagement/"
                            "smartDetectorAlertRules/example"
                        ),
                        "resourceType": (
                            "microsoft.alertsmanagement/smartDetectorAlertRules"
                        ),
                    },
                    {
                        "changeType": "Ignore",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/"
                            f"{RESOURCE_GROUP}/providers/microsoft.insights/"
                            "actiongroups/example"
                        ),
                        "resourceType": "microsoft.insights/actiongroups",
                    },
                ]
            }
        ),
        allowed_resource_types={"Microsoft.KeyVault/vaults"},
    )

    assert safe is True
    assert counts["create"] == 1
    assert counts["ignore"] == 3


def test_preview_parser_rejects_unknown_ignored_resource_type() -> None:
    service = _service()
    safe, counts = service.sanitized_preview_safe(
        json.dumps(
            {
                "changes": [
                    {
                        "changeType": "Ignore",
                        "resourceId": (
                            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/"
                            f"{RESOURCE_GROUP}/providers/Contoso.Unknown/widgets/example"
                        ),
                        "resourceType": "Contoso.Unknown/widgets",
                    }
                ]
            }
        ),
        allowed_resource_types={"Microsoft.KeyVault/vaults"},
    )

    assert safe is False
    assert counts["ignore"] == 1


def test_each_live_deployment_service_makes_exactly_one_request() -> None:
    service = _service()
    vault_request = service.KeyVaultDeploymentRequest(
        mode="live", subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP, location="eastus2",
        project_name="nurse-intake", environment_name="daily",
        vault_name=service.repository_key_vault_name(
            RESOURCE_GROUP, "nurse-intake", "daily"
        ), web_app_name=WEB_APP_NAME,
        repository_root=ROOT,
    )
    rbac_request = service.KeyVaultRbacDeploymentRequest(
        mode="live", subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP, vault_name=VAULT_NAME,
        web_app_name=WEB_APP_NAME, repository_root=ROOT,
    )
    vault_runner = FakeRunner([_result(0, {})])
    rbac_runner = FakeRunner([_result(0, {})])

    vault = service.deploy_key_vault(vault_request, runner=vault_runner)
    rbac = service.deploy_key_vault_rbac(rbac_request, runner=rbac_runner)

    assert vault.deployment_request_accepted is True
    assert rbac.deployment_request_accepted is True
    assert len(vault_runner.calls) == len(rbac_runner.calls) == 1
    assert vault.vault_verified is False
    assert rbac.assignment_verified is False
