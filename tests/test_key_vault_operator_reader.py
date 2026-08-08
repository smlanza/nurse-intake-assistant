from dataclasses import replace
import importlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
TENANT_ID = "00000000-0000-0000-0000-000000000004"
OPERATOR_ID = "00000000-0000-0000-0000-000000000005"
OTHER_ID = "00000000-0000-0000-0000-000000000006"
RESOURCE_GROUP = "fictional-daily-rg"
VAULT_NAME = "kv123456789abcd"
ROLE_GUID = "21090545-7ca7-4776-b22c-e363652d74d2"
VAULT_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}/providers/"
    f"Microsoft.KeyVault/vaults/{VAULT_NAME}"
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


def _result(code: int, payload: object):
    return _service().CommandResult(code, json.dumps(payload), "private stderr")


def _identity_request(mode: str = "live"):
    return _service().OperatorIdentityRequest(
        mode=mode,
        subscription_id=SUBSCRIPTION_ID,
        tenant_id=TENANT_ID,
    )


def _reader_request(mode: str = "live", principal: str = OPERATOR_ID):
    return _service().KeyVaultReaderVerificationRequest(
        mode=mode,
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        vault_name=VAULT_NAME,
        operator_principal_id=principal,
        repository_root=ROOT,
    )


def _vault_payload() -> dict[str, object]:
    return {"name": VAULT_NAME, "id": VAULT_ID, "type": "Microsoft.KeyVault/vaults"}


def _assignment(
    *, principal: str = OPERATOR_ID, role: str = ROLE_ID, scope: str = VAULT_ID
) -> dict[str, str]:
    return {"principalId": principal, "roleDefinitionId": role, "scope": scope}


def test_operator_reader_bicep_is_dedicated_exact_and_secret_free() -> None:
    entry = (ROOT / "infra/key-vault-reader-rbac.bicep").read_text()
    module = (ROOT / "infra/modules/key-vault-reader-rbac.bicep").read_text()
    combined = entry + module

    assert "modules/key-vault-reader-rbac.bicep" in entry
    assert "Microsoft.KeyVault/vaults@2023-07-01" in combined
    assert "existing =" in combined
    assert f"keyVaultReaderRoleDefinitionGuid = '{ROLE_GUID}'" in module
    assert "scope: keyVault" in module
    assert "principalId: operatorPrincipalId" in module
    assert "principalType: 'User'" in module
    assert re.search(
        r"guid\(\s*keyVault\.id,\s*operatorPrincipalId,\s*"
        r"keyVaultReaderRoleDefinitionId\s*\)",
        module,
        re.DOTALL,
    )
    assert "newGuid(" not in combined
    assert "Microsoft.KeyVault/vaults/secrets" not in combined
    assert "Microsoft.Web/sites" not in combined
    assert "4633458b-17de-408a-b874-0445c86b69e6" not in combined
    assert "az role assignment create" not in combined
    assert re.findall(r"^output\s+", combined, re.MULTILINE) == []
    assert set(
        re.findall(
            r"(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])",
            combined.casefold(),
        )
    ) == {ROLE_GUID}


def test_operator_identity_check_is_offline() -> None:
    runner = FakeRunner([AssertionError("offline check must not call Azure")])
    result = _service().resolve_current_operator(_identity_request("check"), runner=runner)

    assert result.ok is True
    assert result.azure_request_attempted is False
    assert runner.calls == []


def test_operator_tenant_is_privately_resolved_when_ready_contract_has_no_tenant() -> None:
    service = _service()
    request = service.OperatorIdentityRequest(
        mode="live", subscription_id=SUBSCRIPTION_ID, tenant_id=None
    )
    runner = FakeRunner(
        [
            _result(0, {"id": SUBSCRIPTION_ID, "tenantId": TENANT_ID, "name": "operator@example.com", "type": "user"}),
            _result(0, {"id": OPERATOR_ID}),
        ]
    )
    result = service.resolve_current_operator(request, runner=runner)

    assert result.ok is True
    assert result.operator_tenant_id == TENANT_ID
    assert TENANT_ID not in json.dumps(result.to_json_dict())


def test_current_user_identity_is_resolved_by_two_bounded_projected_reads() -> None:
    runner = FakeRunner(
        [
            _result(0, {"id": SUBSCRIPTION_ID, "tenantId": TENANT_ID, "name": "operator@example.com", "type": "user"}),
            _result(0, {"id": OPERATOR_ID}),
        ]
    )
    result = _service().resolve_current_operator(_identity_request(), runner=runner)

    assert result.ok is True
    assert result.operator_identity_verified is True
    assert result.operator_principal_id == OPERATOR_ID
    assert runner.calls[0][:3] == ["az", "account", "show"]
    assert runner.calls[1][:4] == ["az", "ad", "signed-in-user", "show"]
    assert "{id:id}" in runner.calls[1]
    assert all("--query" in call and "--output" in call for call in runner.calls)


def test_operator_identity_rejects_malformed_ambiguous_or_changed_session() -> None:
    service = _service()
    malformed = service.resolve_current_operator(
        _identity_request(), runner=FakeRunner([_result(0, [])])
    )
    unsupported = service.resolve_current_operator(
        _identity_request(),
        runner=FakeRunner([_result(0, {"id": SUBSCRIPTION_ID, "tenantId": TENANT_ID, "name": "app", "type": "servicePrincipal"})]),
    )
    ambiguous = service.resolve_current_operator(
        _identity_request(),
        runner=FakeRunner(
            [
                _result(0, {"id": SUBSCRIPTION_ID, "tenantId": TENANT_ID, "name": "operator@example.com", "type": "user"}),
                _result(0, []),
            ]
        ),
    )

    assert malformed.category == "response_parse_failed"
    assert unsupported.category == "operator_identity_unsupported"
    assert ambiguous.category == "response_parse_failed"


def test_operator_identity_public_result_never_serializes_identity() -> None:
    runner = FakeRunner(
        [
            _result(0, {"id": SUBSCRIPTION_ID, "tenantId": TENANT_ID, "name": "operator@example.com", "type": "user"}),
            _result(0, {"id": OPERATOR_ID}),
        ]
    )
    result = _service().resolve_current_operator(_identity_request(), runner=runner)

    serialized = json.dumps(result.to_json_dict())
    assert OPERATOR_ID not in serialized
    assert SUBSCRIPTION_ID not in serialized
    assert TENANT_ID not in serialized
    assert "operator@example.com" not in serialized


def test_exact_one_direct_reader_assignment_succeeds() -> None:
    runner = FakeRunner([_result(0, _vault_payload()), _result(0, [_assignment()])])
    result = _service().verify_operator_key_vault_reader(_reader_request(), runner=runner)

    assert result.ok is True
    assert result.assignment_verified is True
    assert result.matching_assignment_count == 1


def test_missing_reader_assignment_is_conclusive() -> None:
    runner = FakeRunner([_result(0, _vault_payload()), _result(0, [])])
    result = _service().verify_operator_key_vault_reader(_reader_request(), runner=runner)

    assert result.ok is False
    assert result.category == "assignment_missing"
    assert result.assignment_missing_conclusive is True


def test_duplicate_reader_assignments_fail_closed() -> None:
    runner = FakeRunner([_result(0, _vault_payload()), _result(0, [_assignment(), _assignment()])])
    result = _service().verify_operator_key_vault_reader(_reader_request(), runner=runner)

    assert result.category == "assignment_ambiguous"
    assert result.assignment_verified is False


def test_wrong_principal_role_scope_and_malformed_assignment_fail_closed() -> None:
    service = _service()
    cases = (
        ([_assignment(principal=OTHER_ID)], "principal_mismatch"),
        ([_assignment(role=ROLE_ID.replace(ROLE_GUID, "00000000-0000-0000-0000-000000000099"))], "role_mismatch"),
        ([_assignment(scope=f"/subscriptions/{SUBSCRIPTION_ID}")], "authorization_scope_mismatch"),
        ([_assignment(scope=f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{RESOURCE_GROUP}")], "authorization_scope_mismatch"),
        ([_assignment(scope=VAULT_ID.replace(VAULT_NAME, "kvother123456789"))], "authorization_scope_mismatch"),
        ([{"principalId": OPERATOR_ID}], "response_parse_failed"),
    )
    for assignments, category in cases:
        runner = FakeRunner([_result(0, _vault_payload()), _result(0, assignments)])
        result = service.verify_operator_key_vault_reader(_reader_request(), runner=runner)
        assert result.category == category
        assert result.assignment_verified is False


def test_unrelated_assignment_cannot_become_exact_reader_proof() -> None:
    runner = FakeRunner(
        [
            _result(0, _vault_payload()),
            _result(0, [_assignment(role=ROLE_ID.replace(ROLE_GUID, "00000000-0000-0000-0000-000000000099"))]),
        ]
    )
    result = _service().verify_operator_key_vault_reader(_reader_request(), runner=runner)

    assert result.ok is False
    assert result.matching_assignment_count == 0


def test_reader_verification_serialization_contains_no_raw_ids() -> None:
    runner = FakeRunner([_result(0, _vault_payload()), _result(0, [_assignment()])])
    result = _service().verify_operator_key_vault_reader(_reader_request(), runner=runner)

    serialized = json.dumps(result.to_json_dict())
    for private in (OPERATOR_ID, SUBSCRIPTION_ID, VAULT_ID, ROLE_ID):
        assert private not in serialized


def test_reader_approval_is_one_use_and_invalidated_by_changed_evidence() -> None:
    service = _service()
    evidence = service.KeyVaultReaderApprovalEvidence(
        subscription_id=SUBSCRIPTION_ID,
        tenant_id=TENANT_ID,
        resource_group=RESOURCE_GROUP,
        vault_name=VAULT_NAME,
        vault_resource_id=VAULT_ID,
        operator_principal_id=OPERATOR_ID,
        operator_account_name="operator@example.com",
        operator_principal_type="User",
        role_definition_id=ROLE_ID,
        template_digest="a" * 64,
        run_epoch="b" * 32,
    )
    approval = service.OneUseApproval.bind(evidence)

    assert approval.consume(evidence) is True
    assert approval.consume(evidence) is False
    assert service.OneUseApproval.bind(evidence).consume(replace(evidence, operator_principal_id=OTHER_ID)) is False
    assert service.OneUseApproval.bind(evidence).consume(replace(evidence, run_epoch="c" * 32)) is False
    assert service.OneUseApproval.bind(evidence).consume(replace(evidence, tenant_id="00000000-0000-0000-0000-000000000007")) is False
    assert service.OneUseApproval.bind(evidence).consume(replace(evidence, operator_account_name="changed@example.com")) is False
    assert service.OneUseApproval.bind(evidence).consume(replace(evidence, vault_name="kvother123456789")) is False
    assert service.OneUseApproval.bind(evidence).consume(replace(evidence, vault_resource_id=VAULT_ID.replace(VAULT_NAME, "kvother123456789"))) is False
    assert service.OneUseApproval.bind(evidence).consume(replace(evidence, role_definition_id=ROLE_ID.replace(ROLE_GUID, "00000000-0000-0000-0000-000000000099"))) is False


def test_reader_deployment_is_exactly_one_bicep_request_without_ad_hoc_rbac() -> None:
    service = _service()
    request = service.KeyVaultReaderDeploymentRequest(
        mode="live",
        subscription_id=SUBSCRIPTION_ID,
        resource_group=RESOURCE_GROUP,
        vault_name=VAULT_NAME,
        operator_principal_id=OPERATOR_ID,
        repository_root=ROOT,
    )
    runner = FakeRunner([_result(0, {})])
    result = service.deploy_operator_key_vault_reader(request, runner=runner)

    assert result.ok is True
    assert result.deployment_requested is True
    assert result.assignment_verified is False
    assert len(runner.calls) == 1
    command = runner.calls[0]
    assert command[:4] == ["az", "deployment", "group", "create"]
    assert "infra/key-vault-reader-rbac.bicep" in " ".join(command)
    assert "az role assignment create" not in " ".join(command)
    assert "secret" not in " ".join(command).casefold()


def test_metadata_verification_is_gated_by_exact_reader_proof() -> None:
    service = _service()
    runner = FakeRunner([_result(0, _vault_payload()), _result(0, [])])
    result = service.verify_zero_secrets_after_operator_reader(
        _reader_request(),
        service.KeyVaultVerificationRequest(
            mode="live",
            subscription_id=SUBSCRIPTION_ID,
            resource_group=RESOURCE_GROUP,
            vault_name=VAULT_NAME,
            repository_root=ROOT,
        ),
        runner=runner,
    )

    assert result.category == "assignment_missing"
    assert result.metadata_verification_attempted is False
    assert len(runner.calls) == 2


def test_control_plane_only_vault_revalidation_makes_no_metadata_call() -> None:
    service = _service()
    full_vault = {
        **_vault_payload(),
        "provisioningState": "Succeeded",
        "enableRbacAuthorization": True,
        "accessPolicyCount": 0,
    }
    runner = FakeRunner([_result(0, full_vault)])
    result = service.verify_key_vault(
        service.KeyVaultVerificationRequest(
            mode="live", subscription_id=SUBSCRIPTION_ID,
            resource_group=RESOURCE_GROUP, vault_name=VAULT_NAME,
            repository_root=ROOT,
        ),
        runner=runner,
        verify_secret_metadata=False,
    )

    assert result.ok is True
    assert result.resource_identity_verified is True
    assert result.rbac_authorization_enabled is True
    assert result.legacy_access_policies_absent is True
    assert result.zero_secrets_verified is False
    assert len(runner.calls) == 1
    assert "secret" not in " ".join(runner.calls[0]).casefold()


def test_exact_reader_then_zero_metadata_proves_empty_without_value_read() -> None:
    service = _service()
    full_vault = {
        **_vault_payload(),
        "provisioningState": "Succeeded",
        "enableRbacAuthorization": True,
        "accessPolicyCount": 0,
    }
    runner = FakeRunner(
        [
            _result(0, _vault_payload()),
            _result(0, [_assignment()]),
            _result(0, full_vault),
            _result(0, 0),
        ]
    )
    result = service.verify_zero_secrets_after_operator_reader(
        _reader_request(),
        service.KeyVaultVerificationRequest(
            mode="live", subscription_id=SUBSCRIPTION_ID,
            resource_group=RESOURCE_GROUP, vault_name=VAULT_NAME,
            repository_root=ROOT,
        ),
        runner=runner,
    )

    assert result.ok is True
    assert result.operator_assignment_verified is True
    assert result.metadata_verification_attempted is True
    assert result.zero_secrets_verified is True
    combined = " ".join(" ".join(call) for call in runner.calls).casefold()
    assert "secret list" in combined
    assert "secret show" not in combined
    assert "secret version" not in combined


def test_nonzero_or_failed_metadata_never_proves_empty() -> None:
    service = _service()
    full_vault = {
        **_vault_payload(),
        "provisioningState": "Succeeded",
        "enableRbacAuthorization": True,
        "accessPolicyCount": 0,
    }
    for final_result, category in ((_result(0, 1), "secrets_present"), (_result(1, {}), "secret_metadata_read_failed"), (_result(0, "bad"), "secret_metadata_parse_failed")):
        runner = FakeRunner(
            [_result(0, _vault_payload()), _result(0, [_assignment()]), _result(0, full_vault), final_result]
        )
        result = service.verify_zero_secrets_after_operator_reader(
            _reader_request(),
            service.KeyVaultVerificationRequest(
                mode="live", subscription_id=SUBSCRIPTION_ID,
                resource_group=RESOURCE_GROUP, vault_name=VAULT_NAME,
                repository_root=ROOT,
            ),
            runner=runner,
        )
        assert result.ok is False
        assert result.category == category
        assert result.zero_secrets_verified is False
