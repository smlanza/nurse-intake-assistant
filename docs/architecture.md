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
| `FoundryAiService` | Azure AI Foundry provider boundary/scaffold; live extraction is deferred |
| `UrgencyRulesService` | Deterministic red-flag rules with negation-aware matching |
| `create_case_repository(settings)` | Selects in-memory mock repository or Cosmos repository |
| `InMemoryCaseRepository` | Default mock persistence for local demo, filtering, summary, idempotency, and reset |
| `CosmosCaseRepository` | Cosmos point-read/upsert support with container factory wiring |
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
voicemail route expects a transcript that already exists; Azure Speech and live
voice intake are not implemented in this MVP.

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

The service also evaluates local red-flag rules from
`src/app/config/red_flags.yaml`. Rule detection is deterministic and includes
negation-aware handling so phrases such as denying a red-flag symptom do not
count as a positive match.

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
- `GET /cases/{case_id}?createdDate=YYYY-MM-DD` supports point-read lookup when
  the client knows the partition key

Deferred Cosmos behavior:

- Cross-partition list queries
- Cross-partition queue summary queries
- Cross-partition idempotency lookup for voicemail transcripts
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

`infra/main.bicep` is a minimal resource-group-scope Azure baseline for the
capstone. It provisions:

- Cosmos DB account
- Cosmos SQL database
- `cases` container with partition key `/createdDate`
- Storage account
- Log Analytics workspace
- Application Insights component

The infrastructure files contain no secrets. The baseline was deployed and
manually tested once, including Cosmos point-read/upsert behavior, and the test
resource group was cleaned up afterward.

Deferred infrastructure:

- Hosting the FastAPI app
- Key Vault
- Managed identity wiring
- Authentication and RBAC
- Production monitoring/alerting dashboards
- Durable background worker infrastructure

## 10. Deferred / Future Architecture

The following are intentionally not implemented in the current MVP:

- Hosting
- Authentication / RBAC
- Key Vault
- Azure Speech / voice intake
- Live Azure AI Foundry extraction
- ACS SMS delivery reports/status tracking
- Retry logic
- Production frontend
- Production clinical workflow, audit, compliance, and security hardening
- Cosmos cross-partition query support
- Durable queues or background worker processing
- Autonomous medical decision-making

These items should remain clearly separate from the implemented local mock MVP
unless the project scope explicitly changes.

## 11. AI-103 Alignment

This architecture demonstrates AI-103-relevant concepts without overstating the
implementation:

- Azure AI Foundry provider boundary through `FoundryAiService` and
  `create_ai_service(settings)`
- Natural language extraction, summarization, and advisory classification
  concept through the deterministic mock provider
- Responsible AI boundary through explicit human nurse review and no autonomous
  clinical action
- Azure service integration boundaries for Cosmos DB, ACS Email, ACS SMS,
  storage, Application Insights, and Log Analytics
- Infrastructure-as-code baseline through Bicep
- Monitoring baseline concepts through Application Insights and Log Analytics

Live Azure AI Foundry extraction, Azure Speech transcription, production
hosting, authentication, Key Vault, and SMS delivery tracking remain deferred.
