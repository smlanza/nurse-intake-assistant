# Nurse Intake Assistant Progress

Active current-status and resume document. Historical progress through June
2026 is archived at `docs/archive/progress-2026-06.md`.

## Current Status
Latest verified test baseline:
- 940 passed
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
- Added optional `--verify-agent-version` gating to the existing
  `scripts/smoke_foundry_agent_intake.py` application smoke. In explicit live
  mode it reuses `FoundryAgentVerification` and the shared verification request
  builder before constructing the lazy application agent or entering the
  application intake pipeline.
- Exact immutable name/version response contract, configured model deployment,
  and centralized `foundry-agent-intake-v1` instruction drift now stop the
  application smoke before any Responses client, model invocation, intake,
  persistence, or notification work. Missing versions, authorization failures,
  Azure lookup failures, SDK unavailability, and malformed verification results
  retain sanitized verification-stage categories rather than being mislabeled
  as invocation failures.
- Gated check mode validates the additional model setting and existing SDK
  readiness seam while reporting verification required, SDK visibility, zero
  Azure lookup, zero invocation, zero application intake, and unchanged state.
  The legacy check/live JSON remains unchanged when the option is absent; gated
  output adds a nested verification section plus explicit stage, safe-field,
  notification, fallback, and state-restoration facts.
- Gated verification metadata is tri-state where the orchestrator cannot know
  whether an SDK lookup occurred or a definition matched. Application paths
  report temporary-state restoration from an observed pre/post comparison of
  route globals, dependency overrides, the application repository, and
  notification stores. Safe expected-field names are derived independently;
  no field values or state contents are emitted.
- Offline automated coverage uses injected fakes and made no Azure calls. The
  precise verified baseline is 940 passed with the one existing
  FastAPI/TestClient `StarletteDeprecationWarning`. The enhanced command was run
  only with `--check`; no live Azure verification, provisioning, direct agent
  invocation, or application-level smoke was run in this slice.
- `AGENT_PROVIDER=mock` and all other mock defaults remain unchanged. Immutable
  verification and application invocation remain separate, explicit manual
  operations; the optional gate only orchestrates them for the manual
  application smoke. Mandatory nurse review, notification suppression, manual
  settings restoration/resource cleanup, and the no-production-clinical-use
  posture remain unchanged.
- Historical direct-agent evidence only: Manual live Foundry Agent smoke passed
  in an earlier slice with `ok=true`, `category=success`,
  `agent_attempted=true`, `agent_output_valid=true`, `fallback_used=false`, and
  fields `extraction`, `urgency`, and `handoffNote`. This is not evidence that
  the new guarded application-level live smoke passed; no live command was run
  for the current slice.
- No live Azure behavior is claimed for `/demo` by default; `AGENT_PROVIDER=mock` remains the safe local/demo default, and human nurse review remains mandatory.

## Current Resume Point

Safe to demo today:
- The default demo mock/offline posture remains the safe starting point
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

Recommended next move: Run the documented standalone read-only immutable-version
verification, then run the explicit guarded application-level live smoke
against the disposable verified Foundry project. Review the sanitized result
before selecting the next Azure hosting or operational-integration slice.

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

Prioritize concrete Azure AI Foundry and Agents implementation over additional
local-only polish. The next practical slices should move toward manual
validation of the application-level Foundry Agent intake smoke, stronger use of
the provisioned prompt agent, real Azure-hosted Agent invocation through the
application pipeline, Foundry project/agent lifecycle validation, and the Azure
deployment and operational integration required for the capstone. Replace
remaining mock-only AI boundaries where safe and appropriate.

Continue in small RED-to-GREEN slices with offline automated tests, sanitized
diagnostics, fictional data, explicit manual opt-in for live Azure operations,
mandatory nurse review, and no production clinical-readiness claim. Avoid
low-value frontend polish, unrelated local abstractions, or peripheral features
when a practical Foundry or Agents capability slice is available. Keep ACS
phone intake, Speech, auth, Key Vault, retry/durable processing, and production
frontend deferred unless explicitly scoped.

## Current Slice Completed

- The application-level Foundry Agent intake smoke now accepts the optional
  `--verify-agent-version` gate and reuses the standalone immutable-version
  service before any application or invocation client is created.
- Gated offline `--check` validates setting names and SDK visibility while
  making no Azure lookup, client, invocation, intake, case, notification, or
  application-state change. Gated explicit `--live --json` proceeds into the
  existing fixed-fictional-data application pipeline only after the exact
  immutable name/version, model, and centralized instructions match.
- Verification failure categories remain distinct from later invocation/output
  categories. Definition drift, a missing version, authorization or Azure
  request failure, SDK unavailability, and malformed verifier output all stop
  before invocation and emit only sanitized static guidance.
- Lookup, match, and SDK metadata use tri-state values when verification facts
  are unknown. State-restoration output is based on captured pre/post
  application evidence, and expected safe fields are reported independently.
- Application-level intake readiness remains available through its dedicated
  JSON command and the legacy-formatted consolidated `--all` preflight.
- The explicit fixed-fictional-data live smoke retains its exact sanitized JSON
  contract when the gate is absent. Gated output adds compatible verification
  and stage metadata while retaining classifications, safe fallback,
  `PendingReview`, suppressed notifications, and restoration of temporary
  in-process application state on every exit path.
- Idempotent prompt-agent provisioning still creates, reuses, or updates an
  immutable version without invoking it; direct agent and application-level
  invocation remain separate explicit manual operations.
- The latest full suite is 940 passed with 1 existing
  FastAPI/TestClient `StarletteDeprecationWarning`; all automated tests remained
  offline.
- No live Azure command was run; only the enhanced offline/check command was
  exercised. Mock provider defaults, separate explicit manual verification and
  invocation boundaries, manual environment/resource cleanup, mandatory nurse
  review, and no-production-use constraints remain unchanged.
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
