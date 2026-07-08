# System Overview

## Purpose

The Nurse Intake Assistant is a local mock/demo capstone project for Azure
AI-103 preparation. It demonstrates intake processing, mock AI extraction,
urgency classification, nurse review, notification inspection, and provider
boundaries for future Azure integrations.

This is not production clinical software and has no production clinical use.
AI output is advisory only and requires human nurse review.

## Current Working MVP

- Text intake through `POST /intake/text`
- Already-transcribed voicemail intake through
  `POST /intake/voicemail-transcript`
- Mock AI extraction and summarization
- Deterministic urgency rules
- In-memory repository in mock mode
- Mock email/SMS notification records
- Nurse review queue, copy-friendly handoff note route/display, Swagger
  documentation, read routes, and local demo UI

## Main Local Flow

```text
POST /intake/text or POST /intake/voicemail-transcript
-> CaseProcessingService
-> Optional NurseIntakeAgent for explicit non-mock AGENT_PROVIDER
-> AI provider when no agent is configured
-> UrgencyRulesService
-> Case repository
-> Notification senders
-> CaseDocument response
-> Nurse review / queue / demo inspection
```

## Provider Boundaries

- `APP_MODE=mock` uses the in-memory repository for local demos. `APP_MODE=cosmos`
  selects the Cosmos repository boundary; manual Cosmos point-read smoke testing
  was previously verified, while broader cross-partition list/summary behavior
  remains future work.
- `AI_PROVIDER=mock` uses deterministic local extraction. `AI_PROVIDER=foundry`
  selects the Foundry provider boundary, offline contract tests, fake-client
  seam, lazy live adapter, manual guide, and smoke CLI; live Foundry extraction
  has not been completed.
- `AGENT_PROVIDER=mock` remains the default and does not attempt Foundry Agent
  execution. `AGENT_PROVIDER=foundry-agent` explicitly routes intake through
  the `NurseIntakeAgent` boundary where already supported, with contract
  validation and safe fallback behavior.
- `SPEECH_PROVIDER=mock` supports already-transcribed text through an offline
  boundary. `SPEECH_PROVIDER=azure` wires the Azure Speech scaffold and
  preflight guide/CLI; live audio transcription, upload, and processing are
  deferred.
- `EMAIL_PROVIDER=mock` records local mock email notifications. `EMAIL_PROVIDER=acs`
  selects the ACS Email boundary; live ACS Email smoke testing is complete, but
  secrets must remain local and uncommitted.
- `SMS_PROVIDER=mock` records local mock SMS notifications. `SMS_PROVIDER=acs`
  selects the ACS SMS SDK/send-request boundary; final handset delivery is not
  live-confirmed and delivery tracking is deferred.
- `scripts/preflight.py --all` runs consolidated offline-safe readiness checks
  for Foundry, Speech, ACS Email, and ACS SMS without live calls or sends.

## Processing Trace Observability

Saved and returned cases include `processing_trace` for diagnostic visibility
into the local processing path. For the optional `NurseIntakeAgent` path, the
trace records only safe structured values: `agent_attempted`, `agent_provider`,
`agent_mode`, `agent_output_valid`, `agent_fallback_used`, and
`agent_fallback_reason`. Safe fallback reasons include
`invalid_agent_output` and `agent_execution_failed`.

The trace is diagnostic only. It does not expose raw prompts, raw model
responses, endpoint URLs, deployment names, credentials, stack traces,
exception messages, PHI, or secrets. It also does not imply production
clinical readiness or live Azure validation. Deterministic red-flag rules
remain active after agent processing, and `final_urgency_source` remains
`rules` when rules promote urgency.

## Mock vs Azure-Ready vs Deferred

| Area | Current status | Notes |
| --- | --- | --- |
| Text intake | Working in local mock mode | `POST /intake/text` creates cases from text |
| Voicemail transcript intake | Working in local mock mode | Accepts already-transcribed text only |
| Nurse review | Working in local mock mode | Review queue, case detail, and review metadata are implemented |
| Mock notifications | Working in local mock mode | Email/SMS records are inspectable without live sends |
| NurseIntakeAgent trace | Working in local mock/offline tests | Diagnostic-only safe trace; no live Azure validation claim |
| Cosmos | Azure-ready boundary with prior manual point-read smoke | Cross-partition list/summary work remains future |
| ACS Email | Boundary implemented; live smoke complete | Keep credentials local and uncommitted |
| ACS SMS | Boundary implemented; not final-delivery confirmed | Toll-free/regulatory workflow and delivery tracking remain deferred |
| Azure AI Foundry | Boundary, contract, fake-client seam, lazy adapter, guide, and CLI exist | Live Foundry extraction is deferred |
| Azure Speech | Mock boundary, Azure scaffold, guide, and preflight CLI exist | Live transcription/audio processing is deferred |
| Hosting/Auth/Key Vault | Deferred | No App Service hosting, auth/RBAC, or Key Vault integration |
| Phone intake | Deferred | No ACS phone/call automation |
| Retry/durable processing | Deferred | No durable queue/retry workflow |

## Documentation Map

- `README.md`: quick local demo setup and safety boundaries.
- `docs/progress.md`: current source of truth for status, scope, and next work.
- `docs/architecture.md`: architecture, provider boundaries, and deferred scope.
- `docs/developer-handoff.md`: broader project handoff and original direction.
- `docs/ai-103-mapping.md`: AI-103 capability mapping and Azure readiness.
- `docs/manual-local-mock-demo.md`: API-level local mock demo walkthrough.
- `docs/demo-smoke-test.md`: browser demo smoke checklist.
- `docs/manual-foundry-smoke-test.md`: manual Foundry smoke-test checklist.
- `docs/manual-cosmos-smoke-test.md`: manual Cosmos smoke-test notes.
- `docs/manual-acs-email-smoke-test.md`: completed ACS Email smoke-test guide.
- `docs/manual-acs-sms-smoke-test.md`: ACS SMS smoke-test placeholder/status.
- `scripts/preflight.py --all`: consolidated offline-safe provider preflight.
- `docs/archive/progress-2026-06.md`: detailed historical progress archive.

## Demo Claims

Safe to claim/demo:

- Local text intake and already-transcribed voicemail transcript intake
- Mock AI extraction, urgency classification, and human nurse review
- Recent cases, queue summary, demo seed/reset, and local demo UI
- Copy-friendly nurse handoff notes for saved cases in the demo page
- Mock email/SMS notification inspection
- Local mock/offline safety boundary and no production clinical use

Implemented boundary but not live-confirmed:

- Cosmos repository boundary beyond the previously verified point-read path
- ACS SMS final handset delivery and delivery tracking
- Azure AI Foundry provider boundary and live adapter
- Azure Speech provider boundary and preflight scaffold

Do not claim complete:

- Live Azure AI Foundry smoke testing or live Foundry extraction
- Live Azure Speech transcription, audio upload, or audio processing
- ACS phone intake/call automation
- Key Vault, App Service hosting/auth, or production deployment
- Retry/durable processing, SMS delivery tracking, production frontend, or
  production clinical readiness

## Next-Slice Guidance

Future slices should stay small and prefer manual smoke guides, provider
preflight checks, offline deterministic tests, and incremental Azure validation.

Keep ACS phone intake, live Azure Speech audio processing, hosting, auth, Key
Vault, retry/durable processing, production frontend, and production clinical
readiness deferred unless the project scope explicitly changes.

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
