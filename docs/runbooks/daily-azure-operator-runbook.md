# Daily Azure Operator Runbook

## Purpose and scope

This is the only normal operator-facing Azure procedure for the Nurse Intake
Assistant. Follow Steps 1 through 8 in order for every disposable Azure
workday. Other Azure runbooks are technical background or exceptional recovery
references; they do not define an alternate daily sequence.

The normal workflow is:

```text
scripts/daily_azure.sh check
-> verify az account
-> scripts/daily_azure.sh start
-> when enabled, verify current Web App -> Key Vault runtime RBAC
-> verify daily_environment_ready=true
-> optionally verify Consumer RBAC when required
-> perform development/demo work
-> scripts/daily_azure.sh stop
```

This is a fictional-data-only capstone procedure. It does not establish
production or clinical readiness. AI output remains advisory and requires
human nurse review.

## Fixed operator prerequisites

Run every command from the repository root. Before starting, require:

- the repository virtual environment at `.venv/`;
- an ignored, reviewed `.env.daily-azure.local` created from
  `.env.daily-azure.example`;
- Azure CLI and Bicep tooling;
- interactive Azure CLI authentication to the intended enabled subscription;
- only fictional patient and contact data; and
- authority to review each default-no Azure mutation prompt.

Keep the stable, non-secret daily configuration in
`.env.daily-azure.local`. Do not put generation-specific values into the
checked-in example. Never commit `.env.daily-azure.local`,
`infra/foundry-only.bicepparam`, `.env.foundry-agent.local`, `.artifacts/`,
captured live command output, or operator evidence notes.

Never commit or paste into documentation subscription or tenant IDs, principal
IDs, complete resource IDs, fingerprints, manifest digests, endpoints, tokens,
credentials, identity headers, connection strings, secrets, real contact
information, or patient data. Use placeholders in documentation and keep any
generation-specific recovery values only in an approved ignored evidence
location.

Set `ENABLE_KEY_VAULT_RUNTIME_AUTHORIZATION=true` only when the daily
generation requires Key Vault runtime access. This is a stable Boolean feature
selection, not an identity setting: never add the Web App principal, vault ARM
ID, role-assignment ID, or assignment GUID to configuration.

## Step 1 — Validate the local contract

From the repository root, preserve existing work and run the offline wrapper
check:

```bash
pwd
git status --short
scripts/daily_azure.sh check
```

The wrapper validates both cleanup and rebuild contracts with
`.env.daily-azure.local`. It makes no Azure or HTTP call. Use
`scripts/daily_azure.sh check --config <ignored-config-file>` only when the
operator has intentionally selected a different ignored daily configuration.

Stop on a missing configuration, interpreter, dependency, local contract, or
offline check failure. Correct the local cause and restart at Step 1. Do not
continue because an earlier session passed.

## Step 2 — Verify Azure authentication

Authenticate interactively when required, then inspect only the projected
account fields:

```bash
az login

az account show \
  --query "{subscription:name,state:state,isDefault:isDefault}" \
  --output table
```

Confirm by subscription name that this is the intended subscription, that its
state is `Enabled`, and that it is the intended default selection. This check
is read-only; `az login` changes only the operator's authentication session.

Stop if authentication fails, the subscription is wrong or ambiguous, or the
subscription is not enabled. Do not try alternate credentials or run `start`
until the operator corrects the account context.

## Step 3 — Start or reuse the environment

Run the guided coordinator in an interactive terminal:

```bash
scripts/daily_azure.sh start
```

`start` reruns the offline rebuild contract, verifies the current account, and
performs the authoritative startup cleanup preflight. It either safely reuses
the exact healthy repository-owned environment or guides a fresh disposable
build. The preflight independently inspects bounded repository-owned Foundry
`AIServices`, Speech `SpeechServices`, and the exact deterministic Key Vault
tombstone; when any remains, it requires the existing explicit approval and
final absence proof before any resource-group creation. Do not run destructive
cleanup before `start`.

Review every sanitized summary. The default, EOF, malformed input, or `n`
declines that stage. Approval is current-run and evidence-bound; never infer
approval from an earlier run. Depending on verified state, approved stages may
create or delete disposable resources, deploy infrastructure, configure
immutable routing, establish the current Web App's exact Key Vault Secrets User
assignment, or deploy the current application artifact. A conclusively missing
runtime assignment enters only the repository Bicep path under a fresh,
evidence-bound default-no approval.

Stop on unowned, wrong-location, ambiguous, malformed, conflicting, or drifted
resources. Do not adopt, retag, repair, or delete them ad hoc. Stop on any
coordinator failure and use its sanitized category to correct only the stated
prerequisite before restarting at Step 1.

## Step 4 — Confirm the READY boundary

Do not use the disposable environment until the current `start` result contains
all of these decisive fields:

```text
ok=true
category=success
daily_environment_ready=true
hosted_readiness_verified=true
application_artifact_current=true
```

When `ENABLE_KEY_VAULT_RUNTIME_AUTHORIZATION=true`, also require:

```text
key_vault_runtime_authorization_enabled=true
key_vault_verified=true
web_app_identity_verified=true
key_vault_secrets_user_assignment_verified=true
```

READY proves current Foundry infrastructure, prompt-agent configuration,
exclusive immutable routing, Web App configuration, application deployment or
safe artifact reuse, exact artifact equality, and hosted application readiness.
When Key Vault runtime authorization is enabled, it also proves exactly one
direct Key Vault Secrets User assignment from the current-generation Web App
system identity to the exact current vault. Deployment acceptance, inherited
access, a prior principal, or a prior READY receipt cannot satisfy that proof.

The following fields may correctly remain `false` without invalidating READY:

```text
consumer_rbac_verified
webjob_discovered
webjob_triggered
webjob_status_read
managed_identity_verification_performed
agent_invoked
```

These boundaries are outside READY:

- Foundry Agent Consumer RBAC;
- human operator Key Vault Reader metadata authorization;
- Key Vault secret retrieval and zero-secret metadata proof;
- WebJob trigger acceptance or execution;
- managed-identity Foundry access;
- metadata verification;
- agent invocation and live AI inference; and
- email or SMS delivery.

If any required success field is missing or false, the environment is NOT
READY. Historical output, screenshots, a prior readiness receipt, resource
existence, and deployment-request acceptance cannot replace current proof.

### Focused App Service Authentication v2 acceptance

Run this only when approved work specifically requires the one-time live
Authentication v2 acceptance against the exact current READY generation. Keep
the existing Entra tenant and application/client identifiers operator-local;
do not add them to repository configuration or evidence files.

First run the offline/current-generation check, substituting the two existing
non-secret identifiers only in the operator's local shell:

```bash
.venv/bin/python scripts/accept_web_app_authentication.py \
  --check \
  --config .env.daily-azure.local \
  --client-application-id "$OPERATOR_ENTRA_APPLICATION_ID" \
  --tenant-id "$OPERATOR_ENTRA_TENANT_ID" \
  --json
```

Require `ok=true`, `current_generation_verified=true`, and
`local_contract_validated=true`. Then run the supervised live boundary:

```bash
.venv/bin/python scripts/accept_web_app_authentication.py \
  --live \
  --config .env.daily-azure.local \
  --client-application-id "$OPERATOR_ENTRA_APPLICATION_ID" \
  --tenant-id "$OPERATOR_ENTRA_TENANT_ID" \
  --json
```

The live command independently proves current account and Web App identity,
current hosted readiness and artifact equality, and the disabled current auth
state. It accepts only the validation deployment wrapper plus the exact
`authsettingsV2` change, presents a sanitized default-no approval, rereads all
approval-bound evidence, makes at most one auth-only deployment request using
a local projection from the authoritative Web App Bicep, and separately proves
the resulting configuration, anonymous `200` readiness
routes, protected-route `401` responses, and unchanged hosted readiness.

Stop on any sanitized failure category. Do not use `az webapp auth` mutation
commands, broaden the Bicep scope, retry automatically, or treat deployment
acceptance as verification. Authenticated interactive sign-in and application
authorization remain separate work.

## Step 5 — Optionally verify Consumer RBAC

Skip this step unless the approved development or demo slice specifically
requires the Web App system identity's direct project-scoped Foundry Agent
Consumer assignment. READY does not require it.

Run the focused command with the current readiness receipt:

```bash
set -o pipefail

.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --live \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  .venv/bin/python -m json.tool
```

The command first performs read-only account, identity, project, and assignment
verification. When the exact direct assignment already exists, successful
reuse requires:

```text
ok=true
assignment_reused=true
assignment_verified=true
azure_mutation_made=false
```

When the assignment is conclusively missing, the same command presents a fresh
sanitized preview and a default-no approval for one repository-owned
project-scoped assignment. Azure deployment acceptance alone is not success;
the command must finish with `assignment_verified=true`. Operator approval
authorizes the one proposed mutation but does not itself verify the assignment.

Stop on a missing or stale handoff, inherited-only access, duplicate or
mismatched assignments, unsafe preview, authorization failure, declined
approval, stale approval evidence, deployment failure, or failed
post-deployment verification. Do not use an ad hoc role-assignment command,
broaden the scope, or retry without correcting the cause.

## Step 6 — Understand hosted WebJob validation status

No hosted WebJob execution is part of normal operation.

The current live evidence proves that a fresh READY generation was prepared for
handoff, the fixed triggered WebJob was discovered, and the Web App identity's
direct project-scoped Consumer assignment was reused and verified. Multiple
fresh supervised trigger attempts returned
`trigger_acceptance_ambiguous`. Azure exposed no execution record that could be
safely correlated to those attempts.

Therefore:

- hosted managed-identity Foundry metadata access remains unproven;
- the fixed fictional Foundry agent invocation remains unproven; and
- the current trigger-and-correlation implementation is retired from supported
  operator use because it was not reliably provable enough for this capstone.

This is not a claim that Azure WebJobs are universally impossible. It is a
project decision about this specific implementation.

The CLI still exposes `--live-trigger`,
`--live-reconcile-blocked-trigger`, and `--live-status` for the preserved
implementation. They are retired operations, not troubleshooting suggestions
or normal commands. Do not run them unless a future explicit architecture
decision reintroduces a supported hosted validation mechanism and defines new
authorization and proof rules.

Read-only handoff preparation and WebJob discovery are also outside the normal
daily workflow. Their successful historical use proves generation binding and
fixed WebJob registration respectively; neither proves trigger acceptance,
execution, identity access, metadata, invocation, or inference.

### Retired SSH metadata mode

`--live-metadata-verification` is retired and unsupported. The compatibility
option returns a deterministic sanitized rejection before configuration proof,
approval, service construction, tunnel startup, probes, remote execution,
credential construction, metadata access, or Agent invocation.

Operators must not forward, retrieve, inspect, synthesize, or override App
Service runtime identity markers. They belong only to the application-worker
identity environment and remain outside the operator and SSH transport
boundary. Do not retry SSH metadata execution, substitute the retired WebJob
trigger-and-correlation path, or improvise another command or transport.

`--live-tunnel` remains only the documented non-invoking technical proof: one
owned tunnel, listener readiness, two fixed `APP_PATH` probes, one packaged
non-invoking check, and deterministic cleanup and reaping. Hosted metadata or
invocation proof requires a future separately approved architecture decision.
No replacement hosted execution topology is currently selected.

## Step 7 — Use the environment

Perform only the approved development, testing, or demonstration slice. Keep
the hosted application in its mock-safe provider posture with notifications
suppressed unless a separately reviewed scope explicitly changes that
boundary. Use only fictional data and retain human nurse review.

For the local mock demo, no Azure proof is required:

```bash
.venv/bin/python -m uvicorn src.app.main:app --reload
```

Then open `http://127.0.0.1:8000/demo`. The local demo does not prove live
Foundry extraction, managed-identity access, email or SMS delivery, or clinical
readiness.

Do not treat READY or Consumer RBAC as authorization for a WebJob trigger,
live inference, notification delivery, unrelated deployment, or production
data.

## Step 8 — Perform end-of-day cleanup

At the end of the workday, run the ownership-scoped, default-no cleanup:

```bash
scripts/daily_azure.sh stop
```

Review the sanitized plan and approve only the exact configured disposable
environment. Cleanup reinspects after approval, synchronously deletes the
owned resource group when present, purges only independently and conclusively
owned bounded Foundry `AIServices`, Speech `SpeechServices`, and exact
deterministic Key Vault tombstones, and performs final read-only reconciliation.
Conclusively unrelated records are ignored; ambiguous or near-matching records
fail closed for manual review.

Success is either `category=cleanup_completed` or `category=already_clean` and
must include the implementation's final-absence proof:

```text
ok=true
account_verified=true
inspection_completed=true
resource_group_absent=true
foundry_tombstones_absent=true
speech_tombstones_absent=true
key_vault_tombstones_absent=true
daily_environment_clean=true
```

`azure_mutation_made` may be `false` when the environment was already absent.
Deletion immediately expires all readiness, RBAC, WebJob, identity, metadata,
and invocation evidence and returns the daily environment to NOT READY.

Stop on cleanup ownership ambiguity, active-name conflict, authorization
failure, deletion or purge failure, or final reconciliation failure. Do not use
an asynchronous delete, manually purge a similar-name record, or claim cleanup
from request acceptance. Preserve the result and resolve the exact failure
before the next workday.

## Proof matrix

| Command or boundary | Mutation behavior | What it proves | What it does not prove |
| --- | --- | --- | --- |
| `scripts/daily_azure.sh check` | None; offline only | Local cleanup and rebuild contracts are valid | Authentication, Azure state, deployment, or READY |
| `az account show ...` | None; read-only | Current CLI subscription name, state, and default selection | Resource ownership, deployment, or readiness |
| `scripts/daily_azure.sh start` | May make separately approved Azure mutations | Exact owned/rebuilt environment through current hosted application readiness and artifact equality; when Key Vault runtime authorization is enabled, the exact current-generation Secrets User assignment too | Foundry Consumer RBAC, human Reader authorization, secret retrieval, WebJob execution, managed-identity Foundry access, metadata, invocation, inference, or delivery |
| `.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py --live ...` | Read-only when reusing; one default-no assignment deployment only when conclusively missing | Exactly one direct Consumer assignment for the current Web App identity at the exact project scope | Token acquisition, metadata access, WebJob execution, or invocation |
| `.venv/bin/python scripts/prepare_hosted_foundry_agent_webjob_handoff.py --live ...` | Projected Azure reads plus one private immutable local handoff write | Current READY receipt, hosted artifact, Web App identity, Foundry project, and environment generation are bound together | RBAC, WebJob discovery, trigger, execution, metadata, or invocation |
| `.venv/bin/python scripts/run_hosted_foundry_agent_verification.py --live-discover ...` | One authenticated read-only fixed-resource Kudu GET | The exact fixed triggered WebJob name and `run.py` command are registered | Trigger acceptance, execution, status, metadata, or invocation |
| Retired `--live-trigger`, `--live-reconcile-blocked-trigger`, and `--live-status` modes | Former trigger and correlation reads; unsupported for current operations | No supported current proof; preserved only as retired implementation evidence | Any reliable capstone claim for correlated execution, managed-identity metadata access, invocation, or inference |
| Retired `--live-metadata-verification` compatibility mode | None; deterministic rejection before configuration or transport activity | SSH hosted managed-identity execution is unsupported | Token acquisition, metadata access, invocation, or any authorization outcome |
| `.venv/bin/python scripts/run_hosted_foundry_agent_ssh_transport.py --live-tunnel ...` | One owned tunnel and three fixed non-invoking commands after separate approvals | Listener readiness, both prerequisite probes, packaged-module availability, packaged non-invoking check, and deterministic cleanup | Credential construction, metadata access, Agent invocation, or Azure mutation |
| `scripts/daily_azure.sh stop` | May delete the exact owned group and purge bounded owned Foundry, Speech, and exact deterministic Key Vault tombstones after default-no approval | Final resource-group, Foundry-tombstone, Speech-tombstone, and Key Vault-tombstone absence | A future session's readiness or any retained live proof |

## Exceptional immutable WebJob evidence recovery

This is exceptional offline evidence retirement, not a daily step and not a
way to resume the retired trigger path. Use it only when stale, incompatible,
generation-mismatched, or completed WebJob lifecycle evidence blocks a new
generation. It does not call Azure or HTTP, trigger a WebJob, produce READY, or
convert old evidence into current proof.

Never manually delete, edit, overwrite, reset, adopt, or ignore immutable files
beneath `.artifacts/hosted-foundry-agent-webjob/`.

Preserve this inspect-then-archive sequence:

1. Validate the recovery contract and inspect the active evidence:

   ```bash
   set -o pipefail

   .venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
     --check \
     --source-root "$PWD" \
     --json |
     .venv/bin/python -m json.tool

   .venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
     --inspect \
     --source-root "$PWD" \
     --expected-environment-fingerprint <expected-environment-fingerprint> \
     --json |
     .venv/bin/python -m json.tool
   ```

2. In an approved ignored evidence location, record the expected environment
   fingerprint used for the inspection and the returned exact
   `manifest_digest`. Never put either value in documentation or a commit.
3. When necessary, inspect again with the same
   `<expected-environment-fingerprint>`. Stop for changed evidence, malformed
   or conflicting state, unsafe paths, symlinks, unknown files, or an active
   reservation.
4. Archive only the unchanged manifest using its exact matching digest:

   ```bash
   set -o pipefail

   .venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
     --archive \
     --source-root "$PWD" \
     --expected-environment-fingerprint <same-expected-environment-fingerprint> \
     --manifest-digest <exact-matching-manifest-digest> \
     --reason stale_environment_evidence \
     --json |
     .venv/bin/python -m json.tool
   ```

   The prompt defaults to no. After approval, the service atomically
   quarantines, reinspects, and archives only the exact unchanged evidence.
5. Verify the returned archive-relative path and external
   `retirement-receipt.json`. Confirm the archived manifest digest and approved
   digest match and the original evidence remains byte-for-byte preserved.
6. Restart the normal workflow at Step 1. Archived evidence is audit material,
   never a receipt or authorization.

For the exact transitional legacy `generation-handoff.json` plus `package/`
shape, use `--legacy-package-conflict` on both inspect and archive. That flag
does not accept any other directory or ZIP shape.

## Failure handling summary

- Authentication failure: stop, correct the operator login/subscription, and
  restart at Step 1.
- Local contract failure: stop before Azure access, correct the local cause,
  and restart at Step 1.
- Ambiguous or unowned Azure resources: stop without adoption, retagging,
  repair, or deletion.
- Coordinator failure: do not claim READY; correct only the sanitized failure
  and restart at Step 1.
- RBAC failure: stop without manual assignment, scope broadening, or retry.
- WebJob trigger ambiguity: preserve immutable evidence; the current trigger
  path is retired and no reconciliation or status command is supported.
- Cleanup reconciliation failure: do not claim absence; preserve the result and
  resolve exact ownership, deletion, purge, or final-read failure.

## Quick reference

Start of day:

```bash
scripts/daily_azure.sh check
az login
az account show --query "{subscription:name,state:state,isDefault:isDefault}" --output table
scripts/daily_azure.sh start
```

Require `ok=true`, `category=success`, and
`daily_environment_ready=true`.

Optional Consumer RBAC:

```bash
.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --live \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json
```

End of day:

```bash
scripts/daily_azure.sh stop
```

Require `resource_group_absent=true`,
`foundry_tombstones_absent=true`, `speech_tombstones_absent=true`,
`key_vault_tombstones_absent=true`, and `daily_environment_clean=true`.
