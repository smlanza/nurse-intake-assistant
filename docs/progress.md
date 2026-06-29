# Nurse Intake Assistant Progress

This is the active current-status and resume document. Detailed historical
progress through June 2026 is archived at
`docs/archive/progress-2026-06.md`.

## Current Status

Latest verified test baseline:
- 364 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

The current MVP is a local mock/demo only Nurse Intake Assistant capstone flow.
It demonstrates intake processing, deterministic mock AI extraction, urgency
classification, nurse queue review, mock notification inspection, and a local
demo UI without requiring live Azure services.

Important constraints:
- Local mock/demo only
- No production clinical use
- No live Azure integration in the demo page
- Mock mode sends no real email or SMS
- AI output requires human nurse review
- Do not commit secrets, connection strings, real phone numbers, real email
  addresses, provider credentials, or real patient data

## Resume Point

The local mock demo console is complete for the current capstone demo flow:
- Seed demo data
- Load recent cases
- Load queue summary
- Select for Review
- Selected Case Context
- Nurse review submit with Recent Cases and Queue Summary auto-refresh
- Text intake
- Voicemail transcript intake
- Mock email/SMS notification inspection
- Demo reset
- Local mock demo safety banner

README and demo walkthrough polish is complete. The active docs now describe
how to run the local mock demo with `uvicorn`, open `/demo`, use safe mock
defaults, follow the core demo workflow, and keep the demo framed as local
mock/demo only with required human nurse review.

## Current Working Local Pipeline

```text
POST /intake/text
-> CaseProcessingService
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

- `GET /demo` serves the local demo page.
- `POST /demo/seed` seeds deterministic mock demo cases and is mock-only.
- `POST /demo/reset` clears mock in-memory cases and mock notification records.
- `POST /intake/text` creates a text intake case.
- `POST /intake/voicemail-transcript` creates a case from already-transcribed
  voicemail text.
- `GET /cases` returns mock/in-memory cases newest-first after filters.
- `GET /cases` supports filters for review status, urgency, dates, intake
  status, source/channel, and notification status, with limit/offset pagination.
- `GET /cases/summary` returns unpaginated dashboard-style counts for the full
  filtered mock queue.
- `GET /cases/{case_id}` returns a saved case in mock/default mode.
- `GET /cases/{case_id}?createdDate=YYYY-MM-DD` supports Cosmos point-read
  lookup when the client knows the case date.
- `GET /notifications/email` returns recorded mock email notifications.
- `GET /notifications/sms` returns recorded mock SMS notifications.

Primary demo documentation:
- `README.md`
- `docs/manual-local-mock-demo.md`
- `docs/demo-smoke-test.md`

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
  `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`, but live extraction is deferred.
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
  deterministic urgency rules with negation-aware red-flag handling
- Structured missing-field validation, intake completion status, and follow-up
  prioritization
- Human-in-the-loop nurse review with persisted review metadata
- Mock repository support plus Cosmos repository/container factory support
- Email/SMS notification provider scaffolding, fake-client tests, ACS Email
  smoke-test documentation, and ACS SMS SDK/send-request boundary
- Notification status semantics and queue summary notification counts
- Mock queue filtering, ordering, summary, and pagination
- Demo seed/reset endpoints and local demo UI
- Voicemail transcript intake with optional recording metadata and mock-mode
  idempotency
- Swagger/OpenAPI examples for text and voicemail transcript intake
- README local mock demo walkthrough and manual demo/smoke-test docs
- Minimal Bicep infrastructure baseline and manual Cosmos smoke test

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
- Live Azure AI Foundry extraction
- ACS SMS delivery tracking
- Retry logic
- Production frontend
- Production clinical UI or autonomous medical decision-making

## Recommended Next Slice

Recommended next slice:
- Manual smoke-test pass and screenshot cleanup

Other good follow-up slices:
- Architecture documentation refresh
- AI-103 mapping refresh
- Optional favicon/static polish

Do not start live ACS SMS sending, hosting, Key Vault, live Azure AI Foundry
extraction integration, Azure Speech/voice intake, retry logic, authentication,
or a frontend framework in the next slice unless the project scope explicitly
changes.

## Current Slice Completed

- Progress documentation compaction/archive split is complete.
- Detailed historical progress was moved to
  `docs/archive/progress-2026-06.md`.
- Active `docs/progress.md` now serves as a concise current-status/resume point.
- Documentation guardrail tests verify the archive link and required
  current-status content.
- No backend behavior, API contract, notification semantics, live Azure calls,
  hosting, auth, Key Vault, Azure Speech, live Azure AI Foundry, ACS delivery
  tracking, retry logic, or frontend framework was added.

## Reference Docs

- `docs/archive/progress-2026-06.md`
- `docs/manual-local-mock-demo.md`
- `docs/demo-smoke-test.md`
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
