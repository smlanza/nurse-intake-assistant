from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _normalized(path: str) -> str:
    return " ".join((ROOT / path).read_text().split()).casefold()


def test_live_key_vault_reference_preserves_frozen_operator_boundaries() -> None:
    runbook = _normalized(
        "docs/runbooks/live-key-vault-deployment-rbac-prerequisites.md"
    )

    for required in (
        "daily_environment_ready=true",
        "scripts/prove_key_vault_live.py --check",
        "--deploy-vault",
        "--verify-vault",
        "--deploy-rbac",
        "--verify-rbac",
        "current readiness receipt",
        "active azure account",
        "default-no",
        "one key vault deployment request",
        "one rbac deployment request",
        "key vault secrets user",
        "exact vault scope",
        "zero secrets",
        "deployment acceptance is not verification",
        "no secret is created or retrieved",
        "credential migration remains deferred",
    ):
        assert required in runbook
    for forbidden in (
        "az role assignment create",
        "az keyvault secret set",
        "az keyvault secret show",
    ):
        assert forbidden not in runbook


def test_progress_and_mapping_record_partial_live_vault_proof_without_overclaim() -> None:
    progress = _normalized("docs/progress.md")
    mapping = _normalized("docs/ai-103-mapping.md")

    assert "secret_metadata_read_failed" in progress
    assert "runtime rbac orchestration and ready gating are implemented offline" in progress
    assert "live daily acceptance remains unproven" in progress
    assert "authorization_scope_mismatch" in progress
    assert "operator key vault reader remains unproven" in progress
    assert "key vault infrastructure is live-deployed" in mapping
    assert "live daily-generation runtime rbac is not yet proven" in mapping
    assert "operator reader authorization and zero-secret metadata proof remain unproven" in mapping


def test_operator_reader_reference_preserves_metadata_only_stop_boundary() -> None:
    runbook = _normalized(
        "docs/runbooks/live-key-vault-deployment-rbac-prerequisites.md"
    )

    for required in (
        "--check-operator-reader",
        "--verify-operator-reader",
        "--deploy-operator-reader",
        "key vault reader",
        "current azure operator",
        "metadata-only",
        "exact vault scope",
        "stop before web app runtime rbac",
        "does not authorize secret-value access",
    ):
        assert required in runbook
    assert "operatorprincipalid=" not in runbook
