# Nurse Intake Assistant Progress

Active current-status and resume document. Historical progress through June
2026 is archived at `docs/archive/progress-2026-06.md`.

## Current Status
Latest verified test baseline:
- 723 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

The current MVP is a local mock/demo only Nurse Intake Assistant capstone flow
covering intake processing, deterministic mock AI extraction, urgency
classification, nurse review, mock notification inspection, and a local demo UI.

Important constraints:
- Local mock/demo only
- No production clinical use
- No live Azure integration in the demo page
- Mock mode sends no real email or SMS
- AI output requires human nurse review
- Do not commit secrets, connection strings, real phone numbers, real email
  addresses, provider credentials, or real patient data

Latest completed slice:
- Foundry Agent environment readiness helper/check hardening completed.
- `scripts/smoke_foundry_agent.py --check` now prints a sanitized readiness
  summary with provider, check mode, present/missing required setting names,
  optional setting names when applicable, SDK visibility, a static
  `--live --json` command hint, and a safe recommended next step.
- Check mode remains offline and does not create Azure clients, invoke agents,
  or call Azure.
- Automated tests remain offline and deterministic.
- No live Azure success is claimed unless the manual `--live --json` path is
  actually verified in the intended Azure environment.
- `AGENT_PROVIDER=mock` remains the safe default and default mock behavior is
  unchanged.
- No secrets, raw Azure values, endpoint values, agent IDs, deployment names,
  tokens, raw prompts, raw model output, connection strings, real contact data,
  or real patient data are exposed by the check output, smoke JSON output, or
  docs.
- No hosting, auth, Key Vault, Speech, phone intake, durable retry, production
  frontend, or production clinical behavior was added.

## Current Resume Point

Safe to demo today:
- Local text intake and already-transcribed voicemail transcript intake
- Nurse review workflow, recent cases, queue summary, and demo seed/reset
- Copy-friendly nurse handoff note display for selected saved cases
- Mock email/SMS notification inspection
- Local mock demo safety banner, readiness status panel, and human nurse review
  boundary

Implemented but not live-confirmed:
- Cosmos repository boundary and manual Cosmos point-read path
- ACS Email/SMS boundaries, ACS Email smoke testing, offline-safe ACS
  Email/SMS `--check` preflights, and consolidated `scripts/preflight.py --all`
  with Foundry Agent readiness are complete; ACS SMS handset delivery tracking
  is deferred
- Foundry provider boundary, structured extraction contract, fake-client seam,
  lazy live adapter, manual smoke guide, smoke CLI, and `--check` mode
- Foundry Agent client boundary, fake-client seam, lazy live adapter scaffold,
  explicit `AGENT_PROVIDER=foundry-agent` text-intake routing, and manual
  `scripts/smoke_foundry_agent.py` `--check`/`--live` smoke CLI with env-file
  isolation, fictional data only, safe diagnostics, strict response parsing,
  sanitized `--live --json` success/failure results for manual Azure
  validation, and no notification effects
- Speech transcription provider boundary with mock provider and Azure scaffold

Do not claim as complete:
- Live Azure AI Foundry smoke testing or live Foundry extraction
- Live Azure Speech transcription, audio upload, or audio processing
- ACS phone intake/call automation, Key Vault, App Service hosting/auth,
  retry/durable processing, SMS delivery tracking, production frontend, or
  production clinical readiness

Recommended next move:
- With Azure credentials/model deployment, use `docs/manual-foundry-smoke-test.md`.
- If staying offline, prefer docs, smoke guides, or provider preflight checks
  while keeping the default demo mock/offline.

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
  `GET /cases/{case_id}/handoff-note`, with filters and Cosmos point-read
  lookup where already supported.
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
  `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT` or
  `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`, plus `AZURE_AI_FOUNDRY_AGENT_ID`; missing
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
- Cosmos cross-partition list/summary/query filtering remains a future
  enhancement; current Cosmos support is strongest for point reads by
  `createdDate`.
- Cosmos cross-partition voicemail idempotency lookup remains a future
  enhancement.

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

- Foundry Agent environment readiness helper/check hardening completed.
- The new check helper builds a sanitized offline readiness summary using fake
  settings in tests and never creates a Foundry Agent client.
- Check mode remains offline and does not create Azure clients, invoke agents,
  or call Azure.
- Automated tests remain offline and deterministic.
- No live Azure success is claimed unless manually verified.
- Default mock behavior is unchanged.
- No secrets or raw Azure values are exposed.
- No hosting/auth/Key Vault/Speech/phone/retry/frontend/clinical production
  scope was added.
- Foundry Agent live validation hardening slice completed.
- The manual `--live --json` smoke result uses safe fields only: `ok`, `mode`,
  `provider`, `category`, `message`, `agent_attempted`, `agent_output_valid`,
  `fallback_used`, `fields_present`, and `recommended_next_step`.
- The JSON path distinguishes `success`, `missing_configuration`,
  `sdk_unavailable`, `authentication_or_authorization_failed`,
  `azure_request_failed`, `response_parse_failed`, `contract_invalid`, and
  `unexpected_error`.
- Automated tests remain offline and deterministic, with fake clients/settings
  only; no live Azure calls were added to tests.
- No live Azure success is claimed unless actually manually verified.
- Default `AGENT_PROVIDER=mock` behavior is unchanged.
- No secrets or raw Azure values are exposed in API responses, logs, progress
  docs, or smoke JSON output.
- No hosting/auth/Key Vault/Speech/phone/retry/frontend/clinical production
  scope was added.
- Foundry Agent live smoke result contract slice is complete.
- `scripts/smoke_foundry_agent.py --live --json` now returns sanitized
  structured success/failure results for manual Azure validation, including
  distinct `response_parse_failed` and `contract_invalid` categories.
- Foundry Agent readiness/status command-hint slice is complete.
- `/demo/status` and `scripts/preflight.py --foundry-agent` now point operators
  to the sanitized manual `--live --json` smoke command without creating Azure
  clients, invoking an agent, or calling Azure.
- Ops/readiness command-hint slice is complete.
- `/ops` now displays the same static Foundry Agent manual validation command
  when Foundry Agent mode is selected, and remains configuration-only.
- Automated tests use fake agents/settings/failures only and remain offline; no
  live Azure calls were added to tests.
- `AGENT_PROVIDER=mock` and all other mock/local defaults remain unchanged.
- No notification behavior, hosting/auth/Key Vault, Speech, phone intake,
  retry/durable processing, production frontend, or production clinical
  behavior was added.
- Agent output contract validation added with safe fallback behavior and processing trace warnings.
- Recent completed milestones include demo readiness checklist docs, Azure
  OpenAI/Foundry diagnostics, Speech and Foundry env-file smoke isolation,
  Foundry live smoke safe diagnostics, Foundry manual smoke hardening, handoff
  note OpenAPI/demo display, nurse handoff note route/formatter, and system
  overview documentation.
- Detailed earlier slice notes are archived in
  `docs/archive/progress-2026-06.md` or covered by the reference docs below.
- Azure Speech smoke-test guide / CLI preflight scaffold slice is complete.
- `docs/manual-speech-smoke-test.md` documents prerequisites, safe placeholder
  settings, `--check` usage, preflight meaning, non-goals, rollback to
  `SPEECH_PROVIDER=mock`, and fictional-data-only safety notes.
- `python scripts/smoke_speech_transcription.py --check` validates
  `SPEECH_PROVIDER=azure`, `AZURE_SPEECH_ENDPOINT`, and `AZURE_SPEECH_REGION`
  without creating a Speech client, processing audio, or making Azure calls.
- Optional Azure Speech SDK package visibility is reported gracefully and is not
  required for normal local tests.
- Automated tests remain offline and deterministic.
- No live Azure Speech transcription, audio upload endpoint, phone intake, API
  contract changes, notification semantic changes, hosting, auth, Key Vault,
  retry logic, or frontend framework was added for the Speech smoke-test
  preflight slice.
- Earlier completed slice details are archived in
  `docs/archive/progress-2026-06.md`.
- Recent completed milestones include:
  - Azure Speech transcription provider boundary
  - Foundry structured extraction contract, fake-client seam, lazy live adapter,
    manual smoke guide, smoke CLI, and preflight/check mode
  - AI-103 mapping refresh
  - Architecture documentation refresh
  - Progress workflow testing guidance
  - Manual local mock demo cleanup
  - Progress documentation compaction/archive split
- These earlier slices preserved the same safety boundary: no production
  clinical use, no live Azure claims unless manually verified, no API contract
  changes unless explicitly scoped, and no hosting/auth/Key Vault/phone intake
  expansion.

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
