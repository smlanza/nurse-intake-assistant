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
| `FoundryAiService` | Implemented opt-in Foundry structured-extraction provider with an application-owned prompt/schema/parser contract, injected fake-client seam, and lazy live adapter obtained through `AIProjectClient.get_openai_client()` |
| `NurseIntakeAgent` | Implemented application-integrated Agent boundary; output is contract-validated before case processing trusts it, and invalid output uses a safe fallback |
| Offline Foundry evaluation | Strictly validates a repository-owned fictional v1 dataset and provider-neutral candidate contract, then produces deterministic per-case evidence and sanitized aggregate metrics |
| `FoundryAgentVerification` | Explicit read-only boundary that validates stable-endpoint metadata, reads Responses support from `agent_endpoint.protocols`, verifies exclusive immutable-version routing, and compares the configured version definition without mutation or invocation |
| `HostedFoundryAgentInvocation` | Separate packaged proof boundary for exactly one fixed fictional prompt-agent invocation from an App Service system identity; validates only the application-owned output contract and returns no clinical content |
| `HostedFoundryAgentProof` | Packaged synchronous combined proof operation that composes the existing metadata verification and fixed-fictional invocation boundaries with exact result validation; direct operator-supervised App Service SSH is the selected future transport |
| `HostedFoundryAgentSshTransport` | Offline-tested transport lifecycle for one tunnel process created through `create-remote-connection`, bounded readiness, two fixed `APP_PATH` probes, one packaged check, private output handling, and guaranteed termination/reaping |
| Speech transcription services | Mock transcript handling remains the default; the opt-in Azure service uses a lazy SDK adapter with injected-fake tests, in-memory audio input, application-owned normalized outcomes, and sanitized failures. The standalone provider boundary is live-proven for one repository-owned fixed-fictional WAV through the production factory, service, and adapter, isolated from routes and side effects |
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
voicemail route expects already-transcribed text only and never invokes a Speech
provider. Separately, `SPEECH_PROVIDER=azure` selects an application-owned
transcription service whose SDK adapter is constructed lazily for one explicit
in-memory audio request. The standalone proof CLI is separate from application
route processing. The Azure Speech adapter was live-proven using the fixed
repository fixture: exactly one recognition attempt returned the expected
normalized text, with no persistence, notification, or clinical processing.
The normal FastAPI intake pipeline remains text-only. Route-integrated audio
ingestion and voice workflows are not implemented.

The default local settings are:

```text
APP_MODE=mock
AI_PROVIDER=mock
SPEECH_PROVIDER=mock
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

`FoundryAiService` is an implemented opt-in Foundry structured-extraction
provider. Its deterministic prompt instructions, expected JSON fields, and
parser validation map model responses into the existing extraction and urgency
output models. The live adapter constructs SDK resources lazily and obtains its
inference client through `AIProjectClient.get_openai_client()` while preserving
the injected fake-client seam for offline tests. The normal intake path and the
fixed-fictional structured-extraction smoke share the production
`compose_application(settings)` composition boundary.

Application-integrated structured extraction is live-proven with valid
structured output, no fallback, deterministic urgency-rule evaluation,
in-memory persistence, suppressed notifications, mandatory nurse review, and
no Azure mutation. Mock providers remain the safe defaults, and automated
tests remain offline.

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

`NurseIntakeAgent` is an implemented application-integrated Agent boundary.
Application-integrated Agent execution is live-proven with valid Agent output,
no fallback, deterministic urgency-rule execution, in-memory persistence,
suppressed notifications, mandatory nurse review, and no Azure mutation.
Neither application-integrated execution mode proves hosted managed-identity
token acquisition, hosted Foundry metadata access, or hosted Foundry
invocation.

### Offline Evaluation Boundary

The reusable offline evaluation flow is:

```text
repository-owned fictional evaluation dataset
-> strict validation
-> provider-neutral candidate contract
-> deterministic scorer
-> sanitized metrics
```

The canonical candidate contract covers structural contract validity,
application-owned structured fields, symptoms, missing fields, advisory and
final urgency, deterministic-rule outcome, mandatory nurse review, and
nonblank summary structure. Scoring uses trimmed exact structured-field
equality and case-folded order-independent sets for symptoms and missing
fields. Undefined zero-denominator precision, recall, and F1 values are
reported as `0.0`.

Per-case evidence contains only stable case IDs, counts, match booleans, and
safe error categories. Aggregate output contains only the dataset identifier,
version, deterministic counts and rates, and sorted per-case evidence. The
boundary does not invoke a provider or Agent, access Azure or the network,
process a runtime intake, persist a case, or send or record a notification. It
is not a live Foundry evaluation, model-as-judge evaluation, or clinical
validation.

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
result. It never supplies unattended approval. After offline validation,
readiness-receipt revocation, and current-account verification, it invokes the
repository cleanup service in startup-preflight mode before resource-group
creation or Foundry deployment. That boundary reuses a conclusively healthy
owned environment, stops on ambiguous or unowned state, and requires a
separate current-run, one-use approval before deleting proven stale owned state
or purging independently classified, bounded repository-owned Foundry
`AIServices` or Speech `SpeechServices` tombstones. Cleanup must conclusively
prove required tombstone absence before the coordinator continues; a fresh
resource-group creation additionally requires resource-group absence.
Resource-group creation, Foundry
infrastructure deployment, Web App infrastructure deployment, and current
package deployment retain their own current-evidence approvals; changed
evidence cannot reuse an approval.

The daily disposable coordinator ends at verified application-hosting
readiness. It verifies Foundry infrastructure, prompt-agent identity and
immutable routing, Web App infrastructure and configuration, the current
application artifact, and hosted readiness. It returns success immediately
after those proofs. Consumer RBAC remains one of the separate, explicitly
invoked optional workflows outside readiness. WebJob discovery and
immutable-evidence recovery remain separate technical boundaries, while the
current WebJob
trigger-and-correlation path is retired from supported operations.
Managed-identity access, metadata verification, and hosted agent invocation
remain unproven and are not daily readiness requirements. A packaged
synchronous combined proof operation is present in the ordinary application
package, but no live SSH, managed-identity metadata access, or hosted Agent
invocation is proven. The independent
deployment, packaging, read-only verification, RBAC, readiness, and WebJob
lifecycle boundaries below remain authoritative for their resource-specific
parsing and proof. Intake processing and notifications remain outside
infrastructure orchestration. The only normal operator sequence is
`docs/runbooks/daily-azure-operator-runbook.md`.

After READY, a separate explicitly invoked handoff-preparation boundary
validates the current non-revoked readiness receipt, revalidates the hosted
package, and performs only projected read-only Web App identity and Foundry
project reads. It constructs the existing environment-generation evidence
without reading Consumer role assignments and persists only its opaque
fingerprint and readiness correlation in private immutable
`generation-handoff.json` beneath the WebJob lifecycle directory. Discovery
validates the same unchanged readiness receipt and private handoff before
constructing an Azure runner. The preserved retired trigger and status
implementation applies the same validation. The fingerprint and its source
identifiers are never operator inputs or serialized command output. Preparation
cannot discover, trigger, or inspect a WebJob and does not change daily READY.

WebJob installation is a separate generation-bound deployment boundary. The
ordinary deterministic Web App package excludes `App_Data` and cannot imply
WebJob installation. A repository-owned builder creates a deterministic ZIP
whose exact member allowlist is only `run.py`. Its single artifact root is
`.artifacts/hosted-foundry-agent-webjob-package/`, while immutable generation
and trigger evidence remains exclusively under
`.artifacts/hosted-foundry-agent-webjob/`; neither boundary may create entries
in the other. A current-run one-use
authorization binds those bytes to the unchanged source, READY receipt,
immutable generation handoff, fixed Web App, and fixed WebJob name. After a
default-no operator approval, the boundary revalidates the complete shared
environment-generation fingerprint before one Kudu
`PUT /api/triggeredwebjobs/verify-hosted-foundry-agent` request. Upload
acceptance is distinct from one subsequent authoritative Kudu
`GET /api/triggeredwebjobs/verify-hosted-foundry-agent` discovery. The GET uses
the same validated Entra bearer-token boundary as upload and accepts only the
exact fixed name and `run.py` command. A missing or null `latest_run` is valid
before the first trigger and proves no execution. All other externally owned
top-level Kudu fields are discarded without becoming evidence; their presence
or values cannot affect success or enter output. Kudu is authoritative for both
dedicated installation and discovery; the Azure CLI triggered-WebJob list is
not used. The boundary then stops with every trigger, execution, metadata, and
invocation proof false. It is unreachable from application startup, case
processing, ordinary Web App deployment, and the daily rebuild coordinator.

The one-file WebJob bootstrap imports repository operations only from validated
`$HOME/site/wwwroot`. Third-party dependencies resolve only through the
platform-selected Python interpreter's validated `sys.prefix` or
`sys.base_prefix`; temporary Kudu/ZipDeploy paths, the working directory,
`APP_PATH`, and inferred Oryx environment paths are not trusted. Unsafe or
missing runtime bindings fail before metadata verification or invocation.
Generation changes or package changes after approval invalidate authorization,
and immutable lifecycle evidence can be retired only through the separate
evidence-preserving recovery boundary.

One transitional recovery contract handles only the already-produced legacy
shape consisting of a valid 0600 `generation-handoff.json` plus a 0700
`package/` directory containing exactly one regular 0600 fixed-name ZIP. Normal
inspection still rejects every directory beneath the active lifecycle root.
Only an explicit legacy-conflict flag enables descriptor-relative, no-follow,
exact-mode and exact-ZIP validation; its manifest binds the package digest
without serializing that digest. A separately approved archive revalidates the
same manifest and atomically retires the complete unchanged directory with an
immutable external receipt. Extra entries, replacement, mutation, symlinks, or
permission drift fail closed.

The same cleanup service owns exact bounded Foundry and Speech tombstone
policies for the startup and explicit standalone end-of-day boundaries. It
requires independent conclusive ownership classification under the configured
subscription context, resource group, location, ownership tags, and bounded
naming contracts; conclusively unrelated records are ignored, while malformed,
contradictory, or ambiguous records fail closed. It deletes or purges no
unowned account, never adopts by name, and never acts on an active exact-name
conflict outside the owned group. Cleanup requires separate current-run,
default-no approval bound to the complete evidence, synchronous group deletion
when required, and final read-only proof of resource-group, Foundry-tombstone,
and Speech-tombstone absence. Operational commands remain in the canonical
daily Azure operator runbook.

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
retry or polling. Optional RBAC operator use is Step 5 of
`docs/runbooks/daily-azure-operator-runbook.md`; the older RBAC file is an
implementation reference only.

The Foundry infrastructure preview boundary reduces Azure's change collection
to sanitized counts, logical categories, nested-deployment presence, and exact
topology evidence. Resource details remain discarded. Safe evidence requires
current operator approval; destructive or incomplete evidence cannot be
approved through the coordinator.

`infra/main.bicep` remains the full initial application infrastructure entry
point and references the reusable `infra/modules/web-app.bicep` module only
when `deployApp=true` (default `false`). For verified drift on an existing Web
App, the deployment boundary invokes `infra/modules/web-app.bicep` directly
with the existing App Service plan name and plan deployment disabled. The
nested reconciliation wrapper has been removed. Reconciliation therefore
targets only the existing `Microsoft.Web/sites` resource and does not redeploy
the plan, Cosmos, Storage, monitoring, Foundry, or RBAC. The module otherwise
defines a Linux App Service plan and Web App with a system-assigned managed
identity, HTTPS-only access, disabled FTPS, TLS 1.2 minimums, `/health` health
checks, and the actual `src.app.main:app` FastAPI startup target. The direct
`siteConfig` property
`alwaysOn=true` and baseline app setting
`WEBSITE_SKIP_RUNNING_KUDUAGENT=false` enable the repository-packaged manually
triggered Linux WebJob runtime. The former is site configuration; the latter is
not part of the optional Foundry verifier settings. This does not schedule or
continuously run the WebJob. App settings retain mock providers, suppressed
notifications, and `SCM_DO_BUILD_DURING_DEPLOYMENT=true`, allowing App Service
remote build automation to install dependencies from the packaged
`requirements.txt`. The module principal ID is available only to its parent;
`main.bicep` neither uses nor publishes that identifier.

`src/app/services/web_app_infra_deployment.py` and
`scripts/deploy_web_app_infra.py` add an explicit operator boundary around both
purposes. Initial creation requires `infra/main.bicep`; the nondefault
`--reconcile-existing-web-app` purpose requires
`infra/modules/web-app.bicep`. Purpose/template mismatches fail before
Azure CLI execution. Check mode validates required safe arguments, the selected
template, and the mock-safe hosted settings without constructing an Azure CLI
runner. A shared hosting-contract
module owns the exact seven provider/suppression settings used here and by the
configuration verifier, plus the exact remote-build and Kudu-agent baseline
settings. The local Bicep reader is restricted to the Web App resource's active
`siteConfig` declaration. It requires direct `alwaysOn=true` and exactly one
baseline `WEBSITE_SKIP_RUNNING_KUDUAGENT=false`; missing, extra, duplicate,
conflicting, commented-only, and overriding settings fail. A setting placed
only in the optional verifier collection also fails.

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

The daily coordinator selects full initial creation only when read-only
verification proves the Web App absent. When an existing Web App has
hosting-contract drift, the daily coordinator fails closed and does not enter
the reconciliation boundary. Operators may recreate the disposable resource
group through the normal fresh-build path or invoke the separate supervised Web
App deployment workflow. That standalone reconciliation policy requires exactly one resource-level
`Microsoft.Web/sites` `Modify`, zero Create, Deploy, Delete, Unsupported, or
unknown actions, and currently zero Ignore or NoChange records. An exact App
Service plan reference may be permitted only after a direct live preview proves
its identity, scope, parent, type, and multiplicity. Unidentified references
and the full-application topology remain rejected. The exact preview receives
resource-level default-no approval, followed by an identical fresh preview,
one reconciliation deployment, and separate read-only configuration
verification. It is not part of daily coordinator readiness.

The separate resource-group-scoped
`infra/foundry-agent-consumer-rbac.bicep` accepts the exact approved principal,
project resource ID, and deterministic assignment name, independently reads
the existing Web App identity and Foundry project, and enforces equality before
invoking
`infra/modules/foundry-agent-consumer-rbac.bicep`. The module assigns only the
built-in Foundry Agent Consumer role at the existing Foundry project scope,
uses deterministic `guid(...)` naming from the project resource ID, principal
ID, and role-definition ID, and embeds no secret or API key. Application and
Foundry provisioning remain independent and never grant this access
automatically.

`src/app/services/foundry_agent_consumer_rbac_deployment.py` and
`scripts/deploy_foundry_agent_consumer_rbac.py` now provide an offline-tested
operator boundary around that exact entry point. `--check` validates safe names,
the expected file location, its six exact parameters, its existing Web App
identity lookup, its exact module reference, and the module's project-scoped
Consumer-only assignment without constructing a runner or calling Azure.
Explicit `--what-if` is diagnostic-only: it issues at most one argument-list
resource-group preview command, reduces recognized output to bounded sanitized
counts and safe categories, and may fail parsing when Azure emits an unstable
symbolic assignment identity. A preview never authorizes or invokes deployment,
and `--live` never invokes What-if.

Live first validates the current coordinator handoff and exact repository-owned
Bicep contract, then uses the exact read-only assignment verifier. One proven
direct assignment is reused without approval or mutation. Only a conclusive
missing assignment can reach a default-no, current-run approval bound to the
handoff, principal, project, fixed Consumer role, deterministic assignment, and
Bicep contract. Fresh matching evidence permits exactly one existing
resource-group Bicep deployment request, followed immediately by the same exact
read-only verifier. Request acceptance alone is not success; success requires
one direct assignment for the exact principal, project scope, and role.
Ambiguous, duplicate, inherited-only, malformed, mismatched, stale, or unknown
evidence fails closed without retry or repair. The boundary never uses an ad
hoc role-assignment command, creates infrastructure, obtains a token, invokes an
agent, deploys application code, restarts the Web App, or cleans up. Raw Azure
output and identifiers are never serialized.

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

`App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py` is the sole source
for the separate deterministic WebJob-only package; the ordinary deterministic
Web App package excludes `App_Data`. This thin,
manually triggered Python WebJob performs the fixed sequence of hosted metadata
verification followed by one fixed-fictional invocation, then emits one
combined sanitized JSON result. Invocation occurs only when the exact
application-owned metadata result type and every required proof boolean pass;
the invocation result is validated with the same exact-type and exact-boolean
contract. It accepts no prompt or configuration override and adds no schedule,
continuous job, HTTP route, credential implementation, persistence, or
notification path. Before importing `src`, it resolves only the App
Service-provided absolute `HOME`, unconditionally puts the validated
`$HOME/site/wwwroot` first on `sys.path`, fails closed for unexpected preloaded
parent or target modules, and proves after import that the module's resolved
file is exactly the validated HOME-owned operation. Temporary Kudu staging
ancestry, the working directory, and `WEBJOBS_PATH` cannot select the import.

`src/app/services/hosted_foundry_agent_webjob_execution.py` and
`scripts/run_hosted_foundry_agent_verification.py` retain the offline check,
fixed-resource discovery, trigger, blocked-trigger reconciliation, and status
implementation. Offline check and one-read Kudu discovery remain distinct
technical boundaries. Discovery proved the fixed registered WebJob, but it
does not prove trigger acceptance, execution, managed-identity access,
metadata, or invocation.

The trigger-and-correlation modes are retired from supported operations.
Multiple fresh supervised trigger attempts returned
`trigger_acceptance_ambiguous`, and Azure exposed no safely correlatable
execution record for those attempts. This does not mean Azure WebJobs are
universally impossible; this specific implementation was not reliably
provable enough for the capstone. The executable's `--live-trigger`,
`--live-reconcile-blocked-trigger`, and `--live-status` modes require a future
explicit architecture decision before reuse.

The retired implementation still preserves its fail-closed evidence model for
audit and recovery. Before trigger-runner construction it created one exclusive
reservation beneath `.artifacts/hosted-foundry-agent-webjob/`; accepted context
used immutable `accepted-trigger.json`, ambiguous acceptance used
`blocked-trigger.json`, and correlated terminal state used separate
`terminal-outcome.json`. The reservation is local to one repository artifact
filesystem, not a distributed lock.

The retired blocked-trigger reconciliation contract constructed no trigger
runner and performed exactly one history read. Runs before the blocked
trigger's immutable UTC lower bound are discarded. Exactly one eligible known
run could create private exact-run correlation; Zero or multiple eligible runs,
malformed history, and unknown states remained blocked. Retired reconciled
status selected only that exact private run and never falls back to the latest
run. Trigger, blocked-trigger reconciliation, status, metadata proof, and
invocation remain separate in the preserved implementation, but they are not a
supported operator sequence.

Stale or generation-mismatched immutable lifecycle evidence is never deleted,
reset, adopted, or converted by the coordinator. The separate offline recovery
service inspects it with descriptor-relative no-follow reads, produces a
sanitized digest-bound manifest, and can retire only unchanged, nonconflicting
evidence after a default-no manual approval. Retirement atomically moves the
whole active directory to a sibling archive and adds an immutable external
retirement receipt; it cannot trigger a WebJob or produce READY. This remains
an evidence-preservation mechanism. The exceptional operator procedure is in
`docs/runbooks/daily-azure-operator-runbook.md`.

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
request. Capability and offline validation do not claim a successful live
hosted proof.

`src/app/services/hosted_foundry_agent_proof.py` and
`src/app/operations/prove_hosted_foundry_agent.py` form the packaged synchronous
combined proof operation. It composes the existing metadata verification and
fixed-fictional invocation boundaries without reimplementing their credential,
SDK, prompt, parsing, or cleanup behavior. Exact authoritative metadata proof
must complete before exactly one invocation can occur, and the invocation must
return the exact authoritative application-contract success result. Every
other type, boolean, category, or exception fails closed with sanitized status
only.

The operation is selected by the ordinary application package's existing
`src` allowlist; no `App_Data` member or separate package is involved. It is not
exposed through an application route and has no persistence, notification,
case-processing, deterministic-rule, arbitrary-input, or Azure-mutation path.
Operator-supervised direct App Service SSH to the existing Linux application
container remains the selected future execution transport.
`HostedFoundryAgentSshTransport` owns exactly one
`az webapp create-remote-connection` process with a fixed loopback boundary,
one deadline, bounded readiness observation, private raw-output capture, and
interrupt/terminate/kill shutdown followed by reaping. It permits only two
fixed prerequisite probes and one packaged non-invoking check. Both probes use
the active Oryx application root only through `APP_PATH`; no fixed deployment
path or filesystem search is permitted. The preview `az webapp ssh` mechanism
is unsupported. No additional compute resource, Kudu command execution, or HTTP
proof endpoint is part of this boundary. Live SSH remains unproven, as do managed-identity
metadata access and hosted Agent invocation. The WebJob trigger-and-correlation
mechanism remains retired.

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
nine hosting settings; hosted-verifier opt-in adds the five verifier names.
The application never returns, logs, or serializes raw unfiltered Azure CLI
output.
The verifier checks successful provisioning, Linux `PYTHON|3.12`, the current
uvicorn startup command, `alwaysOn=true`, remote build,
`WEBSITE_SKIP_RUNNING_KUDUAGENT=false`, HTTPS-only access, disabled FTPS, TLS
1.2 minimums, `/health`, system-assigned identity presence, mock providers, and
suppressed notifications. Deployment validation and this read-only verifier
both enforce the WebJob prerequisites. Its immutable result never exposes
resource or identity IDs, hostnames, raw settings, command output, errors, or
secrets.

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
The Web App module declares the required
`SCM_DO_BUILD_DURING_DEPLOYMENT=true` and
`WEBSITE_SKIP_RUNNING_KUDUAGENT=false` application settings plus the direct
`alwaysOn=true` site configuration. The compiled Bicep/ARM contract,
configuration proof, code-deployment acceptance, hosted readiness, WebJob
discovery, explicit trigger, receipt-correlated status, metadata verification,
and invocation remain separate proof boundaries.

The coordinator keeps infrastructure deployment, code deployment, hosted
readiness, and their preceding verification boundaries as distinct required
proofs. It may perform bounded repeated deployment-record reconciliation and
bounded repeated calls to the one-shot hosted-readiness verifier to tolerate
Azure control-plane and App Service startup convergence. The coordinator owns
one absolute deadline for each convergence stage and bounds each dependency
call by the stage's remaining budget. It supplies the required absolute
deployment-reconciliation deadline to every reconciliation path and checks it
before and after each bounded Azure history read; evidence returned at or after
the deadline cannot establish terminal deployment proof. A
deployment-submission response is not terminal deployment proof; READY requires
terminal evidence attributable to the current deployment command and exact
current-artifact readiness proof.
Every convergence read remains fail-closed, and deployment acceptance never
substitutes for hosted readiness. Consumer RBAC, generation-bound WebJob
execution, managed-identity metadata verification, and fixed fictional
invocation remain outside the coordinator; their false result fields mean they
were not part of the coordinator run. Consumer RBAC remains optional. The
current WebJob execution path is retired, and metadata verification and
invocation remain unproven. The supported candidate is the packaged synchronous
proof operation behind the owned one-process SSH transport lifecycle and its
separate approvals; the WebJob trigger-and-correlation mechanism remains
retired.
Hosted defaults remain mock-only with
notifications suppressed. Code deployment does not provision infrastructure,
and human nurse review remains mandatory for every fictional result. The
project remains a capstone/demo rather than production clinical software.

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
- Route-integrated audio ingestion, audio upload, microphone capture, ACS
  recording ingestion, voice intake and call automation, streaming
  transcription, audio retention/cleanup, and production audio workflows
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

- Implemented Azure AI Foundry structured-extraction and Agent runtime
  boundaries through `FoundryAiService`, `NurseIntakeAgent`, and production
  application composition
- Offline packaged hosted proof composition with direct App Service SSH as the
  selected future supervised transport; live hosted managed-identity access
  remains unproven and the WebJob trigger mechanism remains retired
- Azure Speech through a lazy SDK adapter boundary that is offline-tested with
  injected fakes and live-proven for one standalone fixed-fictional fixture,
  while intake routes remain text/already-transcribed-text only
- Natural language extraction, summarization, and advisory classification
  concept through the deterministic mock provider
- Responsible AI boundary through explicit human nurse review and no autonomous
  clinical action
- Azure service integration boundaries for Cosmos DB, ACS Email, ACS SMS,
  storage, Application Insights, and Log Analytics
- Infrastructure-as-code baseline through Bicep
- Monitoring baseline concepts through Application Insights and Log Analytics

Hosted managed-identity Foundry access and invocation, route-integrated audio
ingestion and voice workflows, authentication, Key Vault, and SMS delivery
tracking remain deferred.
