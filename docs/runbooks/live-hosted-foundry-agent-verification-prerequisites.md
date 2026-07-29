# Hosted Foundry Agent Verification Implementation Reference

> **Supported operator status:** Step 6 of
> [`daily-azure-operator-runbook.md`](daily-azure-operator-runbook.md) is
> authoritative. The current WebJob trigger-and-correlation path is retired
> from supported operations. This file preserves technical background and
> historical proof semantics only; it is not an executable prerequisite or
> alternate daily workflow.

## Current evidence and decision

The following live boundaries are proven:

- a final fresh daily generation reached READY through hosted application
  readiness and current-artifact equality;
- its generation handoff was prepared successfully;
- the fixed triggered WebJob was discovered successfully; and
- the Web App system identity's exact direct project-scoped Foundry Agent
  Consumer assignment was reused and verified without mutation.

Multiple fresh supervised trigger attempts returned
`trigger_acceptance_ambiguous`. Azure did not expose a safely correlatable
execution record for those attempts. Managed-identity Foundry metadata access
and the fixed-fictional-data invocation are therefore unproven.

The project does not claim that Azure WebJobs are universally impossible. This
specific trigger-and-correlation implementation was not reliably provable
enough for the capstone, so it is retired. Any reuse requires a future explicit
architecture decision with a new supported authorization and proof contract.

## Original purpose and safety boundary

The packaged operation was designed to perform read-only prompt-agent metadata
verification followed by one fixed-fictional invocation from an App Service
system-assigned managed identity. It never submits patient text, persists a
case, sends notifications, repairs RBAC, or establishes production readiness.
This repository-owned execution mechanism and its repository-owned
configuration boundary were offline-tested only.

### Exact operator-approved inventory

Its Exact operator-approved inventory included the resource group, Foundry
account and child project, model deployment, prompt-agent name and exact
immutable prompt-agent version, Linux Web App, hosted origin, project endpoint,
and stable per-agent endpoint. Historical output, portal screenshots, or an
inferred resource name were never valid current prerequisite evidence.

The Exact immutable prompt-agent version was a distinct current prerequisite;
resource existence or RBAC never substituted for version proof.

The old gate began with `az login` and a projected `az account show` using
`subscription:name,state:state,isDefault:isDefault`. Those account operations
now belong only to Step 2 of the canonical runbook.

## Repository-owned boundaries

| Concern | Authoritative implementation |
| --- | --- |
| Foundry deployment and verification | `infra/foundry-only.bicep`, `infra/modules/foundry.bicep`, `scripts/deploy_foundry_infra.py`, `scripts/verify_foundry_infra.py` |
| Prompt-agent lifecycle and immutable-version verification | `src/app/services/foundry_agent_deployment.py`, `scripts/deploy_foundry_agent.py`, `src/app/services/foundry_agent_verification.py`, `scripts/verify_foundry_agent.py` |
| Web App deployment and configuration | `infra/main.bicep`, `infra/modules/web-app.bicep`, `scripts/deploy_web_app_infra.py`, `scripts/verify_web_app_configuration.py` |
| Application package, deployment, and readiness | `src/app/services/web_app_package.py`, `scripts/package_web_app.py`, `scripts/deploy_web_app_code.py`, `scripts/verify_web_app_readiness.py` |
| Consumer RBAC | `infra/foundry-agent-consumer-rbac.bicep`, `scripts/deploy_foundry_agent_consumer_rbac.py`, `scripts/verify_foundry_agent_consumer_rbac.py` |
| Generation handoff | `src/app/services/hosted_foundry_agent_webjob_handoff.py`, `scripts/prepare_hosted_foundry_agent_webjob_handoff.py` |
| WebJob package and deployment | `src/app/services/hosted_foundry_agent_webjob_package.py`, `src/app/services/hosted_foundry_agent_webjob_deployment.py`, `scripts/deploy_hosted_foundry_agent_webjob.py` |
| Fixed hosted execution boundary | `App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py`, `src/app/services/hosted_foundry_agent_webjob_execution.py`, `scripts/run_hosted_foundry_agent_verification.py` |
| Evidence-preserving recovery | `src/app/services/hosted_foundry_agent_webjob_state_recovery.py`, `scripts/recover_hosted_foundry_agent_webjob_state.py`, and canonical exceptional recovery |

Infrastructure, immutable agent routing, application deployment, readiness,
RBAC, WebJob installation/discovery, trigger acceptance, execution correlation,
managed-identity authentication, metadata, and invocation are separate proof
boundaries.

## Generation handoff and discovery semantics

After READY, the separate
`scripts/prepare_hosted_foundry_agent_webjob_handoff.py` boundary validates the
current non-revoked readiness receipt, revalidates the current application
artifact, and performs projected read-only Web App identity and Foundry project
reads without reading Consumer role assignments. It writes private immutable
`generation-handoff.json`. In the normal handoff preparation and preserved
discovery, trigger, reconciliation, and status contracts, operators do not
supply the environment fingerprint and the commands do not emit it. Those
boundaries derive and verify the fingerprint from private immutable evidence.
Exceptional evidence recovery is separate: after inspection, the operator may
pass the exact previously inspected fingerprint through
`--expected-environment-fingerprint` solely as a concurrency and
evidence-matching guard. It is not authorization and no real fingerprint
belongs in documentation.

Handoff preparation may report fail-closed categories including
`current_session_binding_invalid`, `local_package_binding_invalid`,
`hosted_artifact_current_verification_failed`,
`web_app_identity_read_failed`, `web_app_identity_invalid`,
`foundry_project_read_failed`, `foundry_project_invalid`, and
`environment_fingerprint_invalid`. A failure authorizes no WebJob operation.
The historical CLI bound `--config` and `--readiness-receipt`; former
`--live-discover`, trigger, and status stages required the same unchanged
readiness receipt.

The dedicated application package excludes `App_Data`. A separate
generation-bound deterministic ZIP has exactly one `run.py` member and writes
only
`.artifacts/hosted-foundry-agent-webjob-package/verify-hosted-foundry-agent.zip`.
The lifecycle root `.artifacts/hosted-foundry-agent-webjob/` is reserved
exclusively for recognized immutable generation and trigger evidence.

The approved default-no deployment design used
`PUT /api/triggeredwebjobs/verify-hosted-foundry-agent` with
`Content-Type: application/zip` and the fixed
`Content-Disposition: attachment; filename="verify-hosted-foundry-agent.zip"`.
Upload acceptance was distinct from the authoritative fixed-resource
`GET /api/triggeredwebjobs/verify-hosted-foundry-agent`. Kudu is authoritative
for both dedicated installation and discovery; the Azure CLI triggered-WebJob
list is not used. `latest_run` may be null before a trigger. Additional
Kudu-owned top-level fields are ignored.

Successful dedicated deployment proved independent booleans such as
`upload_attempted`, `upload_accepted`, `remote_discovery_attempted`, and
`remote_webjob_discovered`. Its result kept `trigger_attempted` and
`fictional_invocation_proven` false. Failures such as `package_changed`,
`upload_request_invalid`, `upload_throttled`, `upload_service_failed`,
`upload_acceptance_ambiguous`, `discovery_throttled`,
`discovery_service_failed`, `discovery_ambiguous`, and
`discovery_response_invalid` did not authorize retry or trigger. Standalone
discovery used the same Kudu discoverer as post-upload deployment.

## Hosted runtime hardening retained in the implementation

The one-file bootstrap resolves only App Service's absolute `HOME`, places
validated `$HOME/site/wwwroot` first on import search paths, rejects unexpected
preloaded packages, and resolves third-party dependencies only through the
platform-selected Python interpreter. Temporary Kudu staging, the working
directory, `APP_PATH`, inferred Oryx paths, and `WEBJOBS_PATH` are not trusted.

Before former trigger submission, the lifecycle service created
`.artifacts/hosted-foundry-agent-webjob/trigger-reservation.lock`. It was not a
distributed lock across workstations or checkouts. Accepted context used
immutable `accepted-trigger.json`; ambiguous acceptance used
`blocked-trigger.json`; correlated terminal state used separate
`terminal-outcome.json`. Descriptor-relative no-follow reads reject symlinked
or nonregular state.

The historical implementation kept the separate Azure CLI `run` and `log`
adapters. Trigger acceptance without treating it as verification success was a
durable invariant. A terminally successful WebJob run proves the fixed
invocation completed only under the original accepted-receipt result contract;
that outcome was never obtained for the fresh ambiguous attempts and must not
be inferred.

## Retired operations

The executable still recognizes `--live-trigger`,
`--live-reconcile-blocked-trigger`, and `--live-status`. These strings are
documented only to identify retired modes:

- the old trigger mode attempted one request after creating immutable local
  reservation evidence;
- the old blocked-trigger reconciliation mode constructs no trigger runner and
  was designed for exactly one WebJob history read;
- runs before the blocked trigger's immutable UTC lower bound were discarded;
- exactly one eligible known run could create private exact-run correlation;
- Zero or multiple eligible runs remain blocked and do not justify a retrigger;
  and
- the old status mode never falls back to the latest run.

Earlier workflow text said “do not run the trigger command again,” then
proposed one explicitly authorized WebJob trigger request and one separately
authorized receipt-correlated status read in other generations. That sequence
is superseded. Trigger acceptance is not terminal execution success. The
historical rule was trigger acceptance without treating it as verification
success. Trigger, blocked-trigger reconciliation, status, metadata proof,
and invocation remain separate in the code, but none is a supported current
operator continuation.

Do not run `--live-trigger`, `--live-reconcile-blocked-trigger`, or
`--live-status`. Do not retry with alternate credentials, broaden accepted
history, poll, sleep, use repeated sleeps, run repeated verifier calls, use
General-purpose shell polling loops, make ad hoc Azure changes, modify App
Service settings, use interactive Kudu or SSH, or submit arbitrary prompts.

## Remaining unproven claims

RBAC existence, WebJob installation, fixed-name discovery, credential/client
construction, hosted application readiness, and historical trigger attempts do
not prove:

- system-assigned managed-identity token acquisition;
- current Foundry authorization;
- project or prompt-agent metadata access from the hosted process;
- exclusive-route metadata verification by that hosted process;
- fixed-fictional agent invocation;
- application output-contract validation;
- live Foundry structured extraction; or
- any clinical or production behavior.

## Fail-fast stop conditions

The retired hosted operation remains stopped for missing, stale, ambiguous,
malformed, mismatched, unauthorized, or historical-only evidence. Immutable
lifecycle evidence must not be deleted or edited. Use the evidence-preserving
exceptional recovery section of the canonical runbook when it blocks a new
generation.

No recovery, handoff, discovery, READY, RBAC, or operator approval result
revives the retired execution path. A future hosted validation mechanism may
use a different execution boundary.
