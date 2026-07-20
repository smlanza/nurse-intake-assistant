# Nurse Intake Assistant Architecture

## 1. Purpose And Current Scope

The Nurse Intake Assistant is an AI-103 capstone/demo project. The current MVP
is a local mock/demo FastAPI application that turns text intake or an
already-transcribed voicemail into a nurse-review case.

This is not production clinical software. It does not diagnose, prescribe,
dispatch emergency care, or make autonomous medical decisions. AI-generated
extraction, summary, and urgency output is advisory only and requires human
nurse review before any clinical action.

The implemented demo is intentionally small and repeatable:

- Local static demo page served by `GET /demo`
- Text intake through `POST /intake/text`
- Voicemail transcript intake through `POST /intake/voicemail-transcript`
- Deterministic mock AI extraction and summarization by default
- Deterministic red-flag urgency rules
- In-memory mock persistence by default
- Mock email and SMS notification recording by default
- Nurse queue, filtering, summary, case lookup, and review workflow
- Demo seed/reset endpoints for repeatable screenshots and walkthroughs

## 2. Implemented Current-State Architecture

```text
Browser or API client
-> FastAPI app
-> Intake routes, demo route, cases routes, notifications routes
-> CaseProcessingService
-> AI provider factory
-> UrgencyRulesService
-> Case repository factory
-> Email/SMS notification sender factories
-> CaseDocument response and nurse review queue
```

| Component | Implemented responsibility |
|---|---|
| FastAPI app | Hosts the API routes, health route, static legal pages, and local demo page |
| `GET /demo` | Serves the static local mock demo page from `src/app/static/demo.html` |
| Intake routes | Accept text intake and already-transcribed voicemail transcript intake |
| `CaseProcessingService` | Orchestrates extraction, urgency merge, persistence, and notifications |
| `create_ai_service(settings)` | Selects mock AI by default or the Foundry provider boundary when configured |
| `MockAiService` | Deterministic local extraction, summary, and urgency classification for demo/testing |
| `FoundryAiService` | Azure AI Foundry provider boundary/scaffold with offline structured extraction prompt/schema/parser contract, injected fake-client seam, and opt-in lazy live adapter; live extraction is deferred |
| `NurseIntakeAgent` | External reasoning boundary for future agent orchestration; output is contract-validated before case processing trusts it |
| `FoundryAgentVerification` | Explicit read-only boundary that validates stable-endpoint metadata, reads Responses support from `agent_endpoint.protocols`, verifies exclusive immutable-version routing, and compares the configured version definition without mutation or invocation |
| `HostedFoundryAgentInvocation` | Separate packaged proof boundary for exactly one fixed fictional prompt-agent invocation from an App Service system identity; validates only the application-owned output contract and returns no clinical content |
| Speech transcription services | Offline mock transcription boundary and Azure Speech scaffold/factory; live audio transcription is deferred |
| `UrgencyRulesService` | Deterministic red-flag rules with negation-aware matching |
| `create_case_repository(settings)` | Selects in-memory mock repository or Cosmos repository |
| `InMemoryCaseRepository` | Default mock persistence for local demo, filtering, summary, idempotency, and reset |
| `CosmosCaseRepository` | Cosmos point-read/upsert and cross-partition filtered case-list query support with container factory wiring |
| Email/SMS sender factories | Select mock senders by default or ACS provider boundaries when configured |
| Mock email/SMS senders | Record notification attempts in memory for demo inspection |
| ACS Email/SMS senders | Provider boundaries for SDK send-request paths |
| Nurse review workflow | Persists review status, reviewer, notes, and reviewed timestamp |

## 3. Current Local Mock Data Flow

```text
POST /intake/text or POST /intake/voicemail-transcript
-> CaseProcessingService
-> create_ai_service(settings)
-> MockAiService for AI_PROVIDER=mock
-> UrgencyRulesService
-> create_case_repository(settings)
-> InMemoryCaseRepository for APP_MODE=mock
-> create_email_notification_sender(settings)
-> MockEmailNotificationSender for EMAIL_PROVIDER=mock
-> create_sms_notification_sender(settings)
-> MockSmsNotificationSender for SMS_PROVIDER=mock
-> CaseDocument response
```

`POST /intake/text` stores `caseType="text-intake"`. `POST
/intake/voicemail-transcript` stores `caseType="phone-intake"` with optional
source call, recording, audio blob, caller phone, and idempotency metadata. The
voicemail route expects already-transcribed text only. The Speech transcription
provider boundary exists for future work, but Azure Speech, audio upload, and
live voice intake are not implemented in this MVP.

The default local settings are:

```text
APP_MODE=mock
AI_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=false
```

With those defaults, the app makes no live Azure calls and sends no real email
or SMS.

## 4. Intake, AI, And Urgency Processing

`CaseProcessingService` calls the configured AI service to extract patient
fields, summarize the intake, and classify advisory urgency. The mock provider
uses deterministic local logic so tests and demos are repeatable.

The Foundry provider boundary includes an offline structured extraction
contract: deterministic prompt instructions, expected JSON fields, and parser
validation that maps a future model response into the current extraction and
urgency output models. `FoundryAiService` can use that contract through an
injected fake/live-client seam in tests. A thin live adapter implements the
same `complete_structured_extraction(prompt, model_deployment_name)` seam with
lazy SDK imports and client construction. The existing manual Foundry Agent
invocation smoke has succeeded, while programmatic agent-version creation and
validation remain pending explicit operator execution. Automated tests remain offline.

The separate prompt-agent lifecycle boundary makes instruction provisioning
reproducible without changing runtime routing. An explicit operator CLI builds
`PromptAgentDefinition` from the centralized versioned instructions, inspects
the latest version through the current Foundry project SDK, reuses an identical
definition, or creates one version for a missing/changed definition. Only a
sanitized result is emitted. `--check` is offline; only `--live --json` makes
provisioning calls. Provisioning never invokes the agent; invocation remains a
separate explicit smoke command. Automated tests use fakes, and no provisioning
occurs at import, startup, `/demo`, or intake time. This is not a production
clinical deployment; nurse review remains mandatory.

After an operator manually records the provisioned immutable version, a
separate verification CLI can perform one read-only version lookup and compare
the returned version definition with the application-owned model and
centralized instructions. Offline check mode creates no client and makes no
Azure call; explicit live verification creates no version, makes no mutation,
creates no Responses client, and performs no model invocation. Direct agent
and application-level fictional-data smokes remain separate opt-in boundaries.
Stable per-agent OpenAI protocol invocation is primary; project-endpoint
agent-reference invocation remains compatibility-only and explicitly enabled.
Automated tests use fakes, and any live validation must be explicit and use only
fictional data.

The service also evaluates local red-flag rules from
`src/app/config/red_flags.yaml`. Rule detection is deterministic and includes
negation-aware handling so phrases such as denying a red-flag symptom do not
count as a positive match.

### Agent Safety Boundary

NurseIntakeAgent is treated as an external reasoning boundary. Agent output is
validated against an application-owned contract before
`CaseProcessingService` trusts it for summary or urgency classification. This
agent contract validation keeps malformed agent responses from silently
creating bad cases.

Valid agent output is used for the initial summary and urgency classification.
Invalid agent output does not crash intake processing; it falls back to safe
nurse-review values, records a processing trace warning, and leaves final
urgency source as `unknown` unless deterministic red-flag rules promote the
case to urgent. Deterministic red-flag rules still evaluate the raw intake text
even when agent output is invalid, and `processing_trace` records agent usage,
warnings, rules override state, and final urgency source.

```text
Raw intake -> Agent/AI analysis -> agent contract validation -> safe fallback if needed -> deterministic red-flag rules -> persisted case -> notification/review
```

Urgency merge behavior:

```text
If red-flag rules are Urgent or AI classification is Urgent:
    urgency = Urgent
Else:
    urgency = Routine
```

The merged urgency is a queue-prioritization aid only. The nurse remains the
human reviewer and clinical decision-maker.

## 5. Case And Review Model

The main saved object is `CaseDocument`. Important implemented fields include:

| Field area | Current values or purpose |
|---|---|
| Processing | `processingStatus` such as `Completed` |
| Intake completeness | `intakeStatus` of `Complete`, `NeedsFollowUp`, or `ProcessingFailed` |
| Review | `reviewStatus` of `PendingReview` or `Reviewed` |
| Urgency | `Routine`, `Urgent`, or `Unknown` with `urgencySource`, `ruleUrgency`, and `aiUrgency` |
| Source metadata | `sourceSystem`, `sourceCallId`, `sourceRecordingId`, `audioBlobName`, `idempotencyKey` |
| Human review | `reviewedBy`, `reviewNotes`, and `reviewedAt` |
| Notifications | Legacy booleans plus explicit email/SMS status fields |

Cases with missing required intake details are still saved and marked
`NeedsFollowUp`; they are not discarded.

Implemented nurse-facing read/review endpoints include:

```text
GET /cases
GET /cases/summary
GET /cases/{case_id}
POST /cases/{case_id}/review
```

`GET /cases` supports local mock filtering by review status, urgency, intake
status, intake completeness, source/channel metadata, notification status, SMS
delivery confirmation, date range, limit, and offset. `GET /cases/summary`
returns dashboard-style counts for the filtered queue.

## 6. Persistence Architecture

The default persistence mode is mock/in-memory:

- `APP_MODE=mock` uses `InMemoryCaseRepository`
- Supports save, point lookup, idempotency lookup, list filters, queue summary,
  nurse review persistence, demo seed, and demo reset
- Data is process-local and disposable

Cosmos support exists as a provider boundary and smoke-tested path:

- `APP_MODE=cosmos` uses `CosmosCaseRepository`
- `create_cosmos_container(settings)` builds the configured Cosmos container
- `infra/main.bicep` creates a `cases` container with partition key
  `/createdDate`
- Cosmos point reads and upserts are supported
- Cross-partition filtered case-list queries are implemented and covered by
  offline fake-container tests
- `GET /cases/{case_id}?createdDate=YYYY-MM-DD` supports point-read lookup when
  the client knows the partition key

Deferred Cosmos behavior:

- Cross-partition queue summary queries
- Cross-partition idempotency lookup for voicemail transcripts
- Live Azure validation of implemented case-list queries
- Server-side pagination and aggregation refinements
- Production-grade query/index tuning

## 7. Notification Architecture

Mock notification providers are the default:

- `EMAIL_PROVIDER=mock` records mock email notifications in memory
- `SMS_PROVIDER=mock` records mock SMS notifications in memory
- `GET /notifications/email` and `GET /notifications/sms` expose the recorded
  mock notifications for demo inspection

ACS provider boundaries are implemented but not part of the local demo page:

- `EMAIL_PROVIDER=acs` selects ACS Email and requires ACS Email configuration
- ACS Email smoke testing is complete
- `SMS_PROVIDER=acs` selects ACS SMS and reaches the SDK/send-request path
- Confirmed SMS handset delivery remains pending external toll-free
  verification and carrier/Azure regulatory workflow completion

Notification status semantics:

- `notificationEmailSent` and `notificationSmsSent` are backward-compatible
  booleans
- `notificationEmailStatus` and `notificationSmsStatus` should be used for
  explicit state
- Status values are `NotAttempted`, `MockRecorded`, `Accepted`, `Failed`, and
  `Suppressed`
- Mock sends set the legacy sent boolean to `true` and status to
  `MockRecorded`
- ACS accepted sends set the legacy sent boolean to `true` and status to
  `Accepted`
- `Accepted` means the provider accepted the send request; it does not prove
  final SMS handset delivery
- `notificationSmsDeliveryConfirmed` remains `false` until a future delivery
  tracking slice exists
- Failures set the matching legacy sent boolean to `false`, status to `Failed`,
  and still save/return the case
- `DEMO_SUPPRESS_NOTIFICATIONS=true` sets statuses to `Suppressed`, leaves sent
  booleans false, and records no mock notifications

## 8. Demo Architecture

The demo page at `/demo` is a static HTML/CSS/JavaScript page served by FastAPI.
It uses existing local/mock endpoints only and does not use a frontend
framework.

Implemented demo-support endpoints:

```text
POST /demo/seed
POST /demo/reset
```

`POST /demo/seed` creates deterministic screenshot-safe fictional cases.
`POST /demo/reset` clears mock in-memory cases and mock notification records.
Both are restricted to mock mode.

The demo is safe for repeated local walkthroughs because it uses fictional seed
data, mock providers, and explicit local demo safety text. It should not be run
with real patient data, real phone numbers, real email addresses, secrets, or
connection strings.

## 9. Infrastructure Architecture

`scripts/rebuild_daily_azure_environment.py` is the preferred guided daily
orchestration layer for the disposable environment. It owns stable
configuration validation, stage ordering, typed runtime-value propagation,
verification-driven reuse, sanitized approval summaries, stage-specific
operator approval, fail-fast behavior, and one sanitized aggregate readiness
result. It never supplies unattended approval. Resource-group creation,
Foundry infrastructure deployment, Web App infrastructure deployment, and
current package deployment each require approval for the current run and exact
current evidence. An approval is stage-specific and one-use; a changed plan,
package, environment, process, or earlier run cannot reuse it.
The independent deployment, what-if, packaging, read-only verification, RBAC,
readiness, and name-only WebJob discovery boundaries below remain authoritative
for their resource-specific parsing and proof. The manual runbook remains the
recovery, audit, and explicit resource-group adoption path. WebJob trigger and status, hosted managed-identity
verification, and agent invocation remain separately authorized. The
coordinator cannot trigger or read a WebJob run, process intake, send
notifications, or clean up the resource group.

Two resource-group-scoped entry points reuse the
`infra/modules/foundry.bicep` module. `main.bicep` preserves Cosmos DB, Storage,
Log Analytics, and Application Insights and adds Foundry only when
`deployFoundry=true` (default `false`). `foundry-only.bicep` deploys only an
AIServices account, child project, and explicitly parameterized model for
disposable validation. Agent creation remains separate.

The Foundry module preserves deterministic account naming when its optional
explicit name is empty. The daily coordinator supplies a reviewed globally
unique name as a deliberate IaC contract for reusable daily configuration.
When supplied, Bicep enforces the Azure-compatible length, lowercase
alphanumeric-or-hyphen pattern, boundary, and whitespace constraints before
the account resource can deploy.
Reuse requires the exact configured name, repository-owned purpose tag,
security posture, project, model definition, SKU, and capacity to pass the
authoritative read-only verifier; a mismatch stops rather than repairing or
retargeting the resource.

Every Azure-dependent slice must first satisfy its checked-in prerequisite
runbook. Live guided mode reruns the complete offline contract before creating
any live dependency. It verifies the active account and inspects the resource
group. An absent group is created only after approval and receives the exact
daily-purpose tag. An existing group is reused only when location, usable state,
and that ownership tag already match; unowned groups stop for explicit manual
adoption and a rerun.

The Foundry and Web App adapters retain exact identity, scope, parent,
multiplicity, and count/evidence proof for their application resources. They
also recognize `Microsoft.Resources/deployments` only as a sanitized nested
deployment category for operator review. Delete, Modify, malformed, unknown,
unrelated, incomplete, or count-inconsistent evidence stops before prompting.
Safe current evidence is summarized without names or IDs, approved explicitly,
and followed by exactly one deployment request and its separate verifier.
Missing prerequisites, drift, and deterministic failures fail fast without
retry or polling. The current RBAC prerequisite runbook is
`docs/runbooks/live-foundry-agent-consumer-rbac-prerequisites.md`.

The Foundry infrastructure preview boundary reduces Azure's change collection
to sanitized counts, logical categories, nested-deployment presence, and exact
topology evidence. Resource details remain discarded. Safe evidence requires
current operator approval; destructive or incomplete evidence cannot be
approved through the coordinator.

`main.bicep` also references the reusable `infra/modules/web-app.bicep` module
only when `deployApp=true` (default `false`). The module defines a Linux App
Service plan and Web App with a system-assigned managed identity, HTTPS-only
access, disabled FTPS, TLS 1.2 minimums, `/health` health checks, and the actual
`src.app.main:app` FastAPI startup target. Its app settings retain mock
providers and suppressed notifications. It also declares
`SCM_DO_BUILD_DURING_DEPLOYMENT=true`, allowing App Service remote build
automation to install dependencies from the packaged `requirements.txt`. The
module principal ID is available only to its parent; `main.bicep` neither uses
nor publishes that identifier.

`src/app/services/web_app_infra_deployment.py` and
`scripts/deploy_web_app_infra.py` add an explicit operator boundary around that
existing `main.bicep` entry point. Check mode validates required safe arguments,
the template, `deployApp=true`, `deployFoundry=false`, and the mock-safe hosted
settings without constructing an Azure CLI runner. A shared hosting-contract
module owns the exact seven provider/suppression settings used here and by the
configuration verifier. The local Bicep reader is restricted to the Web App
resource's active `siteConfig.appSettings` declaration; missing, extra,
duplicate, conflicting, commented-only, and overriding settings fail. The
separate remote-build setting must also remain exactly enabled.

Explicit `--what-if` or `--live` mode issues exactly one argument-list
`az deployment group` command against an existing resource group; the CLI never
creates the group. What-if explicitly requests JSON and reduces the active
change collection to sanitized create, modify, delete, no-change, ignore,
deploy, and unsupported counts plus exact identity, scope, parent, and
multiplicity match evidence. A repository-computed deterministic naming suffix
is supplied to Bicep so expected Web App boundary identities are known before
the preview is parsed. Resource details and raw CLI output are never exposed.
Proposed deletes are surfaced for manual review but are never acted on
automatically; preview mode never invokes live mode. Live uses a deterministic
deployment name and records only Azure acceptance of the request. It does not
verify configuration, package or upload code, check hosted readiness, assign
RBAC, invoke Foundry, or clean up.

The separate resource-group-scoped
`infra/foundry-agent-consumer-rbac.bicep` entry point reads the principal ID
from an existing Web App and invokes
`infra/modules/foundry-agent-consumer-rbac.bicep`. The module assigns only the
built-in Foundry Agent Consumer role at the existing Foundry project scope,
uses deterministic `guid(...)` naming from the project resource ID, principal
ID, and role-definition ID, and embeds no secret or API key. Application and
Foundry provisioning remain independent and never grant this access
automatically.

`src/app/services/foundry_agent_consumer_rbac_deployment.py` and
`scripts/deploy_foundry_agent_consumer_rbac.py` now provide an offline-tested
operator boundary around that exact entry point. `--check` validates safe names,
the expected file location, its three exact parameters, its existing Web App
identity lookup, its exact module reference, and the module's project-scoped
Consumer-only assignment without constructing a runner or calling Azure.
`--what-if` and `--live` each issue at most one argument-list resource-group
deployment command against an existing group. Neither mode creates or deletes a
group, retries, cleans up, verifies RBAC, obtains a token, invokes an agent,
deploys application code, restarts the Web App, or changes infrastructure.

What-if requests JSON, accepts all seven documented resource change types, and
returns separate sanitized create, delete, ignore, deploy, no-change, modify,
and unsupported counts. Delete, Deploy, or Unsupported entries require manual
review; only Delete sets the separate delete-review flag. Truly unknown values
fail closed, raw output is discarded, and preview never continues to deployment.
Live success records only Azure CLI acceptance
of the deployment request and directs the operator to a separate
read-only assignment verifier. No role-definition override is exposed, and
sanitized results contain no principal, tenant, subscription, token, credential,
or complete resource identifier.

`src/app/services/foundry_agent_consumer_rbac_verification.py` and
`scripts/verify_foundry_agent_consumer_rbac.py` provide that distinct read-only
proof boundary. Offline `--check` reuses the deployment-owned fixed Consumer
role and exact Bicep contract and creates no runner. Only explicit
`--live --json` issues three bounded argument-list reads: the Web App system
identity, the expected Foundry project through dedicated `az cognitiveservices
account project show`, and projected role assignments for that principal and
scope. The project read projects only name and ID, accepts Azure's leaf or
`<account>/<project>` name, validates the Azure-returned ARM ID against the
approved resource-group/account/project tuple, and never constructs that ID.
Azure CLI projections minimize the fields entering Python; the immutable result
exposes only sanitized status booleans, a category, and a next step—not IDs,
endpoints, commands, raw output, errors, or unrelated assignments.

Success requires one unambiguous Consumer assignment for the exact Web App
principal at the exact project scope. Broader inherited assignments, a different
role, a different principal, missing or malformed data, and unknown response
shapes fail closed. Duplicate exact records deterministically return sanitized
`response_parse_failed`. The verifier never deploys or repairs RBAC, acquires a
token, invokes Foundry or an agent, retries, polls, or mutates Azure. Deployment
request acceptance and assignment verification are therefore separate proofs.

`src/app/services/hosted_foundry_agent_verification.py` and the packaged
`src/app/operations/verify_hosted_foundry_agent.py` add the next separate proof
boundary. Check mode validates the configured project endpoint, stable agent
endpoint, agent name, immutable version, model, centralized instructions, and
SDK visibility without reading hosted markers or constructing a credential or
client. Explicit live JSON mode first requires nonblank `WEBSITE_INSTANCE_ID`,
`IDENTITY_ENDPOINT`, and sensitive `IDENTITY_HEADER` markers, then lazily creates only a system-assigned
`ManagedIdentityCredential` and one Foundry project client. It cannot fall back
to developer, CLI, environment-secret, browser, cache, workload, user-assigned,
or interactive credentials.

The App Service-hosted verification command admits only the configured prompt
agent and exact-version metadata reads; it is not a Microsoft Foundry Hosted
Agent product/runtime. A narrow adapter validates SDK shapes, exposes no Responses/inference or
mutation method, and passes metadata into the existing stable-endpoint,
Responses-protocol, exclusive-version-routing, model, and centralized
instruction verifier. Its fixed result excludes endpoints, hostnames,
identities, resource IDs, settings, raw SDK values, exceptions, prompts, and
credentials. Missing, malformed, unauthorized, or drifted responses fail
closed. The command closes the project client and credential synchronously on
every post-construction outcome; cleanup failures are suppressed and cannot
replace the primary result. No live managed-identity verification has run.

The five non-secret values consumed by that verifier now use one optional
tagged configuration from `infra/main.bicep` through
`infra/modules/web-app.bicep` into App Service settings. The default disabled
form requires and writes none of them, preserving ordinary Web App deployment.
Explicit `--enable-hosted-foundry-verifier` requires all five complete,
nonblank values before runner construction. Both raw deployable boundaries,
`main.bicep` and `modules/web-app.bicep`, reject empty, whitespace-only, and
surrounding-whitespace values: each maps any non-exact trimmed value to an empty
nested-module property, whose compiled ARM `minLength: 1` contract fails
deployment validation before Web App settings are emitted. The reusable module
uses a resource-free internal validation template and no experimental Bicep
feature. The read-only
configuration verifier likewise defaults to the baseline
hosting projection; explicit hosted-verifier opt-in projects and exactly
compares all five without serializing either side. The exact seven mock-safe
provider and notification settings remain unchanged, and remote build remains
enabled; this does not enable a live provider in FastAPI.

`App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py` is the sole
allowlisted `App_Data` member in the deterministic Web App package. This thin,
manually triggered Python WebJob calls only the existing hosted metadata
operation with fixed `--live --json` arguments. It accepts no prompt or
configuration override and adds no schedule, continuous job, HTTP route,
credential implementation, persistence, notification, inference, or
invocation path. Before importing `src`, it resolves only the App
Service-provided absolute `HOME`, unconditionally puts the validated
`$HOME/site/wwwroot` first on `sys.path`, fails closed for unexpected preloaded
parent or target modules, and proves after import that the module's resolved
file is exactly the validated HOME-owned operation. Temporary Kudu staging
ancestry, the working directory, and `WEBJOBS_PATH` cannot select the import.

`src/app/services/hosted_foundry_agent_webjob_execution.py` and
`scripts/run_hosted_foundry_agent_verification.py` provide four separate
operator stages. Offline check validates the fixed entry point, package,
Bicep/configuration, and lazy-SDK contracts without a runner. Explicit discovery
performs exactly one name-only read and distinguishes remote discovery from
local package presence. Explicit trigger submits one fixed run request and,
before reading lifecycle state or constructing a runner, atomically creates one
fixed exclusive reservation beneath
`.artifacts/hosted-foundry-agent-webjob/`. The reservation excludes concurrent
trigger processes sharing that repository artifact filesystem; it is not a
distributed lock across machines or checkouts. Accepted context is atomically
recorded once in immutable `accepted-trigger.json`. Receipt-persistence failure
after acceptance creates immutable `blocked-trigger.json`; if both writes fail,
the reservation is preserved for manual investigation. After runner entry, a
nonzero return, timeout, exception, or empty, malformed, or unknown acceptance
response is ambiguous and creates the same immutable blocked state before
reservation release. Only the repository-owned process-not-started exception
conclusively proves a local pre-submission failure and permits a later explicit
attempt. There is no automatic expiry, cleanup, reset, or retrigger path.

Explicit status requires the immutable resource/app/job receipt before runner
construction, discards runs before its UTC lower bound, and requires exactly one
eligible known run. It never changes the receipt. A correlated terminal success
or failure is atomically recorded separately in immutable
`terminal-outcome.json`; repeated status returns that sanitized recorded result
without another Azure read, while mismatched or conflicting evidence fails
closed. Descriptor-relative no-follow reads reject symlinked state parents,
targets, and nonregular files. Trigger acceptance is never metadata success;
only the single receipt-correlated terminal `Success` can prove the operation
exited successfully. Raw history, timestamps, lifecycle contents, paths, lock
information, logs, identifiers, endpoints, and operator values are never
serialized.
The boundary has only offline test evidence; no WebJob was deployed, discovered,
triggered, or read live in this slice.

`src/app/services/hosted_foundry_agent_invocation.py` and the packaged
`src/app/operations/invoke_hosted_foundry_agent.py` implement the following,
strictly separate fictional-data invocation proof. Check mode validates local
configuration, the fixed repository-owned fictional request, the expected
application contract, and lazy SDK visibility without reading App Service
identity markers, creating a credential or client, or performing inference.
Only explicit live JSON mode can continue. It requires valid nonblank
`WEBSITE_INSTANCE_ID`, `IDENTITY_ENDPOINT`, and sensitive `IDENTITY_HEADER`
values before constructing dependencies, uses system-assigned
`ManagedIdentityCredential()` with no client ID or credential fallback, and
submits the fixed request exactly once through the existing stable per-agent
Responses path.

The hosted invocation validates extraction, advisory urgency, summary, and the
application-generated handoff note through existing contracts. Its result
contains only status, safe category/message, invocation and validation
booleans, approved field names, the fictional-data flag, and a next step. It
never returns prompt or patient text, generated clinical content, endpoints,
agent identifiers, identity values, raw responses, exceptions, or credentials.
The owned Responses/project client is closed before the credential on every
post-construction result; partial construction and cleanup failures are also
sanitized. This operation does not call an intake route or metadata verifier,
persist a case, send or record notifications, run deterministic urgency rules,
change RBAC, provision or modify an agent, alter infrastructure, or repeat the
request. Automated tests make no Azure calls, and neither live hosted metadata
verification nor live hosted invocation ran in this slice.

Project scope permits the identity to interact with agent endpoints in that
project without granting agent creation or modification. Agent-specific scope
is deferred because prompt-agent provisioning remains a separate lifecycle and
the full-stack Bicep deployment does not own the agent resource.

`src/app/services/web_app_configuration_verification.py` and
`scripts/verify_web_app_configuration.py` add a read-only proof boundary for an
already-existing Web App before code deployment. Check mode validates the local
contract without creating an Azure CLI runner. Only explicit `--live --json`
uses three read-only Azure CLI commands with explicit JSON output projections.
JMESPath `--query` shapes the JSON emitted to the Python verifier; it does not
limit what Azure reads. The baseline app-settings projection emits only the
eight hosting settings; hosted-verifier opt-in adds the five verifier names.
The application never returns, logs, or serializes raw unfiltered Azure CLI
output.
The verifier checks successful provisioning, Linux `PYTHON|3.12`, the current
uvicorn startup command, remote build, HTTPS-only access, disabled FTPS, TLS
1.2 minimums, `/health`, system-assigned identity presence, mock providers, and
suppressed notifications. Its immutable result never exposes resource or
identity IDs, hostnames, raw settings, command output, errors, or secrets.

`WebAppPackage` and the two thin CLIs add the next offline-tested boundaries.
The package service selects only the root dependency manifest and required
`src` Python, configuration, and static assets; it rejects unsafe paths and
symlinks, then writes a stably ordered, timestamp-normalized source deployment
ZIP beneath the ignored `.artifacts/` directory. `.env`, Bicep parameter, test,
documentation, cache, repository metadata, and prior artifact content cannot
enter through the allowlist. It deterministically hashes the approved source
members and explicitly adds one generated application marker containing that
digest. Package deployment requires an opaque authorization issued for the
current coordinator run and bound to the source root, member set, ZIP path, and
exact bytes. Authorization is one-use; forgery, replay, a prior-run proof,
rebuild, replacement, mutation, or symlink fails closed. Neither the proof nor
its token, nonce, digest, hash, or path is serialized.
After code-deployment approval, no-follow file access copies the validated ZIP
into a unique current-run directory. Exclusive creation rejects pre-existing
and symlink targets, directory and file permissions are restrictive, and the
copied bytes are verified before runner entry. The one-use authorization is
then consumed, only the transient path reaches the Azure CLI, and that path is
invalidated after the request.

`scripts/package_web_app.py` performs local package checks and builds.
`scripts/deploy_web_app_code.py` keeps check, package, and explicit live modes
separate. Only `--live --json` with an existing resource group and Web App name
can issue one `az webapp deploy` command through an injected runner. The result
distinguishes package creation, deployment request acceptance, and hosted
verification; it never treats one as evidence of the next.

`src/app/services/web_app_readiness_verification.py` and
`scripts/verify_web_app_readiness.py` implement the next read-only boundary for
an already-existing, already-deployed Web App. Check mode validates an explicit
absolute HTTPS origin without constructing an HTTP transport. Only explicit
`--live --json` creates the standard-library transport and makes one bounded,
sequential GET request each to `/health`, `/version`, and `/demo/status`, with
no credentials, body, retry, polling, mutation, Azure discovery, RBAC action,
or Foundry call. The packaged `/version` route reads only its fixed marker and
returns the source artifact digest; a missing or malformed hosted marker fails
safely, while local development may explicitly report `unpackaged`. The
coordinator passes the current package digest internally to readiness, which
requires an exact match before setting `application_artifact_current=true`. A
healthy old worker cannot produce READY. The result exposes only
application-owned booleans and sanitized categories; it never serializes the
digest, origin, hostname, response body, marker contents, or exception details.

The ZIP contains Python source plus `requirements.txt`, including this packaged
operation and its Foundry project SDK dependency; dependencies are not vendored.
The Web App module now declares the required
`SCM_DO_BUILD_DURING_DEPLOYMENT=true` application setting so App Service remote
build automation can install those dependencies. The compiled Bicep/ARM
contract, configuration proof, code-deployment acceptance, and hosted startup
remain separate proof boundaries.

The coordinator's daily sequence is:

```text
account verification and owned resource-group inspection
-> approve absent resource-group creation, or stop for manual adoption
-> exact Foundry preview and operator approval when absent
-> one Foundry deployment request and verification
-> prompt-agent provisioning, exclusive routing, and immutable-version verification
-> exact Web App preview and operator approval when absent
-> one Web App deployment request and configuration verification
-> current-run deterministic source package and code-deployment approval
-> immutable package handoff and one code-deployment request
-> hosted package-digest and mock-safe readiness verification
-> direct Consumer RBAC verification
-> stop for the separate manual RBAC workflow when the assignment is missing
-> optional name-only WebJob discovery
-> READY
```

On rerun after that manual workflow, the coordinator verifies the exact direct
assignment and continues; it never previews or deploys RBAC itself. Each arrow
is a separate boundary. Code deployment does not provision
infrastructure, alter app settings, assign RBAC, verify startup, or call
Foundry. Configuration verification does not prove code deployment;
deployment-request acceptance does not prove startup. Hosted defaults remain
mock-only with notifications suppressed, and human nurse review remains
mandatory.

Infrastructure deployment, code deployment, readiness, manual RBAC deployment,
RBAC verification, Web App-hosted managed-identity prompt-agent verification,
and fixed fictional invocation remain separate stages. Mock defaults and
notification suppression remain unchanged, and every fictional result still
requires human nurse review. The project remains a capstone/demo and is not
production clinical software.

`infra/main.bicep` is a minimal resource-group-scope Azure baseline for the
capstone. It provisions:

- Cosmos DB account
- Cosmos SQL database
- `cases` container with partition key `/createdDate`
- Storage account
- Log Analytics workspace
- Application Insights component
- Optional Linux App Service plan and Web App hosting contract

The infrastructure files contain no secrets. Deployment acceptance never proves
configuration, code deployment, startup, managed-identity access, or agent
behavior; each remains a separately authorized and verified boundary.

Deferred infrastructure:

- Agent-specific RBAC scope
- Key Vault
- App Service Authentication
- Private networking
- Production monitoring
- Durable background worker infrastructure
- Production clinical security or compliance

## 10. Deferred / Future Architecture

The following are intentionally not implemented in the current MVP:

- Hosted managed-identity verification and invocation
- Agent-specific RBAC scope
- Authentication / RBAC beyond the proven direct Consumer assignment
- Application authentication and private networking
- Key Vault
- Azure Speech / voice intake
- Live Azure AI Foundry extraction
- ACS SMS delivery reports/status tracking
- Retry logic
- Production frontend
- Production clinical workflow, audit, compliance, and security hardening
- Cosmos queue-summary and voicemail-idempotency lookup parity
- Durable queues or background worker processing
- Autonomous medical decision-making

These items should remain clearly separate from the implemented local mock MVP
unless the project scope explicitly changes.

## 11. AI-103 Alignment

This architecture demonstrates AI-103-relevant concepts without overstating the
implementation:

- Azure AI Foundry provider boundary through `FoundryAiService` and
  `create_ai_service(settings)`
- Azure Speech readiness through an offline transcription provider boundary and
  Azure Speech scaffold
- Natural language extraction, summarization, and advisory classification
  concept through the deterministic mock provider
- Responsible AI boundary through explicit human nurse review and no autonomous
  clinical action
- Azure service integration boundaries for Cosmos DB, ACS Email, ACS SMS,
  storage, Application Insights, and Log Analytics
- Infrastructure-as-code baseline through Bicep
- Monitoring baseline concepts through Application Insights and Log Analytics

Live Azure AI Foundry extraction, live Azure Speech transcription/audio
processing, production hosting, authentication, Key Vault, and SMS delivery
tracking remain deferred.
