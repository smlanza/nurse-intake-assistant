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

Two resource-group-scoped entry points reuse the
`infra/modules/foundry.bicep` module. `main.bicep` preserves Cosmos DB, Storage,
Log Analytics, and Application Insights and adds Foundry only when
`deployFoundry=true` (default `false`). `foundry-only.bicep` deploys only an
AIServices account, child project, and explicitly parameterized model for
disposable validation. Agent creation remains separate.

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

The separate resource-group-scoped
`infra/foundry-agent-consumer-rbac.bicep` entry point reads the principal ID
from an existing Web App and invokes
`infra/modules/foundry-agent-consumer-rbac.bicep`. The module assigns only the
built-in Foundry Agent Consumer role at the existing Foundry project scope,
uses deterministic `guid(...)` naming from the project resource ID, principal
ID, and role-definition ID, and embeds no secret or API key. Application and
Foundry provisioning remain independent and never grant this access
automatically.

Project scope permits the identity to interact with agent endpoints in that
project without granting agent creation or modification. Agent-specific scope
is deferred because prompt-agent provisioning remains a separate lifecycle and
the full-stack Bicep deployment does not own the agent resource.

`WebAppPackage` and the two thin CLIs add the next offline-tested boundaries.
The package service selects only the root dependency manifest and required
`src` Python, configuration, and static assets; it rejects unsafe paths and
symlinks, then writes a stably ordered, timestamp-normalized source deployment
ZIP beneath the ignored `.artifacts/` directory. `.env`, Bicep parameter, test,
documentation, cache, repository metadata, and prior artifact content cannot
enter through the allowlist.

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
or Foundry call. The result exposes only application-owned booleans and
sanitized categories; it never serializes the origin, hostname, response body,
or exception details.

The ZIP contains Python source plus `requirements.txt`; dependencies are not
vendored. The Web App module now declares the required
`SCM_DO_BUILD_DURING_DEPLOYMENT=true` application setting so App Service remote
build automation can install those dependencies. This configuration is tested
only against the compiled Bicep/ARM representation. The readiness verifier is
also tested offline with fake transports, but no live Web App infrastructure
deployment, code deployment, application startup, health check,
managed-identity authentication, Foundry verification, or agent invocation has
occurred. Deployment-request acceptance and hosted startup remain separate
proof boundaries.

The intended operator sequence is:

```text
Foundry infrastructure
-> optional Linux Web App with system-assigned identity
-> reviewed App Service Python build-automation prerequisite
-> deterministic source deployment package
-> explicit Web App code deployment-request acceptance
-> explicit hosted health/readiness verification
-> explicit Foundry Agent Consumer RBAC assignment
-> hosted managed-identity Foundry Agent verification
-> hosted fictional-data agent invocation
```

Each arrow is a separate boundary. Code deployment does not provision
infrastructure, alter app settings, assign RBAC, verify startup, or call
Foundry. Hosted defaults remain mock-only with notifications suppressed, and
human nurse review remains mandatory.

`infra/main.bicep` is a minimal resource-group-scope Azure baseline for the
capstone. It provisions:

- Cosmos DB account
- Cosmos SQL database
- `cases` container with partition key `/createdDate`
- Storage account
- Log Analytics workspace
- Application Insights component
- Optional Linux App Service plan and Web App hosting contract

The infrastructure files contain no secrets. The baseline was deployed and
manually tested once, including Cosmos point-read/upsert behavior, and the test
resource group was cleaned up afterward. The newer Web App infrastructure has
compiled and passed offline tests but has not been deployed or authenticated
with its system-assigned identity. The RBAC templates have also compiled and
passed offline tests, but the assignment has not been deployed.

Not demonstrated live:

- Web App deployment
- Application code deployment
- Hosted `/health`, `/version`, or `/demo/status` verification
- Foundry Agent Consumer RBAC deployment
- Managed-identity token acquisition
- Immutable-version verification from the hosted application
- Hosted agent invocation

Deferred infrastructure:

- Live Web App code deployment and execution of hosted readiness verification
- Agent-specific RBAC scope
- Key Vault
- App Service Authentication
- Private networking
- Production monitoring
- Durable background worker infrastructure
- Production clinical security or compliance

## 10. Deferred / Future Architecture

The following are intentionally not implemented in the current MVP:

- Live Hosting infrastructure and application code deployment for the Web App
- Live execution of hosted health/readiness verification
- Live RBAC deployment plus hosted verification and invocation
- Agent-specific RBAC scope
- Authentication / RBAC beyond the offline-tested Consumer assignment
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
