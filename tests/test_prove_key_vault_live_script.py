import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _script():
    return importlib.import_module("scripts.prove_key_vault_live")


def test_import_is_inert(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules.pop("scripts.prove_key_vault_live", None)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("import must not call Azure"),
    )
    _script()


def test_check_constructs_no_runner(monkeypatch, capsys) -> None:
    script = _script()
    context = _context()
    monkeypatch.setattr(script, "_receipt_context", lambda _args: context)
    monkeypatch.setattr(
        script,
        "_create_runner",
        lambda: pytest.fail("check must not construct Azure runner"),
    )

    exit_code = script.main(
        [
            "--check",
            "--config", ".env.daily-azure.local",
            "--readiness-receipt", ".artifacts/daily-azure-rebuild/readiness-receipt.json",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["ready_verified"] is True
    assert payload["vault_contract_valid"] is True
    assert payload["azure_operation_attempted"] is False


def test_invalid_or_stale_ready_fails_before_runner(monkeypatch, capsys, tmp_path) -> None:
    script = _script()
    created: list[bool] = []
    monkeypatch.setattr(script, "_create_runner", lambda: created.append(True))
    monkeypatch.setattr(script, "_receipt_context", lambda _args: None)

    exit_code = script.main(
        [
            "--verify-vault",
            "--config", ".env.daily-azure.local",
            "--readiness-receipt", str(tmp_path / "missing.json"),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert payload["category"] == "ready_invalid"
    assert payload["azure_operation_attempted"] is False
    assert created == []


def _context():
    config = SimpleNamespace(
        location="eastus2",
        project_name="nurse-intake",
        environment_name="daily",
    )
    receipt = SimpleNamespace(
        resource_group="fictional-daily-rg",
        web_app_name="fictional-web-app",
        run_epoch="b" * 32,
    )
    return (
        config,
        receipt,
        "00000000-0000-0000-0000-000000000001",
        "kv123456789abcd",
    )


def _vault_result(*, ok: bool, missing: bool = False):
    return SimpleNamespace(
        ok=ok,
        category="success" if ok else "vault_missing",
        vault_contract_valid=True,
        azure_request_attempted=True,
        vault_missing_conclusive=missing,
        vault_verified=ok,
        resource_identity_verified=ok,
        rbac_authorization_enabled=ok,
        legacy_access_policies_absent=ok,
        zero_secrets_verified=ok,
        secret_metadata_count=0 if ok else None,
    )


def _rbac_result(*, ok: bool, missing: bool = False):
    subscription_id = "00000000-0000-0000-0000-000000000001"
    vault_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/fictional-daily-rg/"
        "providers/Microsoft.KeyVault/vaults/kv123456789abcd"
    )
    return SimpleNamespace(
        ok=ok,
        category="success" if ok else "assignment_missing",
        azure_request_attempted=True,
        web_app_identity_verified=True,
        vault_identity_verified=True,
        assignment_missing_conclusive=missing,
        assignment_verified=ok,
        matching_assignment_count=1 if ok else 0,
        subscription_id=subscription_id,
        web_app_principal_id="00000000-0000-0000-0000-000000000002",
        vault_resource_id=vault_id,
        role_definition_id=(
            f"/subscriptions/{subscription_id}/providers/"
            "Microsoft.Authorization/roleDefinitions/"
            "4633458b-17de-408a-b874-0445c86b69e6"
        ),
    )


def _live_args(mode: str) -> list[str]:
    return [
        mode,
        "--config", "fictional-config",
        "--readiness-receipt", "fictional-receipt",
        "--json",
    ]


def test_exact_vault_reuse_performs_no_mutation_or_approval(monkeypatch, capsys) -> None:
    script = _script()
    monkeypatch.setattr(script, "_receipt_context", lambda _args: _context())
    monkeypatch.setattr(script, "_create_runner", lambda: object())
    monkeypatch.setattr(script, "_account_matches", lambda *_args: True)
    monkeypatch.setattr(script, "verify_key_vault", lambda *_args, **_kwargs: _vault_result(ok=True))
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args: pytest.fail("reuse needs no approval"))
    monkeypatch.setattr(script, "deploy_key_vault", lambda *_args, **_kwargs: pytest.fail("reuse must not deploy"))

    exit_code = script.main(_live_args("--deploy-vault"))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["vault_reused"] is True
    assert payload["azure_mutation_made"] is False


def test_missing_vault_gets_one_approved_deployment_then_independent_verification(
    monkeypatch, capsys
) -> None:
    script = _script()
    vault_results = iter([
        _vault_result(ok=False, missing=True),
        _vault_result(ok=False, missing=True),
        _vault_result(ok=True),
    ])
    deployments: list[object] = []
    monkeypatch.setattr(script, "_receipt_context", lambda _args: _context())
    monkeypatch.setattr(script, "_fresh_context_matches", lambda *_args: True)
    monkeypatch.setattr(script, "_create_runner", lambda: object())
    monkeypatch.setattr(script, "_account_matches", lambda *_args: True)
    monkeypatch.setattr(script, "verify_key_vault", lambda *_args, **_kwargs: next(vault_results))
    monkeypatch.setattr(script, "verify_key_vault_rbac", lambda *_args, **_kwargs: _rbac_result(ok=False, missing=True))
    monkeypatch.setattr(script, "_preview", lambda *_args, **_kwargs: (True, {"create": 1, "modify": 0, "delete": 0, "no_change": 0, "ignore": 0, "deploy": 0, "unsupported": 0}))
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args: True)

    def deploy(request, **_kwargs):
        deployments.append(request)
        return SimpleNamespace(
            ok=True,
            category="success",
            deployment_requested=True,
            deployment_request_accepted=True,
            azure_mutation_made=True,
        )

    monkeypatch.setattr(script, "deploy_key_vault", deploy)

    exit_code = script.main(_live_args("--deploy-vault"))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert len(deployments) == 1
    assert payload["vault_deployment_accepted"] is True
    assert payload["vault_verified"] is True
    assert payload["zero_secrets_verified"] is True


def test_rbac_reuse_performs_no_mutation(monkeypatch, capsys) -> None:
    script = _script()
    monkeypatch.setattr(script, "_receipt_context", lambda _args: _context())
    monkeypatch.setattr(script, "_create_runner", lambda: object())
    monkeypatch.setattr(script, "_account_matches", lambda *_args: True)
    monkeypatch.setattr(script, "verify_key_vault_rbac", lambda *_args, **_kwargs: _rbac_result(ok=True))
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args: pytest.fail("reuse needs no approval"))
    monkeypatch.setattr(script, "deploy_key_vault_rbac", lambda *_args, **_kwargs: pytest.fail("reuse must not deploy"))

    exit_code = script.main(_live_args("--deploy-rbac"))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["rbac_assignment_reused"] is True
    assert payload["rbac_assignment_verified"] is True
    assert payload["azure_mutation_made"] is False


def test_changed_postapproval_rbac_evidence_blocks_before_deployment(monkeypatch, capsys) -> None:
    script = _script()
    results = iter([_rbac_result(ok=False, missing=True), _rbac_result(ok=False, missing=True)])
    monkeypatch.setattr(script, "_receipt_context", lambda _args: _context())
    monkeypatch.setattr(script, "_fresh_context_matches", lambda *_args: True)
    monkeypatch.setattr(script, "_create_runner", lambda: object())
    monkeypatch.setattr(script, "_account_matches", lambda *_args: True)
    monkeypatch.setattr(script, "verify_key_vault_rbac", lambda *_args, **_kwargs: next(results))
    monkeypatch.setattr(script, "_preview", lambda *_args, **_kwargs: (True, {"create": 1, "modify": 0, "delete": 0, "no_change": 0, "ignore": 0, "deploy": 0, "unsupported": 0}))
    monkeypatch.setattr(script, "prompt_for_approval", lambda *_args: True)
    original_evidence = script._evidence
    evidence_calls = 0

    def changed_evidence(*args, **kwargs):
        nonlocal evidence_calls
        evidence_calls += 1
        evidence = original_evidence(*args, **kwargs)
        assert evidence is not None
        if evidence_calls == 2:
            return script.KeyVaultDeploymentEvidence(
                **{**evidence.__dict__, "template_digest": "c" * 64}
            )
        return evidence

    monkeypatch.setattr(script, "_evidence", changed_evidence)
    monkeypatch.setattr(script, "deploy_key_vault_rbac", lambda *_args, **_kwargs: pytest.fail("stale approval must not deploy"))

    exit_code = script.main(_live_args("--deploy-rbac"))
    payload = json.loads(capsys.readouterr().out)

    assert exit_code != 0
    assert payload["category"] == "approval_evidence_stale"
    assert payload["rbac_deployment_requested"] is False


def test_public_payload_allowlist_excludes_private_evidence() -> None:
    script = _script()
    allowed = set(script.PUBLIC_RESULT_FIELDS)

    for forbidden in (
        "subscription_id", "tenant_id", "principal_id", "resource_id",
        "vault_uri", "command", "raw_output", "secret_name", "secret_value",
    ):
        assert forbidden not in allowed


def test_no_ad_hoc_role_assignment_mutation_exists() -> None:
    text = (ROOT / "scripts/prove_key_vault_live.py").read_text()
    service = (ROOT / "src/app/services/key_vault_live_proof.py").read_text()

    assert "az role assignment create" not in (text + service)
    assert "key-vault-secrets-user-rbac.bicep" in service
