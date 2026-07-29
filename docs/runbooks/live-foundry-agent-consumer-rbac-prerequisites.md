# Foundry Agent Consumer RBAC Implementation Reference

> **Canonical procedure moved:** Use Step 5 of
> [`daily-azure-operator-runbook.md`](daily-azure-operator-runbook.md) for the
> only supported optional Consumer RBAC operator command. This file retains
> narrow implementation and failure-contract background. It is not an
> alternate daily workflow.

## Boundary

The focused deployment CLI consumes the current coordinator readiness receipt
and performs an immediate read-only check for exactly one direct Foundry Agent
Consumer assignment. It accepts only the current Web App system-assigned
principal, fixed Consumer role, exact Foundry project scope, and deterministic
repository-owned assignment.

A missing, revoked, stale, configuration-mismatched, account-mismatched, or
scope-mismatched readiness receipt fails closed. Operators must obtain a new
READY generation through the canonical runbook; they must not edit the receipt
or reconstruct identifiers.

The RBAC boundary does not acquire a managed-identity token, run a WebJob, read
Foundry metadata, invoke an agent or model, change providers, send
notifications, or establish production or clinical readiness.

## Success meanings

Successful reuse has these decisive fields:

```json
{
  "ok": true,
  "category": "success",
  "operation": "deploy_foundry_agent_consumer_rbac",
  "mode": "live",
  "rbac_handoff_validated": true,
  "assignment_reused": true,
  "assignment_verified": true,
  "azure_operation_attempted": true,
  "azure_mutation_made": false,
  "deployment_request_accepted": false
}
```

This proves read-only reuse of one exact direct assignment. It proves no hosted
identity behavior.

When the assignment is conclusively missing, the CLI produces fresh sanitized
evidence and requests one default-no approval. Successful creation has:

```json
{
  "ok": true,
  "category": "success",
  "operation": "deploy_foundry_agent_consumer_rbac",
  "mode": "live",
  "rbac_handoff_validated": true,
  "assignment_reused": false,
  "assignment_verified": true,
  "azure_operation_attempted": true,
  "azure_mutation_made": true,
  "deployment_request_accepted": true
}
```

Operator approval authorizes one exact mutation; it is not verification.
Success requires the immediate separate read-only verifier to prove the final
direct assignment. Deployment acceptance without verification is
`consumer_rbac_verification_failed`.

## Fail-closed categories

The boundary rejects inherited-only access, duplicates, mismatched
principal/role/scope evidence, unsafe or malformed previews, and stale
coordinator handoffs. Important sanitized categories include:

- `invalid_configuration`;
- `rbac_handoff_invalid`;
- `rbac_handoff_account_mismatch`;
- `rbac_handoff_azure_scope_mismatch`;
- `consumer_rbac_preverification_failed`;
- `consumer_rbac_preview_unsafe`;
- `consumer_rbac_operator_declined`;
- `approval_evidence_stale`;
- `consumer_rbac_verification_failed`;
- `template_contract_invalid`; and
- `deployment_failed`.

No failure category authorizes manual role assignment, broader scope,
historical evidence reuse, alternate credentials, repeated mutation, or
receipt editing. Correct the stated prerequisite and restart with Step 1 of the
canonical runbook.

## Authoritative implementation

- `infra/foundry-agent-consumer-rbac.bicep`
- `infra/modules/foundry-agent-consumer-rbac.bicep`
- `src/app/services/foundry_agent_consumer_rbac_deployment.py`
- `src/app/services/foundry_agent_consumer_rbac_verification.py`
- `scripts/deploy_foundry_agent_consumer_rbac.py`
- `scripts/verify_foundry_agent_consumer_rbac.py`

The verifier resolves the Foundry project through Azure's returned resource ID;
operators must never concatenate a project resource ID. Raw Azure output,
identifiers, endpoints, commands, errors, and unrelated role assignments are
not part of the sanitized result.
