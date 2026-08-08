# Live Key Vault Deployment And RBAC Proof Reference

## Boundary

This is a focused technical reference, not an alternate daily Azure workflow.
First obtain fresh `daily_environment_ready=true` through the canonical daily
operator runbook. Every command below consumes the same current readiness
receipt, revalidates its configuration/generation/correlation state, and checks
the active Azure account against its private subscription identity.

The workflow proves only the repository-owned vault and the existing Web App
system identity's direct **Key Vault Secrets User** assignment at exact vault
scope. It creates no secret, reads no secret value or version, changes no
application setting, and migrates no credential. Credential migration remains
deferred, as do application Key Vault use, App Service references, retrieval,
rotation, and production secret management.

## Offline contract check

Run from the repository root:

```bash
.venv/bin/python scripts/prove_key_vault_live.py --check --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

Check mode constructs no Azure runner. Success requires current READY evidence
and the exact local vault/RBAC Bicep contracts.

## Vault deployment or safe reuse

The following command first revalidates READY/account state and performs an
independent read-only vault inspection. Exact verified reuse makes no mutation.
A conclusively missing vault gets a sanitized preview and a default-no prompt
bound to current evidence. Approval permits one Key Vault deployment request;
the command then independently verifies resource identity, successful
provisioning, RBAC mode, absent legacy policies, and zero secrets. Deployment
acceptance is not verification.

```bash
.venv/bin/python scripts/prove_key_vault_live.py --deploy-vault --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

Run the independent read-only verifier separately:

```bash
.venv/bin/python scripts/prove_key_vault_live.py --verify-vault --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

The zero-object proof uses only a bounded metadata list/count operation with a
maximum of one item. No secret is created or retrieved, and no version or value
operation is available through this CLI.

## Current-operator metadata-only authorization

If vault verification stops at `secret_metadata_read_failed`, use the dedicated
current Azure operator **Key Vault Reader** boundary. It privately resolves the
signed-in user from the same READY-bound account, revalidates the exact vault,
and accepts only one direct Key Vault Reader assignment at exact vault scope.
The caller cannot supply a principal ID. This metadata-only role is distinct
from Key Vault Secrets User and does not authorize secret-value access.

Check the local Bicep and identity contracts without an Azure call:

```bash
.venv/bin/python scripts/prove_key_vault_live.py --check-operator-reader --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

Perform the independent read-only identity, vault, and exact-assignment
preflight:

```bash
.venv/bin/python scripts/prove_key_vault_live.py --verify-operator-reader --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

The deployment/reuse command reuses one exact direct assignment without a
prompt. Only a conclusively missing assignment reaches a separate default-no,
current-evidence-bound prompt and at most one repository-owned Bicep request.
It independently verifies the assignment before retrying the existing bounded
secret-metadata count:

```bash
.venv/bin/python scripts/prove_key_vault_live.py --deploy-operator-reader --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

Successful output must prove both `operator_assignment_verified=true` and
`zero_secrets_verified=true`. Stop before Web App runtime RBAC. The operator
Reader assignment proves metadata authorization only and neither proves nor
performs secret retrieval.

## Exact RBAC deployment or safe reuse

Only in the separate resumed runtime slice after vault verification, run the
RBAC stage. It first resolves the
existing Web App's system-assigned identity, the exact Azure-returned vault
identity, and current direct/inherited assignments. One exact direct assignment
is reused without mutation. Only a conclusively missing assignment reaches a
separate default-no prompt; approval permits one RBAC deployment request using
the repository-owned Bicep entry point. There is no ad hoc CLI role-assignment
mutation or broader-role fallback.

```bash
.venv/bin/python scripts/prove_key_vault_live.py --deploy-rbac --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

Run the independent read-only verifier separately:

```bash
.venv/bin/python scripts/prove_key_vault_live.py --verify-rbac --config .env.daily-azure.local --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json --json
```

Success requires exactly one direct assignment for the current Web App
principal, fixed role, and exact vault scope. Zero after deployment, duplicate,
inherited-only, different-principal, different-role, broader-role, wrong-scope,
or malformed evidence fails closed. RBAC deployment acceptance is not
assignment verification and RBAC verification does not prove retrieval.

## Stop conditions

Stop on invalid/revoked/stale READY, account mismatch, ambiguous identity,
unsafe preview, changed approval evidence, unowned vault, failed zero-secret
metadata proof, malformed Azure output, or nonexact RBAC. Do not recreate the
daily environment, retry a mutation, repair manually, broaden a role, or proceed
to secret retrieval. End-of-day cleanup remains Step 8 of the canonical daily
operator runbook.
