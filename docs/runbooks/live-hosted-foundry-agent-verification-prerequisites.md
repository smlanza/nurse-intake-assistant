# Live Hosted Foundry Agent Verification Prerequisites

## 1. Purpose and scope

This runbook defines prerequisites for a separately authorized live proof that an already-deployed Linux
Web App, using only its system-assigned managed identity, can perform the
repository's read-only prompt-agent metadata verification followed by one fixed
fictional invocation against an operator-approved project and exact version.
Completing this runbook does not authorize or perform that proof.

The packaged WebJob first verifies prompt-agent metadata and then performs one
fixed-fictional-data invocation using the Linux Web App system-assigned managed
identity. It never submits patient text, persists a case, or sends or records
notifications. It does not alter infrastructure, RBAC, agent definitions,
application configuration, or hosted code, and does not prove production
readiness.

## 2. Authentication and subscription gate

The operator begins the future prerequisite workflow by authenticating and
performing one current-account check:

```bash
az login

az account show \
  --query "{subscription:name,state:state,isDefault:isDefault}" \
  --output table
```

Confirm the intended subscription by name, confirm its state is `Enabled`, and
confirm it is the intended default selection. Stop if any of those checks fail
or are ambiguous. Do not try alternate credentials.

Do not record subscription IDs, tenant IDs, access tokens, credentials, or
complete resource IDs in this runbook, prompts, commits, or captured evidence.

## 3. Exact operator-approved inventory

Before any current prerequisite verification, the operator must record a
sanitized exact value for every item below:

- [ ] Resource group
- [ ] Foundry AIServices account
- [ ] Foundry child project
- [ ] Model deployment
- [ ] Prompt-agent name
- [ ] Exact immutable prompt-agent version
- [ ] Linux Web App
- [ ] Hosted application origin
- [ ] Expected Foundry project endpoint
- [ ] Expected stable per-agent endpoint or repository-owned equivalent

Every value must come from fresh repository-owned verification or an explicit
operator-approved parameter source. Historical output, portal screenshots,
truncated portal names, prior conversations, inferred resource groups or other
inferred resource names, and assumed defaults are insufficient. Resource
existence alone is not current usability proof.

The inventory and evidence must remain sanitized. Record names only where this
runbook asks for names; never capture identity values, tokens, credentials,
complete resource IDs, raw CLI or SDK output, or endpoints containing secrets.

## 4. Authoritative repository ownership

Use the existing repository boundaries below. Do not duplicate Bicep, create an
alternate provisioner, or substitute portal-only instructions.

| Concern | Authoritative repository boundary |
|---|---|
| Foundry infrastructure deployment and verification | `infra/foundry-only.bicep`, `infra/modules/foundry.bicep`, `scripts/deploy_foundry_infra.py`, and `scripts/verify_foundry_infra.py` |
| Prompt-agent lifecycle and immutable-version verification | `src/app/services/foundry_agent_deployment.py`, `scripts/deploy_foundry_agent.py`, `src/app/services/foundry_agent_verification.py`, and `scripts/verify_foundry_agent.py` |
| Linux Web App infrastructure | `infra/main.bicep`, `infra/modules/web-app.bicep`, `src/app/services/web_app_infra_deployment.py`, and `scripts/deploy_web_app_infra.py` |
| Hosted application configuration verification | `src/app/services/web_app_hosting_contract.py`, `src/app/services/web_app_configuration_verification.py`, and `scripts/verify_web_app_configuration.py` |
| Deterministic application packaging and code deployment | `src/app/services/web_app_package.py`, `scripts/package_web_app.py`, and `scripts/deploy_web_app_code.py` |
| Generation-bound triggered WebJob packaging and deployment | `src/app/services/hosted_foundry_agent_webjob_package.py`, `src/app/services/hosted_foundry_agent_webjob_deployment.py`, and `scripts/deploy_hosted_foundry_agent_webjob.py` |
| Hosted readiness verification | `src/app/services/web_app_readiness_verification.py` and `scripts/verify_web_app_readiness.py` |
| Project-scoped Consumer RBAC deployment and exact direct-assignment verification | `infra/foundry-agent-consumer-rbac.bicep`, `infra/modules/foundry-agent-consumer-rbac.bicep`, `src/app/services/foundry_agent_consumer_rbac_deployment.py`, `scripts/deploy_foundry_agent_consumer_rbac.py`, `src/app/services/foundry_agent_consumer_rbac_verification.py`, and `scripts/verify_foundry_agent_consumer_rbac.py` |
| Packaged hosted Foundry metadata verification | `src/app/services/hosted_foundry_agent_verification.py` and `src/app/operations/verify_hosted_foundry_agent.py` |
| Fixed hosted execution boundary | `App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py`, `src/app/services/hosted_foundry_agent_webjob_execution.py`, and `scripts/run_hosted_foundry_agent_verification.py` |
| Manual immutable-state recovery | `src/app/services/hosted_foundry_agent_webjob_state_recovery.py`, `scripts/recover_hosted_foundry_agent_webjob_state.py`, and `docs/runbooks/recover-stale-hosted-foundry-agent-webjob-state.md` |

Infrastructure deployment, prompt-agent lifecycle, Web App deployment,
configuration verification, packaging, code deployment, readiness, RBAC,
hosted metadata verification, and invocation are distinct approval boundaries.

## 5. Required current proof

Before the hosted operation may run, obtain fresh, successful, sanitized
evidence for every applicable prerequisite:

1. `scripts/verify_foundry_infra.py` proves the approved AIServices account,
   child project, project-endpoint contract, model deployment, and successful
   states.
2. `scripts/verify_foundry_agent.py` proves the exact prompt-agent immutable
   version through a read-only live verification.
3. The same agent metadata proof shows the Responses protocol and routing that
   resolves exclusively to the approved immutable version.
4. The exact model deployment and repository-centralized instructions match
   the immutable version definition.
5. `scripts/verify_web_app_configuration.py` proves the approved Linux Web App,
   complete Bicep-owned safe configuration, and system-assigned identity.
6. The current deterministic package is the package used by the most recent
   separately approved code deployment; request acceptance alone is not proof.
7. `scripts/verify_web_app_readiness.py` freshly proves `/health`, `/version`,
   and `/demo/status` for the approved hosted application origin.
8. The system-assigned identity is present and usable as the intended identity;
   no user-assigned identity may substitute for it.
9. `scripts/verify_foundry_agent_consumer_rbac.py` freshly proves exactly one
   direct Foundry Agent Consumer assignment for that Web App identity at the
   exact Foundry child-project scope.
10. Every non-secret setting required by the packaged hosted verifier is
    available through a repository-owned deployment/configuration path.

All proof must describe current usability, not merely resource existence,
deployment acceptance, RBAC existence, token construction, or client
construction. Missing, stale, or historical evidence fails the gate.

## 6. Hosted execution mechanism and configuration gates

The deterministic application package excludes `App_Data` and therefore
cannot implicitly install or update a WebJob. A separate deterministic
WebJob-only ZIP contains exactly `run.py`, sourced from
`App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py`; no `.env`, Git,
tests, documentation, Bicep parameters, application source tree, artifacts, or
unrelated WebJob can enter that archive. The separately approved deployment
uses the supported Kudu replacing upload contract,
`PUT /api/triggeredwebjobs/verify-hosted-foundry-agent`, with
`Content-Type: application/zip`. Upload acceptance and the subsequent
authoritative Kudu
`GET /api/triggeredwebjobs/verify-hosted-foundry-agent` are distinct proofs.
Both use the same validated Entra bearer-token acquisition boundary. Neither
proof triggers the WebJob.

The package builder writes only
`.artifacts/hosted-foundry-agent-webjob-package/verify-hosted-foundry-agent.zip`.
The separate `.artifacts/hosted-foundry-agent-webjob/` root is reserved
exclusively for recognized immutable generation and trigger lifecycle state.
Check, package creation, approval preparation, upload, and deployment must not
create a package directory, ZIP, staging file, or other build artifact beneath
that lifecycle root. If the exact transitional legacy `package/` conflict is
present, stop before deployment and use only the explicit recovery procedure;
never move or delete it manually.

The fixed entry point first runs hosted metadata verification and, only after
exact typed proof success, performs one fixed-fictional invocation. It validates both complete
application-owned result schemas and emits one combined sanitized JSON result.
Offline
check validates the entry point, package allowlist, Bicep/configuration path,
and lazy SDK imports without constructing an Azure runner. The entry point
resolves only the absolute App Service `HOME`, puts validated
`$HOME/site/wwwroot` first on `sys.path`, rejects unexpected preloaded parent or
target packages, proves the imported module is the exact HOME-owned operation
file, and rebuilds dependency paths only from the platform-selected Python
interpreter's validated `sys.prefix` and `sys.base_prefix`. It does not use
`APP_PATH`, inferred Oryx virtual-environment names, temporary Kudu staging,
`cwd`, or `WEBJOBS_PATH`. Missing or unsafe `pydantic`, `azure.identity`, or
`azure.ai.projects` resolution fails before metadata verification or
invocation. Separate discovery performs exactly one fixed-resource Kudu GET,
requires the exact fixed name and `run.py`, and performs no list, poll, upload,
trigger, history, or mutation operation. `latest_run` may be absent or null
before the first trigger and is not execution proof. Additional Kudu-owned
top-level fields are ignored and their values are neither trusted nor
serialized. Before separate trigger reads state or constructs a runner, it atomically
creates the fixed
`.artifacts/hosted-foundry-agent-webjob/trigger-reservation.lock`. That local
reservation excludes trigger processes sharing this checkout's artifact
filesystem; it is not a distributed lock across workstations or checkouts.
Accepted context is then written once to immutable `accepted-trigger.json`.
Accepted-but-uncorrelatable execution writes immutable `blocked-trigger.json`,
or preserves the reservation when neither artifact can be made durable. No
automatic expiry, cleanup, reset, or retrigger is allowed. After the trigger
runner is entered, any nonzero result, timeout, exception, or empty, malformed,
or unknown acceptance response is ambiguous and must create blocked state before
reservation release. Only a specifically modeled local process-not-started
failure is conclusively pre-submission and may permit a later explicit attempt.

After daily READY and before discovery, the separate
`scripts/prepare_hosted_foundry_agent_webjob_handoff.py` command validates the
current non-revoked readiness receipt, revalidates the current hosted package,
and performs only projected read-only Web App identity and Foundry project
reads. It reads no role assignments and performs no WebJob operation. It writes
one private immutable `generation-handoff.json` beneath the lifecycle
directory. The fingerprint and its source evidence are never operator inputs or
command output. Discovery, trigger, and status require the same unchanged
readiness receipt and handoff. A rebuild or deletion invalidates the readiness
receipt; retire stale lifecycle evidence through the recovery runbook rather
than replacing it.

Separate status requires the immutable accepted receipt and one projected
history read. It never mutates the receipt. Correlated terminal success or
failure is written separately to immutable `terminal-outcome.json`; a repeated
status request validates both artifacts and returns the recorded sanitized
result without another Azure read. All lifecycle reads use descriptor-relative
no-follow handling and reject symlinked parents, symlinked targets, and
nonregular files. No mode retries, polls, sleeps, or changes configuration; one
terminally successful WebJob run proves the fixed invocation completed.
Stale, incompatible, or generation-mismatched immutable state is never ignored
or removed here. Stop and use the separate evidence-preserving recovery runbook;
recovery itself neither authorizes a trigger nor produces READY.

This repository-owned execution mechanism is offline-tested only. Before its
first live use, current evidence must prove that the exact package is deployed
and the fixed WebJob is discoverable in the approved Linux Web App. Do not use
interactive Kudu manipulation, improvised SSH or shell commands, a portal
console, a temporary startup-command change, an ad hoc HTTP endpoint, another
WebJob, local execution masquerading as hosted proof, or any Azure CLI command
that mutates application configuration.

The operation also requires these five non-secret values:

- `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT`
- `AZURE_AI_FOUNDRY_AGENT_ENDPOINT`
- `AZURE_AI_FOUNDRY_AGENT_NAME`
- `AZURE_AI_FOUNDRY_AGENT_VERSION`
- `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`

These five values now flow through one disabled/enabled tagged configuration in
`infra/main.bicep` and `infra/modules/web-app.bicep`. Disabled is the default for
ordinary Web App deployment and emits none of the five settings. Explicit opt-in
requires all five complete nonblank values. Direct `main.bicep` and reusable
`web-app.bicep` deployment each map any empty, whitespace-only, or
surrounding-whitespace enabled value to an empty nested-module value, where the
compiled ARM `minLength: 1` constraint rejects deployment before an App Service
setting can be emitted. The internal validation module creates no Azure service
resource and uses no experimental Bicep feature. The seven
mock-safe settings remain
unchanged. Baseline configuration verification projects none of the five;
explicit hosted-verifier verification compares all five to operator-approved
values without returning them. This path is offline-tested only. Fresh live
configuration proof is still required, and manual environment-variable
injection or ad hoc App Service setting changes remain prohibited.

The four reviewed lifecycle and raw-Bicep blockers are resolved offline. Live readiness is
still blocked until the runbook's current infrastructure, immutable-version,
configuration, package/code, WebJob discovery, readiness, and RBAC evidence is
complete and manually reviewed.

## 7. Approved stage sequence

The future workflow must preserve this order, with fresh sanitized evidence and
manual review between stages:

```text
Operator authentication/current account
-> exact approved inventory
-> current Foundry infrastructure verification
-> exact immutable prompt-agent version verification
-> current Web App configuration verification
-> current hosted readiness verification
-> current exact direct RBAC verification
-> exact assignment-only what-if and preview-bound default-no approval when missing
-> immediate fresh identity, project, subscription, role, assignment, and generation revalidation
-> constrained RBAC deployment and separate post-deployment verification when missing
-> read-only WebJob generation-handoff preparation
-> offline hosted-verifier check
-> manual review of all sanitized evidence
-> separately approved generation-bound WebJob-only ZIP upload
-> read-only proof that the fixed remote WebJob is discoverable
-> one explicitly authorized WebJob trigger request
-> review of trigger acceptance without treating it as verification success
-> one separately authorized receipt-correlated status read
-> immutable separate terminal outcome or fail-closed nonterminal result
-> review of the sanitized result
```

Trigger acceptance is not completion. Status discards every historical run
before the current receipt lower bound and proves metadata success only when
exactly one eligible run exists and is terminal `Success`; zero or multiple
eligible runs, including stale successful history, fail closed.

The hosted execution must not run while preparing or reviewing this runbook.
When separately authorized, its only invocation is the fixed-fictional packaged
proof after metadata success; it is not an arbitrary prompt or intake path.

## 8. Success contract for a separately authorized live proof

Success requires the existing sanitized application-owned result to prove all
of the following without exposing identifiers or raw SDK output:

- Execution occurred inside the approved hosted App Service environment.
- Only the Linux Web App system-assigned managed identity was used.
- Managed-identity authentication succeeded.
- The expected Foundry project and prompt-agent metadata were readable.
- The configured prompt agent and exact immutable version were present.
- Responses protocol support was present.
- Routing resolved exclusively to the approved immutable version.
- The model and centralized instructions matched the approved definition.
- Exactly one fixed-fictional invocation was attempted after metadata success.
- The application-owned output contract passed, fallback was not used, and the
  fictional-data-only proof was exactly true.
- No intake, persistence, notification, clinical action, or Azure mutation was
  attempted.
- One combined result contained only sanitized application-owned proof fields.

RBAC existence alone, token acquisition alone, credential or client
construction, resource existence, and successful hosted readiness are not
sufficient proof.

## 9. Fail-fast stop conditions

Stop before the hosted operation when any prerequisite is missing, stale,
ambiguous, malformed, mismatched, unauthorized, not currently usable, or based
only on historical evidence. Also stop when:

- The immutable agent version cannot be freshly verified.
- Hosted code provenance or `/health`, `/version`, and `/demo/status` readiness
  cannot be freshly verified.
- The exact direct Consumer assignment cannot be freshly verified.
- The hosted operation has no repository-owned execution mechanism.
- A required non-secret setting lacks a repository-owned configuration boundary.
- A command would require credential fallback, mutation, retry, polling, manual
  environment injection, or an inferred resource name.
- The repository's current implementation differs materially from this runbook.

Do not retry with alternate credentials or scopes. Stop for operator correction
and, where required, a separately scoped implementation or deployment slice.

## 10. Prohibited behavior

The prerequisite and hosted proof workflows prohibit the
following ad hoc Azure changes and unsafe operations:

- Ad hoc Azure changes during prerequisite verification.
- Arbitrary prompts, patient-data invocation, repeated inference, or invocation
  outside the fixed packaged proof.
- Prompt-agent creation or version creation.
- RBAC repair.
- Infrastructure deployment unless separately authorized before the future
  metadata-verification slice.
- Application code deployment during the metadata-verification execution.
- Credential fallback to Azure CLI, developer, environment-secret, browser,
  workload, cached, user-assigned, or interactive credentials.
- General-purpose shell polling loops, repeated sleeps, repeated verifier calls,
  indefinite waiting, or retrying against alternate names, scopes, or
  credentials.
- Portal-only substitutes, inferred names, historical evidence, interactive
  Kudu or SSH manipulation, temporary startup changes, any WebJob other than
  the fixed repository-owned metadata verifier, ad hoc HTTP endpoints, and
  manual environment-variable injection.
- Raw CLI or SDK output in documentation.
- Secrets, identity values, tokens, endpoints with embedded secrets, real
  patient data, or real contact information.

At most one repository-approved bounded completion check is permitted, and
only when an authoritative operation explicitly requires it. It never permits
general polling, repeated calls, or indefinite waiting.

## 11. Operator completion checklist

- [ ] Operator login and one current-account check are complete.
- [ ] Intended subscription name, `Enabled` state, and default selection are
  confirmed without recording subscription or tenant IDs.
- [ ] Every exact inventory value is current, sanitized, operator-approved, and
  matched to repository-owned evidence.
- [ ] Foundry account, project, endpoint contract, and model deployment are
  freshly verified and usable.
- [ ] Prompt-agent name, exact immutable version, Responses protocol, exclusive
  routing, model, and centralized instructions are freshly verified.
- [ ] Linux Web App configuration and system-assigned identity are freshly
  verified against the complete Bicep-owned safe contract.
- [ ] Current package/code provenance is reviewed and `/health`, `/version`, and
  `/demo/status` are freshly verified.
- [ ] Exactly one direct Consumer assignment is freshly verified for the exact
  identity and exact Foundry child-project scope.
- [ ] Every required non-secret verifier setting has a repository-owned
  deployment/configuration path and is currently available to the Web App.
- [ ] A repository-owned bounded hosted execution mechanism exists and has been
  separately implemented, packaged, deployed, discovered, and reviewed.
- [ ] Offline hosted-verifier check passed without a credential, client, Azure
  call, metadata read, inference, invocation, or mutation.
- [ ] All sanitized evidence has been manually reviewed; no raw output, secret,
  identity value, complete resource ID, patient data, or real contact data was
  captured.
- [ ] No stop condition remains.
- [ ] The operator explicitly authorizes exactly one WebJob trigger request.
  This authorization applies only to metadata verification followed by the one
  fixed-fictional invocation; it does not authorize arbitrary inference,
  intake processing, status polling, deployment, RBAC change, or retry.
- [ ] After trigger acceptance, the operator separately authorizes at most one
  receipt-correlated status read; trigger acceptance itself is not verification
  success, and historical latest-run evidence is insufficient.

## 12. Preferred handoff and WebJob commands

Use the same current readiness receipt for preparation, discovery, trigger, and
status. Stop and review each sanitized JSON result before the next command.
Never substitute another fingerprint or manually reconstruct generation
evidence.

```bash
set -o pipefail

.venv/bin/python scripts/prepare_hosted_foundry_agent_webjob_handoff.py \
  --check \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  python -m json.tool

.venv/bin/python scripts/prepare_hosted_foundry_agent_webjob_handoff.py \
  --live \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  python -m json.tool
```

Preparation is fail-closed. Its output contains only fixed sanitized categories;
it never includes names, IDs, endpoints, package digests, fingerprints,
settings, credentials, command output, stderr, or exception text.
`azure_read_attempted=true` means the preparation reader entered at least one
Azure CLI runner call. It remains `false` for every failure before that exact
boundary.

| Sanitized failure category | Meaning and required operator response |
|---|---|
| `invalid_request` | The local request contract is invalid. Use the documented command exactly; do not infer or substitute values. |
| `readiness_receipt_invalid` | The receipt is missing, stale, revoked, malformed, or does not match the current approved configuration. Stop and obtain a fresh successful daily READY receipt through the daily rebuild runbook. |
| `current_session_binding_invalid` | The protected current-session file is missing, malformed, unsafe, or does not exactly match the approved config and receipt. Correct the approved daily configuration or rerun its repository-owned coordinator; never hand-edit evidence to make it match. |
| `local_package_binding_invalid` | Current deterministic package construction or its authorized digest proof failed. Resolve the local package safety/contract failure and rerun the offline package checks. |
| `hosted_artifact_current_verification_failed` | The hosted readiness request failed, its contracts or safe posture failed, or the hosted artifact is not the current deterministic package. Use the separate sanitized readiness verifier to distinguish those cases. For `application_artifact_mismatch`, separately authorize deployment of the current package, then re-establish hosted readiness before preparation. |
| `web_app_identity_read_failed` | The projected read-only Web App command failed or returned unreadable JSON. Review current authentication, authorization, approved inventory, and resource usability without trying alternate credentials. |
| `web_app_identity_invalid` | The projected identity response did not prove the exact Web App resource and system-assigned identity contract. Correct infrastructure or inventory only through the separately approved repository-owned path; do not broaden accepted response shapes. |
| `foundry_project_read_failed` | The projected read-only Foundry project command failed or returned unreadable JSON. Review current authentication, authorization, approved inventory, and project usability without trying alternate names or credentials. |
| `foundry_project_invalid` | The projected project response did not prove the exact subscription, resource group, account, child-project name, and resource-ID contract. Correct external inventory or infrastructure drift through a separately approved path; do not relax exact matching. |
| `environment_fingerprint_invalid` | Final evidence failed the shared environment-generation fingerprint contract. Stop for repository/inventory review; never supply, reconstruct, print, or override a fingerprint. |
| `generation_evidence_invalid` | An unclassified evidence-reader contract failure occurred. Stop for repository-owned diagnostic review; do not proceed to discovery. |
| `generation_handoff_invalid` | Existing lifecycle state could not be safely read or validated. Stop and follow the evidence-preserving recovery runbook. |
| `generation_handoff_conflict` | Immutable lifecycle state already exists but does not exactly match this generation, or concurrent creation won. Do not replace it; use the recovery runbook. |
| `generation_handoff_write_failed` | Private immutable handoff persistence failed. Correct only the local protected-filesystem condition, preserving any existing evidence, before a new explicit preparation attempt. |
| `unexpected_error` | An unclassified preparation failure occurred. Stop for repository-owned diagnostic review. |

No preparation failure category authorizes WebJob deployment, discovery,
trigger, status, metadata
verification, invocation, Azure mutation, or replacement of immutable
lifecycle evidence.

After successful preparation, run both offline checks:

```bash
.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --json |
  python -m json.tool

.venv/bin/python scripts/deploy_hosted_foundry_agent_webjob.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  python -m json.tool
```

Only after separate approval, perform the generation-bound WebJob upload. The
prompt is default-no. The service re-reads the complete environment generation
after approval, consumes a current-run one-use package authorization, performs
at most one upload, performs one authoritative fixed-resource Kudu discovery
only after conclusive upload acceptance, and stops:

```bash
.venv/bin/python scripts/deploy_hosted_foundry_agent_webjob.py \
  --live \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  python -m json.tool
```

The deployment output is sanitized. Resource and project names, IDs, endpoints,
principal or subscription identifiers, package digests, fingerprints, raw
command output, stderr, exception text, settings, tokens, and credentials are
never serialized. Review these independent proof booleans:

Do not repeat the lifecycle CLI's `--live-discover` immediately after this
command: successful deployment has already performed the single allowed
discovery and must stop for review.

- `upload_attempted` means the Kudu upload transport was entered.
- `upload_accepted` means that one upload returned a supported acceptance
  status; it does not prove remote installation or execution.
- `remote_discovery_attempted` means the single Kudu fixed-resource GET
  transport was entered.
- `remote_webjob_discovered` proves the exact fixed name and `run.py` command.
- `trigger_attempted`, `trigger_accepted`,
  `correlated_execution_observed`, `metadata_verification_proven`, and
  `fictional_invocation_proven` remain `false` in every deployment result.

| Sanitized deployment category | Meaning and required operator response |
|---|---|
| `invalid_request` | The fixed source root, approved names, mode, or WebJob name contract is invalid. Use the documented command unchanged. |
| `readiness_receipt_invalid` | Current READY proof is absent or mismatched. Re-establish READY; do not upload. |
| `generation_handoff_invalid` | The immutable handoff is absent, unsafe, stale, or mismatched. Use evidence-preserving recovery before preparing a replacement. |
| `local_package_invalid` | Exact one-file package planning or construction failed. Correct repository-owned package or filesystem safety; do not upload. |
| `generation_invalid` | Current environment evidence does not match the immutable handoff. Treat this as configuration, package, identity, project, agent, or WebJob-generation drift. |
| `approval_required` | Approval was declined, missing, interrupted, or defaulted to no. No upload occurred. |
| `generation_changed` | Environment evidence changed after approval. Obtain fresh prerequisite evidence and a new approval. |
| `package_changed` | The source or archive changed after approval, or the one-use authorization could not be consumed. Review the source and restart from current proofs. |
| `authentication_or_authorization_failed` | No usable shared Entra token was obtained, or Kudu rejected upload or discovery authentication/authorization. Correct operator access without changing the package or trying alternate credentials. |
| `upload_request_invalid` | Kudu conclusively rejected the request contract with a recognized client/request status. Stop without discovery or retry; correct only the repository-owned request contract after diagnostic-first review. |
| `upload_throttled` | Kudu conclusively reported throttling. Stop without discovery, retry, delay loop, or inferred acceptance; any later attempt requires fresh generation proof and separate approval. |
| `upload_service_failed` | Kudu conclusively returned a service-side 5xx rejection. Stop without discovery or retry; do not infer installation from request submission. |
| `upload_failed` | Kudu conclusively rejected the request with another HTTP status. Stop without discovery or retry and review only the sanitized category. |
| `upload_acceptance_ambiguous` | Transport interruption, timeout, or another unknown post-submission outcome means acceptance is unknown. Do not retry automatically; inspect current remote state through a separately approved read-only recovery step. |
| `remote_webjob_missing` | Upload was accepted but the one allowed discovery did not find the fixed name. Stop; do not trigger or upload again automatically. |
| `remote_webjob_ambiguous` | Discovery did not prove exactly one authoritative fixed WebJob. Stop without inference or trigger. |
| `discovery_throttled` | Kudu returned throttling for the single discovery GET. Stop without polling, delay loop, or retry. |
| `discovery_service_failed` | Kudu returned a service-side 5xx discovery failure. Stop without polling or retry. |
| `discovery_failed` | Kudu conclusively rejected the discovery GET with another status. Stop without another operation. |
| `discovery_ambiguous` | Discovery was interrupted, timed out, or had an unknown transport outcome. Stop without retry or inference. |
| `discovery_response_invalid` | The HTTP 200 body was malformed, collection-shaped, duplicated, missing required proof, used an invalid `latest_run` type, or did not prove the exact fixed name and `run.py`. Stop without weakening required-field validation. |
| `unexpected_error` | An unclassified fail-closed deployment-boundary failure occurred. Stop for repository-owned review. |
| `success` | Upload acceptance and exact fixed-name discovery are both proven. Stop; trigger still requires a later separate approval. |

The Kudu endpoint behavior is documented in the
[Kudu WebJobs API](https://github.com/projectkudu/kudu/wiki/WebJobs-API);
Microsoft also documents ZIP upload for triggered WebJobs in
[Create and run WebJobs](https://learn.microsoft.com/azure/app-service/webjobs-create).
These references do not broaden the repository's required proof fields.
Externally owned non-proof fields remain deliberately extensible and ignored.
The upload request always uses an Entra bearer token, `application/zip`, and
the fixed non-secret
`Content-Disposition: attachment; filename="verify-hosted-foundry-agent.zip"`.
It never retrieves or emits SCM publishing credentials. Current App Service
guidance supports Entra-authenticated Kudu access for identities with the
required App Service publish action, and Azure CLI's ARM token remains the
repository's fixed audience. An HTTP failure category never contains the
status, response body, headers, URL, token, exception text, or Kudu output.

For the already-installed generation whose dedicated upload was accepted but
whose former Azure CLI list discovery returned `remote_webjob_missing`, do not
upload, replace, archive, or recreate anything. Run exactly one corrected
read-only discovery and stop:

```bash
.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --live-discover \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  python -m json.tool
```

This standalone mode uses the same Kudu discoverer as post-upload deployment.
It returns only fixed categories and booleans. It does not trigger, upload,
poll, read status or history, verify metadata, invoke the agent, mutate Azure,
or change immutable lifecycle evidence. Trigger and receipt-correlated status
remain the existing separate Azure CLI `run` and `log` adapters; this discovery
slice does not change them.

Only after separate approval, submit one trigger and stop. Trigger acceptance
is not terminal execution success:

```bash
.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --live-trigger \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  python -m json.tool
```

Authorize one receipt-correlated status read separately:

```bash
.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --live-status \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json |
  python -m json.tool
```

Terminal WebJob success must still prove the fixed sequence of exact metadata
verification, one fictional invocation, and output-contract validation. It is
not inferred from preparation, discovery, or trigger acceptance.
