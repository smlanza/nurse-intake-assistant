# Nurse Intake Assistant Progress

Active current-status and resume document. Historical progress through June
2026 is archived at `docs/archive/progress-2026-06.md`.

## Current Status
Latest verified test baseline:
- 856 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

The current MVP is a local mock/demo only Nurse Intake Assistant capstone flow covering intake, mock AI extraction, urgency, nurse review, notifications, and a local demo UI.

Important constraints:
- Local mock/demo only
- No production clinical use
- No live Azure integration in the demo page
- Mock mode sends no real email or SMS
- AI output requires human nurse review
- Do not commit secrets, connection strings, real contact data, credentials, or patient data

Latest completed slice:
- Programmatic prompt-agent provisioning now uses the configured Foundry
  project endpoint, agent name, `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`, and
  centralized `foundry-agent-intake-v1` instructions. It creates a missing
  agent, reuses an identical latest version, or creates one updated immutable
  version when the model/instructions changed. Repeated identical runs do not
  create duplicates.
- Provisioning and invocation are separate: `deploy_foundry_agent.py` never
  creates a Responses client or invokes the agent. Offline `--check` creates no
  client and makes no Azure call; live provisioning requires explicit
  `--live --json` and emits sanitized lifecycle/presence metadata only.
- Live provisioning was not run in this slice, so no new created/reused/updated
  outcome is claimed. The separate invocation smoke was not rerun; the prior
  verified baseline remains `ok=true`, `category=success`,
  `agent_attempted=true`, `agent_output_valid=true`, and
  `fallback_used=false`.
- Automated tests remained offline with injected fake SDK clients. No Bicep
  resources were added or duplicated; `infra/main.bicep`,
  `infra/modules/foundry.bicep`, and `infra/foundry-only.bicep` remain the
  authoritative existing infrastructure.
- Environment-file updates and resource-group cleanup remain manual. All local
  mock defaults, notification behavior, and mandatory human nurse review remain
  unchanged.
- The existing Foundry manual guide now documents the complete separated
  workflow: infrastructure verification, offline provisioning readiness,
  explicit live prompt-agent provisioning, separate live invocation, restoration
  of all providers to mock/offline defaults, and manual disposable-resource
  cleanup. No new live provisioning or invocation validation was performed or
  reviewed for this documentation correction, so no new live success is
  claimed.
- Manual live Foundry Agent smoke passed: `ok=true`, `category=success`, `agent_attempted=true`, `agent_output_valid=true`, `fallback_used=false`; fields included `extraction`, `urgency`, and `handoffNote`.
- No live Azure behavior is claimed for `/demo` by default; `AGENT_PROVIDER=mock` remains the safe local/demo default, and human nurse review remains mandatory.
- Live Foundry-only deployment and read-only verification succeeded: AIServices account, project, and model provisioning were `Succeeded`; endpoint format was valid; Azure returned qualified `<account>/<project>`.
- Verified model metadata: `gpt-5-mini`, version `2025-08-07`, format `OpenAI`, SKU `GlobalStandard`.
- No prompt agent was created, no model inference ran, application behavior did not change, nurse review remains mandatory, and no production clinical claim is made.

## Current Resume Point

Safe to demo today:
- Local text intake and already-transcribed voicemail transcript intake
- Nurse review workflow, recent cases, queue summary, and demo seed/reset
- Copy-friendly nurse handoff note display for selected saved cases
- Mock email/SMS notification inspection
- Local mock demo safety banner, readiness status panel, and human nurse review
  boundary

Authoritative Foundry infrastructure for future TDD slices:
- `infra/main.bicep`: authoritative full application entry point; Foundry remains optional through `deployFoundry=false` by default.
- `infra/modules/foundry.bicep`: single reusable AIServices account/project/model module; do not duplicate these definitions.
- `infra/foundry-only.bicep`: preferred lightweight entry point for disposable daily Foundry validation.
- `infra/foundry-only.example.bicepparam`: committed fictional example; `infra/foundry-only.bicepparam` is ignored, operator-local, and must not be committed.
- `scripts/deploy_foundry_infra.py`: approved deployment boundary; `scripts/verify_foundry_infra.py`: approved read-only verification boundary.

Future-slice rules:
- Future TDD slices requiring Foundry infrastructure must extend or reuse this implementation rather than create another `main.bicep`, duplicate resources, or return to portal-only creation.
- Do not add a parallel subscription-scope Foundry stack unless subscription-scope resources are genuinely required.
- Do not refactor Cosmos, Storage, Log Analytics, or Application Insights merely to add a Foundry feature.
- Keep infrastructure deployment separate from prompt-agent creation; keep prompt-agent creation separate from application startup and intake requests.
- Keep environment-file updates manual unless explicitly and safely introduced by a future TDD slice.
- Keep cleanup manual and explicit; never automatically delete resource groups.

Approved daily Foundry workflow:
```text
edit ignored infra/foundry-only.bicepparam -> compile Bicep parameters -> deploy_foundry_infra.py --check -> create/reuse disposable resource group -> deploy_foundry_infra.py --what-if --json -> deploy_foundry_infra.py --live --json -> verify_foundry_infra.py --json -> optionally run the separate prompt-agent workflow -> manually delete the resource group after review
```

Do not claim as complete:
- Live Azure AI Foundry extraction outside the manual Foundry Agent smoke path
- Live Azure Speech transcription, audio upload, or audio processing
- ACS phone intake/call automation, Key Vault, App Service hosting/auth,
  retry/durable processing, SMS delivery tracking, production frontend, or
  production clinical readiness

Recommended next move: Run the documented manual offline provisioning check,
then explicit live provisioning against the verified disposable Foundry project.
Review the sanitized result, set the resulting version manually, and run the
separate existing fictional-data invocation smoke. Do not redesign or recreate
the infrastructure first.

## Current Working Local Pipeline

```text
POST /intake/text
-> CaseProcessingService
-> Optional NurseIntakeAgent when AGENT_PROVIDER is foundry/foundry-agent
-> create_ai_service(settings)
-> MockAiService for AI_PROVIDER=mock
-> UrgencyRulesService
-> create_case_repository(settings)
-> InMemoryCaseRepository for APP_MODE=mock
-> create_email_notification_sender(settings)
-> MockEmailNotificationSender for EMAIL_PROVIDER=mock unless suppressed
-> create_sms_notification_sender(settings)
-> MockSmsNotificationSender for SMS_PROVIDER=mock unless suppressed
-> CaseDocument response
```

Voicemail transcript intake uses the same processing and notification/status
pipeline through `POST /intake/voicemail-transcript`.

## Available Demo And Read Routes

- Demo: `GET /demo`, `GET /demo/status`, `POST /demo/seed`, `POST /demo/reset`.
- Intake: `POST /intake/text`, `POST /intake/voicemail-transcript`.
- Cases: `GET /cases`, `GET /cases/summary`, `GET /cases/{case_id}`, and
  `GET /cases/{case_id}/handoff-note`, with mock filters, offline-tested Cosmos
  full-filter list/summary parity, and point-read lookup where supported.
- Notifications: `GET /notifications/email`, `GET /notifications/sms`.

Primary demo documentation:
- `README.md`
- `docs/system-overview.md`
- `docs/manual-local-mock-demo.md`
- `docs/demo-smoke-test.md`
- `docs/manual-foundry-smoke-test.md`
- `docs/manual-speech-smoke-test.md`

## App Settings Summary

Safe local defaults:
- `APP_MODE=mock`
- `AI_PROVIDER=mock`
- `EMAIL_PROVIDER=mock`
- `SMS_PROVIDER=mock`
- `DEMO_SUPPRESS_NOTIFICATIONS=false`

Provider settings:
- `APP_MODE=mock` uses `InMemoryCaseRepository`.
- `APP_MODE=cosmos` uses `CosmosCaseRepository` and requires Cosmos settings.
  Basic cross-partition listing supports newest-first ordering plus optional
  all filters across the repository contract. The summary route has the same
  offline-tested filter parity and counts the returned cases in the application.
  Server-side aggregation/pagination, live list/summary/idempotency validation,
  and concurrent exactly-once processing remain deferred.
- `AI_PROVIDER=mock` uses deterministic local mock extraction.
- `AI_PROVIDER=foundry` is a tested provider boundary and requires
  `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` and
  `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`. The offline Foundry structured
  extraction prompt/schema/parser contract and injected fake-client seam are
  implemented. A thin opt-in live adapter matches the same seam with lazy SDK
  imports/client construction, but live extraction is deferred.
- `AGENT_PROVIDER=mock` remains the default. `AGENT_PROVIDER=foundry-agent`
  routes text intake through the `NurseIntakeAgent` boundary when explicitly
  configured. The Foundry Agent client boundary supports injected fakes and
  explicit opt-in live-client creation using
  `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT`,
  `AZURE_AI_FOUNDRY_AGENT_NAME`, and `AZURE_AI_FOUNDRY_AGENT_VERSION`; missing
  settings, SDK support, and response contract failures use sanitized
  diagnostics. `/demo/status` and `scripts/preflight.py --foundry-agent` report
  readiness without calling Azure. The manual smoke script also accepts the
  `AGENT_PROVIDER=foundry` smoke alias while preserving `mock` as the default.
- `SPEECH_PROVIDER=mock` uses an offline transcription boundary for
  already-transcribed text.
- `SPEECH_PROVIDER=azure` wires an Azure Speech scaffold/factory, but live
  Azure Speech transcription and audio processing are deferred.
- Mock email remains the default local mode.
- `EMAIL_PROVIDER=acs` selects ACS Email and requires
  `ACS_EMAIL_CONNECTION_STRING`, `ACS_EMAIL_SENDER_ADDRESS`, and
  `NURSE_NOTIFICATION_EMAIL`.
- `SMS_PROVIDER=mock` records mock SMS notifications in memory.
- `SMS_PROVIDER=acs` selects ACS SMS and requires
  `ACS_SMS_CONNECTION_STRING`, `ACS_SMS_FROM_PHONE_NUMBER`, and
  `NURSE_NOTIFICATION_PHONE_NUMBER`.

`.env.example` keeps mock as the safe local default and includes placeholders
only. Do not commit connection strings, access keys, real phone numbers, real
email addresses, or Azure AI keys.

## Notification Semantics Summary

- `notificationEmailSent` and `notificationSmsSent` remain backward-compatible
  boolean fields.
- `notificationEmailStatus`, `notificationSmsStatus`, and
  `notificationSmsDeliveryConfirmed` provide explicit notification state.
- Status values are `NotAttempted`, `MockRecorded`, `Accepted`, `Failed`, and
  `Suppressed`.
- Mock email and SMS sends set the legacy sent booleans to `true` and report
  `MockRecorded`.
- ACS-style accepted sends set the legacy sent booleans to `true` and report
  `Accepted` without implying final handset delivery.
- SMS provider acceptance always leaves
  `notificationSmsDeliveryConfirmed=false` until a future delivery-status
  slice exists.
- Email and SMS failures set the matching sent boolean to `false`, report
  `Failed`, and still save/return the case.
- `DEMO_SUPPRESS_NOTIFICATIONS=true` sets email and SMS statuses to
  `Suppressed`, leaves sent booleans false, and records no mock notifications.

## Feature Summary

Completed work by feature area:
- Core FastAPI app, health route, Pydantic models, settings, and intake
  processing service
- Text intake validation for empty, whitespace-only, and too-short requests
- Mock AI extraction, AI provider factory, Foundry provider boundary, and
  offline Foundry structured extraction prompt/schema/parser contract with an
  injected fake-client seam and opt-in lazy live adapter
- Offline Speech transcription provider boundary, mock provider, Azure Speech
  scaffold, and speech provider factory
- Deterministic urgency rules with negation-aware red-flag handling
- Structured missing-field validation, intake completion status, and follow-up
  prioritization
- Human-in-the-loop nurse review with persisted review metadata
- Mock repository support plus Cosmos repository/container factory support
- Email/SMS notification provider scaffolding, fake-client tests, ACS Email
  smoke-test documentation, and ACS SMS SDK/send-request boundary
- Notification status semantics and queue summary notification counts
- Mock queue filtering, ordering, summary, and pagination
- Deterministic copy-friendly nurse handoff notes for saved cases
- Demo seed/reset endpoints and local demo UI with handoff note display
- Voicemail transcript intake with optional recording metadata and mock-mode
  idempotency
- Swagger/OpenAPI examples for text and voicemail transcript intake
- Swagger/OpenAPI metadata and safe example for the handoff note route
- README local mock demo walkthrough and manual demo/smoke-test docs
- Minimal Bicep infrastructure baseline and manual Cosmos smoke test
- No Azure calls in tests, PHI, production clinical behavior, hosting/auth/Key
  Vault, phone intake automation, retry/durable processing, or frontend work
  were added in the Foundry Agent response hardening slice.

## Infrastructure Summary

- `infra/main.bicep` is a resource-group-scope MVP baseline.
- It provisions Cosmos DB, a Cosmos SQL database, a `cases` container using
  `/createdDate`, a storage account, Log Analytics, and Application Insights.
- `infra/README.md` documents Azure CLI build, validate, deploy, and cleanup
  commands.
- Manual Cosmos smoke testing verified local `APP_MODE=cosmos` with a deployed
  Cosmos account and a point read via `createdDate`.
- The dev resource group used for manual validation was deleted after testing.
- No secrets are stored in infrastructure files.

## Known Issues And Future Enhancements

- `notificationSmsSent=true` is backward-compatible and should be read with
  `notificationSmsStatus` and `notificationSmsDeliveryConfirmed`.
- Confirmed live ACS SMS handset delivery is pending external toll-free
  verification and carrier/Azure regulatory workflow completion.
- Future enhancement: capture ACS message id/status or delivery report
  semantics for confirmed handset delivery status.
- Cosmos list/summary filter parity is covered offline with fakes and no Azure
  calls. Server-side pagination/aggregation and live list/summary validation
  remain deferred; only the prior point-read smoke used `createdDate`.
- Cosmos voicemail idempotency lookup supports sequential retries offline; live
  validation and atomic concurrent exactly-once guarantees remain deferred.

## Not Yet Implemented / Deferred Scope

- Authentication
- Hosting
- Key Vault
- Azure Speech/voice intake
- live Azure AI Foundry extraction
- ACS SMS delivery tracking
- Retry logic
- Production frontend
- Production clinical UI or autonomous medical decision-making

## Recommended Next Slice

Prefer small manual smoke guides, provider preflight checks, offline tests, and incremental Azure validation while keeping the default demo mock/offline.
Keep ACS phone intake, live Azure Speech processing, hosting, auth, Key Vault, retry/durable processing, and production frontend deferred unless scoped.

## Current Slice Completed

- Idempotent programmatic Foundry prompt-agent provisioning is implemented by
  extending the existing deployment service and CLI.
- The configured endpoint, agent name, model deployment, and centralized
  instruction pack flow through an injected SDK seam. Missing definitions are
  created, exact definitions are reused, and changed definitions create one
  updated immutable version without repeated duplicates.
- Provisioning never invokes the agent. The existing
  `scripts/smoke_foundry_agent.py --live --json` command remains the separate
  manual invocation boundary.
- The latest full suite is 856 passed with 1 existing
  FastAPI/TestClient `StarletteDeprecationWarning`; all automated tests remained
  offline.
- Live provisioning and a new invocation smoke were deferred in this slice, so
  no new Azure success or created/reused/updated outcome is claimed.
- No Bicep resources were duplicated. Ignored environment-file updates and
  resource-group cleanup remain manual. `APP_MODE=mock`, `AI_PROVIDER=mock`,
  `AGENT_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock`, and
  `SPEECH_PROVIDER=mock` remain unchanged, as does mandatory human nurse review.
- Earlier Foundry Agent diagnostics, instruction-pack, readiness/status,
  sanitized smoke-result, and contract-validation slices remain implemented.
- Agent output contract validation added with safe fallback behavior and processing trace warnings.
- Earlier Speech, demo, handoff-note, documentation, and provider-boundary
  milestones are summarized in `docs/archive/progress-2026-06.md` and the
  reference guides below.

## Reference Docs

- `docs/archive/progress-2026-06.md`
- `docs/manual-local-mock-demo.md`
- `docs/demo-smoke-test.md`
- `docs/manual-foundry-smoke-test.md`
- `docs/manual-cosmos-smoke-test.md`
- `docs/manual-acs-email-smoke-test.md`
- `docs/manual-acs-sms-smoke-test.md`
- `docs/architecture.md`
- `docs/ai-103-mapping.md`
- `docs/developer-handoff.md`

Live ACS Email smoke testing is complete and documented in
`docs/manual-acs-email-smoke-test.md`. Live ACS SMS handset delivery remains
deferred until external toll-free verification is complete.

## Workflow

1. Before each Codex task, ChatGPT should recommend the Codex model and
   reasoning level. ChatGPT should recommend the Codex model and reasoning level
   before each slice.
2. Default recommendation:
   - Model: GPT-5.5
   - Reasoning: Medium for normal TDD slices
   - Reasoning: High for cross-cutting architecture, risky integration, or multi-layer refactors
   - Reasoning: Light for docs-only or tiny single-file cleanup
3. Every future TDD slice must include a `docs/progress.md` update as part of
   its acceptance criteria.
4. Run pytest.
5. Run git status.
6. Review output with ChatGPT.
7. Commit and push.
8. Ask ChatGPT for the next Codex prompt.

## Testing Guidance

- Continue using TDD for backend behavior, business rules, provider selection,
  notification semantics, safety boundaries, idempotency, and error handling.
- For docs-only slices, avoid adding many brittle string-matching tests.
- Documentation tests should verify important project guardrails, not exact
  prose everywhere.
- For UI polish slices, test stable workflow controls, section headings, and
  safety/human-review boundaries only when useful.
- Avoid tests that lock in incidental wording, CSS/layout details, or
  formatting.
- Prefer a small number of high-value guardrail tests over many low-value
  documentation tests.
