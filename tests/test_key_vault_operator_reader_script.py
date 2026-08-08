import importlib
import json
from types import SimpleNamespace

import pytest


SUBSCRIPTION_ID = "00000000-0000-0000-0000-000000000001"
TENANT_ID = "00000000-0000-0000-0000-000000000004"
OPERATOR_ID = "00000000-0000-0000-0000-000000000005"
VAULT_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/fictional-daily-rg/"
    "providers/Microsoft.KeyVault/vaults/kv123456789abcd"
)
ROLE_ID = (
    f"/subscriptions/{SUBSCRIPTION_ID}/providers/"
    "Microsoft.Authorization/roleDefinitions/21090545-7ca7-4776-b22c-e363652d74d2"
)
ARGS = [
    "--config", ".env.daily-azure.local",
    "--readiness-receipt", ".artifacts/daily-azure-rebuild/readiness-receipt.json",
    "--json",
]


def _script():
    return importlib.import_module("scripts.prove_key_vault_live")


def _context():
    return (
        SimpleNamespace(
            location="eastus2",
            project_name="nurse-intake",
            environment_name="daily",
            tenant_id=TENANT_ID,
        ),
        SimpleNamespace(
            resource_group="fictional-daily-rg",
            web_app_name="fictional-web-app",
            run_epoch="b" * 32,
        ),
        SUBSCRIPTION_ID,
        "kv123456789abcd",
    )


def _identity(*, ok: bool = True, category: str = "success", principal: str = OPERATOR_ID):
    return SimpleNamespace(
        ok=ok,
        category=category,
        azure_request_attempted=True,
        operator_identity_verified=ok,
        operator_tenant_id=TENANT_ID if ok else None,
        operator_principal_id=principal if ok else None,
        operator_account_name="operator@example.com" if ok else None,
        operator_principal_type="User" if ok else None,
    )


def _reader(*, ok: bool, missing: bool = False):
    return SimpleNamespace(
        ok=ok,
        category="success" if ok else "assignment_missing",
        role_contract_valid=True,
        azure_request_attempted=True,
        vault_identity_verified=True,
        operator_identity_verified=True,
        assignment_missing_conclusive=missing,
        assignment_verified=ok,
        matching_assignment_count=1 if ok else 0,
        vault_resource_id=VAULT_ID,
        role_definition_id=ROLE_ID,
    )


def _vault(*, ok: bool = True):
    return SimpleNamespace(
        ok=ok,
        category="success" if ok else "secret_metadata_read_failed",
        vault_contract_valid=True,
        azure_request_attempted=True,
        vault_verified=ok,
        resource_identity_verified=True,
        rbac_authorization_enabled=True,
        legacy_access_policies_absent=True,
        zero_secrets_verified=ok,
        secret_metadata_count=0 if ok else None,
    )


def _configure(monkeypatch: pytest.MonkeyPatch):
    script = _script()
    monkeypatch.setattr(script, "_receipt_context", lambda _args: _context())
    monkeypatch.setattr(script, "_account_matches", lambda *_args: True)
    monkeypatch.setattr(script, "_create_runner", lambda: object())
    monkeypatch.setattr(script, "verify_key_vault", lambda *_args, **_kwargs: _vault(ok=False))
    return script


def test_operator_reader_check_constructs_no_azure_runner(monkeypatch, capsys) -> None:
    script = _script()
    monkeypatch.setattr(script, "_receipt_context", lambda _args: _context())
    monkeypatch.setattr(
        script, "_create_runner", lambda: pytest.fail("check must remain offline")
    )

    code = script.main(["--check-operator-reader", *ARGS])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["ready_verified"] is True
    assert payload["operator_reader_contract_valid"] is True
    assert payload["azure_operation_attempted"] is False


def test_identity_failure_stops_before_reader_verification(monkeypatch, capsys) -> None:
    script = _configure(monkeypatch)
    monkeypatch.setattr(script, "resolve_current_operator", lambda *_args, **_kwargs: _identity(ok=False, category="operator_identity_unsupported"))
    monkeypatch.setattr(script, "verify_operator_key_vault_reader", lambda *_args, **_kwargs: pytest.fail("reader verification must not run"))

    code = script.main(["--verify-operator-reader", *ARGS])
    payload = json.loads(capsys.readouterr().out)

    assert code != 0
    assert payload["category"] == "operator_identity_unsupported"
    assert payload["operator_identity_verified"] is False


def test_vault_control_plane_failure_stops_before_reader_preflight(monkeypatch, capsys) -> None:
    script = _configure(monkeypatch)
    bad_vault = _vault(ok=False)
    bad_vault.resource_identity_verified = False
    monkeypatch.setattr(script, "verify_key_vault", lambda *_args, **_kwargs: bad_vault)
    monkeypatch.setattr(script, "resolve_current_operator", lambda *_args, **_kwargs: _identity())
    monkeypatch.setattr(
        script,
        "verify_operator_key_vault_reader",
        lambda *_args, **_kwargs: pytest.fail("Reader preflight must stay gated"),
    )

    code = script.main(["--verify-operator-reader", *ARGS])
    payload = json.loads(capsys.readouterr().out)

    assert code != 0
    assert payload["category"] == "vault_control_plane_unverified"


def test_exact_reader_reuse_skips_prompt_and_mutation_then_proves_zero(monkeypatch, capsys) -> None:
    script = _configure(monkeypatch)
    monkeypatch.setattr(script, "resolve_current_operator", lambda *_args, **_kwargs: _identity())
    monkeypatch.setattr(script, "verify_operator_key_vault_reader", lambda *_args, **_kwargs: _reader(ok=True))
    monkeypatch.setattr(script, "verify_key_vault", lambda *_args, **_kwargs: _vault())
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args, **_kwargs: pytest.fail("reuse must not prompt"))
    monkeypatch.setattr(script, "deploy_operator_key_vault_reader", lambda *_args, **_kwargs: pytest.fail("reuse must not deploy"))

    code = script.main(["--deploy-operator-reader", *ARGS])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["operator_assignment_reused"] is True
    assert payload["operator_assignment_verified"] is True
    assert payload["metadata_verification_attempted"] is True
    assert payload["zero_secrets_verified"] is True
    assert payload["azure_mutation_made"] is False


def test_missing_reader_default_no_causes_zero_mutation(monkeypatch, capsys) -> None:
    script = _configure(monkeypatch)
    monkeypatch.setattr(script, "resolve_current_operator", lambda *_args, **_kwargs: _identity())
    monkeypatch.setattr(script, "verify_operator_key_vault_reader", lambda *_args, **_kwargs: _reader(ok=False, missing=True))
    monkeypatch.setattr(script, "_reader_preview", lambda *_args, **_kwargs: (True, {"create": 1, "modify": 0, "delete": 0, "no_change": 0, "ignore": 0, "deploy": 0, "unsupported": 0}))
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(script, "deploy_operator_key_vault_reader", lambda *_args, **_kwargs: pytest.fail("decline must not deploy"))

    code = script.main(["--deploy-operator-reader", *ARGS])
    payload = json.loads(capsys.readouterr().out)

    assert code != 0
    assert payload["category"] == "operator_declined"
    assert payload["azure_mutation_made"] is False


def test_approved_reader_deploy_revalidates_then_verifies_and_proves_zero(monkeypatch, capsys) -> None:
    script = _configure(monkeypatch)
    identities = [_identity(), _identity()]
    readers = [_reader(ok=False, missing=True), _reader(ok=False, missing=True), _reader(ok=True)]
    monkeypatch.setattr(script, "resolve_current_operator", lambda *_args, **_kwargs: identities.pop(0))
    monkeypatch.setattr(script, "verify_operator_key_vault_reader", lambda *_args, **_kwargs: readers.pop(0))
    monkeypatch.setattr(script, "_reader_preview", lambda *_args, **_kwargs: (True, {"create": 1, "modify": 0, "delete": 0, "no_change": 0, "ignore": 0, "deploy": 0, "unsupported": 0}))
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args, **_kwargs: True)
    deployments: list[object] = []
    monkeypatch.setattr(
        script,
        "deploy_operator_key_vault_reader",
        lambda request, **_kwargs: deployments.append(request) or SimpleNamespace(
            ok=True, category="success", deployment_requested=True,
            deployment_request_accepted=True, azure_mutation_made=True,
        ),
    )
    monkeypatch.setattr(script, "verify_key_vault", lambda *_args, **_kwargs: _vault())

    code = script.main(["--deploy-operator-reader", *ARGS])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert len(deployments) == 1
    assert identities == [] and readers == []
    assert payload["operator_rbac_deployment_requested"] is True
    assert payload["operator_rbac_deployment_accepted"] is True
    assert payload["operator_assignment_verified"] is True
    assert payload["zero_secrets_verified"] is True
    assert payload["azure_mutation_made"] is True


def test_failed_postdeployment_reader_verification_does_not_retry_metadata(monkeypatch, capsys) -> None:
    script = _configure(monkeypatch)
    identities = [_identity(), _identity()]
    readers = [_reader(ok=False, missing=True), _reader(ok=False, missing=True), _reader(ok=False, missing=False)]
    monkeypatch.setattr(script, "resolve_current_operator", lambda *_args, **_kwargs: identities.pop(0))
    monkeypatch.setattr(script, "verify_operator_key_vault_reader", lambda *_args, **_kwargs: readers.pop(0))
    monkeypatch.setattr(script, "_reader_preview", lambda *_args, **_kwargs: (True, {"create": 1, "modify": 0, "delete": 0, "no_change": 0, "ignore": 0, "deploy": 0, "unsupported": 0}))
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(script, "deploy_operator_key_vault_reader", lambda *_args, **_kwargs: SimpleNamespace(ok=True, category="success", deployment_requested=True, deployment_request_accepted=True, azure_mutation_made=True))
    monkeypatch.setattr(
        script,
        "verify_key_vault",
        lambda *_args, **kwargs: (
            _vault(ok=False)
            if kwargs.get("verify_secret_metadata") is False
            else pytest.fail("metadata must remain gated")
        ),
    )

    code = script.main(["--deploy-operator-reader", *ARGS])
    payload = json.loads(capsys.readouterr().out)

    assert code != 0
    assert payload["operator_assignment_verified"] is False
    assert payload["metadata_verification_attempted"] is False
    assert payload["zero_secrets_verified"] is False


def test_operator_public_payload_allowlist_contains_no_private_ids() -> None:
    script = _script()
    for forbidden in (
        "operator_principal_id", "subscription_id", "tenant_id",
        "vault_resource_id", "role_definition_id", "azure_command",
    ):
        assert forbidden not in script.PUBLIC_RESULT_FIELDS
