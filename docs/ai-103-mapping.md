# Nurse Intake Assistant AI-103 Mapping

## 1. Current Purpose

The Nurse Intake Assistant is an AI-103 capstone/demo project. The current
implementation is a local mock/demo FastAPI app that demonstrates AI solution
architecture, provider seams, responsible AI boundaries, testable service
design, and Azure integration readiness.

It is not production clinical software. It does not diagnose, prescribe,
dispatch care, or make autonomous medical decisions. AI-generated extraction,
summary, and advisory urgency output requires human nurse review before any
clinical action. AI output requires human nurse review.

The current app runs safely with mock defaults:

```text
APP_MODE=mock
AI_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
```

With those defaults, the demo makes no live Azure calls and sends no real email
or SMS.

## 2. Implemented AI-103-Aligned Capabilities

| AI-103 area | Current implementation | Evidence in repo | Status |
|---|---|---|---|
| Generative AI app design | `CaseProcessingService` orchestrates extraction, urgency merge, persistence, and notifications; AI provider factory selects the configured provider; `MockAiService` returns structured extraction, summary, and advisory classification; Pydantic models define API and output contracts | `src/app/services/case_processing_service.py`, `src/app/services/ai_service_factory.py`, `src/app/services/mock_ai_service.py`, `src/app/models/ai_outputs.py`, `src/app/models/case.py` | Implemented locally with mock AI |
| Azure AI Foundry readiness | `FoundryAiService` and `AI_PROVIDER=foundry` provide a tested provider boundary; settings placeholders capture required Foundry endpoint and deployment name | `src/app/services/foundry_ai_service.py`, `src/app/services/ai_service_factory.py`, `src/app/config/settings.py`, `.env.example`, `tests/test_foundry_ai_service.py`, `tests/test_ai_service_factory.py` | Boundary/scaffold implemented; live Foundry extraction deferred |
| Responsible AI / human oversight | Urgency is advisory only; deterministic red-flag rules supplement AI; red-flag matching is negation-aware; nurse review is persisted; no autonomous clinical decision-making is implemented | `src/app/services/urgency_rules_service.py`, `src/app/config/red_flags.yaml`, `src/app/routes/cases.py`, `tests/test_red_flags.py`, `tests/test_cases_route.py`, `docs/architecture.md` | Implemented safety boundary |
| Natural language processing | Text intake and voicemail transcript intake convert natural language into patient fields, reason, symptoms, summary, missing fields, intake status, and advisory urgency | `src/app/routes/intake.py`, `src/app/services/mock_ai_service.py`, `tests/test_intake_route.py`, `tests/test_mock_ai_service.py` | Implemented for text/transcripts; Azure Speech deferred |
| Azure service integration boundaries | Cosmos repository and container factory, ACS Email/SMS sender boundaries, and Bicep baseline for Cosmos, storage, Log Analytics, and Application Insights | `src/app/services/cosmos_case_repository.py`, `src/app/services/cosmos_container_factory.py`, `src/app/services/email_notification_sender.py`, `src/app/services/sms_notification_sender.py`, `infra/main.bicep`, `infra/README.md` | Boundaries and baseline implemented; production hosting/secret/auth hardening deferred |
| Application architecture | FastAPI routes support intake, case list, filtering, summary, lookup, nurse review, demo seed/reset, notification inspection, health, and static demo/legal pages | `src/app/routes/`, `src/app/main.py`, `src/app/static/demo.html`, `tests/test_cases_route.py`, `tests/test_demo_page_route.py`, `tests/test_demo_reset_route.py`, `tests/test_notifications_route.py` | Implemented local MVP |
| Notification status semantics | Legacy booleans remain backward-compatible while explicit email/SMS status fields distinguish `MockRecorded`, `Accepted`, `Failed`, `Suppressed`, and `NotAttempted`; SMS delivery confirmation remains false until future tracking exists | `src/app/models/case.py`, `src/app/services/case_processing_service.py`, `tests/test_case_processing_service.py`, `docs/architecture.md` | Implemented semantics |
| Testing and reliability | Pytest suite covers provider factories, repositories, routes, red-flag rules, notification behavior, OpenAPI examples, static pages, and documentation guardrails; demo smoke-test guide supports manual validation | `tests/`, `pytest.ini`, `docs/demo-smoke-test.md`, `docs/manual-local-mock-demo.md` | Implemented project discipline |

## 3. Generative AI And Foundry Relevance

The implemented local pipeline mirrors the shape of a production generative AI
application while keeping the demo deterministic:

```text
POST /intake/text or POST /intake/voicemail-transcript
-> CaseProcessingService
-> create_ai_service(settings)
-> MockAiService for AI_PROVIDER=mock
-> structured extraction, summary, and advisory urgency
-> Pydantic CaseDocument
-> rules merge, persistence, notifications, nurse review queue
```

For AI-103 discussion, the important design point is the provider seam:
`MockAiService` supports safe local demonstration today, while
`FoundryAiService` is the boundary where live Azure AI Foundry structured
extraction can be added later. The backend owns side effects such as
persistence, notifications, and review state; the AI provider should only return
structured reasoning output.

Live Azure AI Foundry extraction is not currently implemented.

## 4. Responsible AI And Human Review

The project is deliberately human-in-the-loop:

- Advisory urgency is used for nurse queue prioritization, not diagnosis
- Red-flag rules provide deterministic safety support
- Negation-aware detection reduces false positives for denied symptoms
- Missing intake fields create a case marked `NeedsFollowUp`
- Nurse review changes `reviewStatus` from `PendingReview` to `Reviewed`
- The system does not provide treatment instructions or autonomous medical
  decisions

Interview framing:

```text
The AI helps structure and summarize intake information, but the nurse remains
responsible for clinical judgment and follow-up.
```

## 5. Natural Language And Speech Scope

Implemented natural language inputs:

- `POST /intake/text`
- `POST /intake/voicemail-transcript`

Both routes process existing text. The voicemail route accepts an
already-transcribed voicemail transcript plus optional call, recording, audio
blob, caller phone, and idempotency metadata.

Deferred speech work:

- Azure Speech transcription service
- Audio upload or ACS recording transcription
- Voice intake or call automation workflow
- Audio retention and cleanup workflow

This keeps the current app honest: it demonstrates transcript processing and
the future Speech boundary, not live Azure Speech.

## 6. Azure Integration Readiness

The current codebase includes Azure-ready boundaries without requiring live
Azure services for the local demo:

- Cosmos repository boundary with point reads and upserts
- Cosmos container factory using `/createdDate` partitioning
- Bicep baseline for Cosmos DB, storage account, Log Analytics, and
  Application Insights
- ACS Email sender boundary and completed ACS Email smoke-test documentation
- ACS SMS sender boundary that reaches SDK/send-request path
- Mock providers as the safe local default

Scope boundaries:

- Cosmos cross-partition list/summary queries are deferred
- Application Insights runtime logging/telemetry hardening is deferred
- App Service or Azure Container Apps hosting is deferred
- Key Vault and managed identity are deferred
- App Service Authentication / Entra ID protection is deferred
- Confirmed ACS SMS handset delivery is not implemented and remains pending
  external toll-free verification and future delivery tracking

## 7. Explicitly Deferred AI-103 / Azure Work

The following are future work, not current implementation:

- Live Azure AI Foundry structured extraction
- Azure AI Foundry Agent/tool orchestration, if still useful after the simpler
  Foundry provider path
- Azure Speech transcription service
- App Service or Azure Container Apps hosting
- Key Vault and managed identity
- App Service Authentication / Entra ID protection
- Application Insights runtime logging/telemetry hardening
- ACS phone intake/call automation
- ACS SMS delivery reports/status tracking
- Retry/durable processing
- Production security, compliance, audit, and clinical workflow hardening

## 8. Exam ROI For Future Slices

Highest AI-103 ROI:

- Live Azure AI Foundry structured extraction
- Foundry prompt/schema/evaluation documentation
- Azure Speech transcription boundary
- Responsible AI and human-review documentation

Medium AI-103 ROI:

- Key Vault and managed identity
- App Service or Azure Container Apps hosting
- App Service Authentication / Entra ID route protection
- Application Insights telemetry hardening

Lower direct exam ROI but strong portfolio value:

- ACS phone intake
- Full phone-recording/callback workflow
- Production dashboard polish

## 9. Recommended Azure Implementation Order

1. Live Azure AI Foundry structured extraction
2. Foundry prompt/schema/evaluation notes
3. Azure Speech transcription service boundary
4. Key Vault / managed identity
5. Azure hosting
6. App Service auth/protected routes
7. Application Insights telemetry hardening
8. ACS phone intake
9. Retry/durable processing
10. Advanced Foundry Agent/tool orchestration only if useful

This order prioritizes AI-103 learning value before lower-exam-value telephony
workflow work.

## 10. Scope Honesty Checklist

When presenting the capstone, do not imply that the current MVP already has:

- Live Azure AI Foundry extraction
- Azure Speech transcription
- ACS phone intake
- App Service authentication
- Key Vault
- Confirmed SMS handset delivery
- Production clinical readiness

Accurate portfolio framing:

```text
Built a local mock/demo Nurse Intake Assistant in FastAPI with structured
intake processing, deterministic mock AI extraction and summarization,
advisory urgency classification with red-flag rules, nurse review workflow,
mock notification inspection, and Azure-ready provider boundaries for Foundry,
Cosmos DB, ACS Email/SMS, and infrastructure.
```

Future-facing framing:

```text
The next highest-value Azure slice is to replace the mock AI provider with live
Azure AI Foundry structured extraction while preserving the same Pydantic output
contracts and human-review boundary.
```
