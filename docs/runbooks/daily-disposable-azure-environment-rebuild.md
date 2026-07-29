# Daily Disposable Azure Environment Rebuild

> **Canonical procedure moved:** Follow
> [`daily-azure-operator-runbook.md`](daily-azure-operator-runbook.md) for the
> only supported normal daily Azure sequence. This file retains implementation
> background and a historical stage index only. It is not an alternate
> operator procedure.

## Daily command summary

The canonical runbook owns `scripts/daily_azure.sh check`,
`scripts/daily_azure.sh start`, `scripts/daily_azure.sh inspect`, and
`scripts/daily_azure.sh stop`. Their arguments and order are intentionally not
repeated here.

The wrapper is only a convenience interface. The Python CLIs remain the
authoritative implementation boundaries:
`scripts/rebuild_daily_azure_environment.py` and
`scripts/cleanup_daily_azure_environment.py`. `start` already includes startup
cleanup inspection through the startup cleanup preflight; `inspect` is optional
and read-only; `stop` is the explicit end-of-day cleanup. Final absence is
proved by `resource_group_absent=true` and
`foundry_tombstones_absent=true`.

## Normal Daily Guided Path

The ordered Normal Daily Guided Path, including offline `--check`, explicit
`--live`, current-run approval, and the required
`daily_environment_ready=true` proof, is now solely in the canonical runbook.
The coordinator returns success immediately at verified application-hosting
readiness. Its historical detailed stages below remain a troubleshooting,
recovery, audit index, not commands to execute.

The coordinator stops with
`resource_group_ownership_approval_required` rather than adopting an unowned
group. Approved application deployment uses an immutable transient handoff.

### Out of scope for daily readiness

Consumer RBAC, WebJob discovery or execution, managed-identity Foundry access,
metadata verification, agent invocation, live inference, and notification
delivery remain outside READY. Do not continue into them automatically after
daily success.

## 1. Purpose and lifecycle

The canonical file is the durable checked-in procedure; command output is fresh
current-session evidence. READY and NOT READY describe only the current
disposable generation. Deletion immediately returns the environment to NOT
READY and expires its evidence. See the canonical runbook for the lifecycle.

## 2. Required operator inputs

The ignored `.env.daily-azure.local` is the normal configuration source. Never
commit subscription IDs, tenant IDs, principal IDs, complete ARM resource IDs,
access tokens, bearer tokens, secrets, endpoints, real contact data, or patient
data. The canonical prerequisite section owns the complete list.

## 3. Local preflight

The wrapper now owns the normal local validation. The implementation still
delegates to the offline modes of cleanup and rebuild. Do not treat an earlier
check as live proof.

## 4. Authentication and subscription

Authentication and projected current-account verification are Step 2 of the
canonical runbook. No alternate account sequence is defined here.

## 5. Resource group creation or explicit adoption

The coordinator creates only an absent configured group after approval and
reuses only conclusively healthy repository-owned state. Explicit manual
adoption is an exceptional operator decision, never an automatic continuation.

## 6. Foundry infrastructure

The implementation boundaries remain `scripts/deploy_foundry_infra.py` and
`scripts/verify_foundry_infra.py`. Deployment and read-only verification are
separate; the wrapper coordinator owns their normal ordering and arguments.

## 7. Prompt-agent provisioning and immutable-version proof

The implementation boundaries remain, in order,
`scripts/deploy_foundry_agent.py`,
`scripts/configure_foundry_agent_endpoint_routing.py`, and
`scripts/verify_foundry_agent.py`. Provisioning, routing mutation, read-only
verification, and invocation remain separate authorization boundaries.

## 8. Web App infrastructure

The implementation boundary remains `scripts/deploy_web_app_infra.py`.
The coordinator owns the normal preview, current-run approval, deployment, and
reuse policy.

## 9. Web App configuration verification

The read-only implementation boundary remains
`scripts/verify_web_app_configuration.py`. It proves configuration, not current
application code.

## 10. Package creation

The deterministic implementation boundary remains
`scripts/package_web_app.py`. Packaging proves neither upload acceptance nor
hosted readiness.

## 11. Web App code deployment

The implementation boundary remains `scripts/deploy_web_app_code.py`.
Deployment-request acceptance is not terminal deployment or readiness proof.

## 12. Hosted readiness verification

The read-only implementation boundary remains
`scripts/verify_web_app_readiness.py`. A healthy old worker cannot produce
READY; exact current-artifact equality is required.

## 13. Optional standalone Consumer RBAC deployment

The separate implementation boundary remains
`scripts/deploy_foundry_agent_consumer_rbac.py`. Its supported optional
operator use is Step 5 of the canonical runbook.

## 14. Optional standalone Consumer RBAC verification

The focused deployment CLI performs its own exact post-deployment verification.
The lower-level read-only implementation boundary remains
`scripts/verify_foundry_agent_consumer_rbac.py`.

## 15. Optional standalone Consumer RBAC and WebJob troubleshooting

`scripts/run_hosted_foundry_agent_verification.py` remains in the repository,
but the current trigger-and-correlation path is retired from supported
operations. Standalone discovery does not itself authorize a trigger, status
read, managed-identity access, metadata verification, or agent invocation.
Retired trigger, reconciliation, and status modes require a future explicit
architecture decision before reuse.

## 16. Daily environment-ready declaration

Only the current canonical Step 4 success contract may establish READY. No
historical or specialized runbook supplies a substitute declaration.

## 17. End-of-day cleanup and evidence expiry

Only canonical Step 8 defines normal cleanup. The implementation remains
ownership-scoped, default-no, synchronous, and verification-driven.

## 18. Fail-fast rules

Malformed, unknown, stale, mismatched, unowned, or ambiguous evidence fails
closed. Do not improvise repairs, retry mutations, or infer proof from resource
existence.

If immutable WebJob evidence blocks a new generation, follow the exceptional
procedure in the canonical runbook. The specialized implementation background
is retained in
[`recover-stale-hosted-foundry-agent-webjob-state.md`](recover-stale-hosted-foundry-agent-webjob-state.md).

## 19. Cost control

The environment remains short-lived and disposable. The canonical end-of-day
cleanup is the sole normal cost-control procedure.
