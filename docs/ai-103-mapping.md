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
| Azure AI Foundry / agent orchestration readiness | `FoundryAiService` and `NurseIntakeAgent` provide tested runtime boundaries and application-owned structured contracts, including validation before trusting model/agent output; stable per-agent OpenAI protocol invocation is primary, project-endpoint agent-reference invocation is explicit compatibility-only, and read-only verification checks `agent_endpoint.protocols`, exclusive immutable-version routing, and the configured definition | `src/app/services/foundry_agent_client.py`, `src/app/services/foundry_agent_verification.py`, `scripts/verify_foundry_agent.py`, `tests/test_foundry_agent_verification.py` | Offline tests use fakes and make no Azure calls; live verification/invocation remains explicit, sanitized, and fictional-data-only |
| Responsible AI / human oversight | Responsible AI pattern: urgency is advisory only; invalid agent output uses safe fallback values instead of crashing intake processing; deterministic red-flag rules supplement AI and may promote final urgency; red-flag matching is negation-aware; nurse review is persisted; no autonomous clinical decision-making is implemented | `src/app/services/urgency_rules_service.py`, `src/app/services/nurse_intake_agent_contract.py`, `src/app/config/red_flags.yaml`, `src/app/routes/cases.py`, `tests/test_red_flags.py`, `tests/test_case_processing_service.py`, `docs/architecture.md` | Implemented human review and deterministic safety rules |
| Natural language processing and Speech readiness | Text intake and voicemail transcript intake convert natural language into patient fields, reason, symptoms, summary, missing fields, intake status, and advisory urgency; Speech transcription provider boundary has mock/offline and Azure scaffold implementations | `src/app/routes/intake.py`, `src/app/services/mock_ai_service.py`, `src/app/services/speech_transcription_service.py`, `src/app/services/speech_transcription_factory.py`, `tests/test_intake_route.py`, `tests/test_mock_ai_service.py`, `tests/test_speech_transcription_service.py`, `tests/test_speech_transcription_factory.py` | Implemented for text/transcripts and offline Speech boundary; live Azure Speech deferred |
| Azure service integration boundaries | Cosmos repository and container factory with point reads/upserts plus cross-partition filtered case-list queries; ACS Email/SMS boundaries; Bicep baseline for Cosmos, storage, Log Analytics, Application Insights, and optional Azure Web App hosting | `src/app/services/cosmos_case_repository.py`, `src/app/services/cosmos_container_factory.py`, `src/app/services/email_notification_sender.py`, `src/app/services/sms_notification_sender.py`, `infra/main.bicep`, `infra/modules/web-app.bicep`, `infra/README.md` | Case-list/query-filter parity is covered offline with fakes; queue-summary and voicemail-idempotency lookup parity, live Cosmos validation, and production hardening are deferred |
| Application architecture | FastAPI routes support intake, case list, filtering, summary, lookup, nurse review, demo seed/reset, notification inspection, health, and static demo/legal pages | `src/app/routes/`, `src/app/main.py`, `src/app/static/demo.html`, `tests/test_cases_route.py`, `tests/test_demo_page_route.py`, `tests/test_demo_reset_route.py`, `tests/test_notifications_route.py` | Implemented local MVP |
| Notification status semantics | Legacy booleans remain backward-compatible while explicit email/SMS status fields distinguish `MockRecorded`, `Accepted`, `Failed`, `Suppressed`, and `NotAttempted`; SMS delivery confirmation remains false until future tracking exists | `src/app/models/case.py`, `src/app/services/case_processing_service.py`, `tests/test_case_processing_service.py`, `docs/architecture.md` | Implemented semantics |
| Testing and reliability | Pytest suite covers provider factories, repositories, routes, red-flag rules, notification behavior, OpenAPI examples, static pages, and documentation guardrails; demo smoke-test guide supports manual validation | `tests/`, `pytest.ini`, `docs/demo-smoke-test.md`, `docs/manual-local-mock-demo.md` | Implemented project discipline |
| Reusable Foundry infrastructure | One Bicep module defines an Entra-oriented AIServices account, child project, and explicitly parameterized model; full-stack and disposable entry points reuse it; a read-only verifier accepts Azure's qualified `<account>/<project>` child-resource name | `infra/modules/foundry.bicep`, `infra/main.bicep`, `infra/foundry-only.bicep`, `scripts/deploy_foundry_infra.py`, `scripts/verify_foundry_infra.py` | Live Foundry-only deployment plus account, project, endpoint-format, and model verification succeeded; no agent, inference, runtime change, or production clinical claim |
| Managed-identity and RBAC readiness | Optional IaC defines a Linux Azure Web App with a system-assigned managed identity; a separate explicit template derives that identity and grants only Foundry Agent Consumer at the Foundry project scope | `infra/modules/web-app.bicep`, `infra/foundry-agent-consumer-rbac.bicep`, `infra/modules/foundry-agent-consumer-rbac.bicep`, `tests/test_foundry_agent_consumer_rbac_bicep.py` | Implemented and compiled offline only; no RBAC deployment, managed-identity authentication, hosted verification, or invocation has occurred; human nurse review, safe fallback, mock defaults, and suppressed notifications remain unchanged |
| Repeatable application deployment readiness | An allowlist-driven service creates deterministic Azure Web App source ZIPs containing `requirements.txt`; the optional Web App declares its remote-build setting; a separate CLI can submit only an explicit code-deployment request; and a read-only verifier checks `/health`, `/version`, and `/demo/status` on an explicitly supplied HTTPS origin | `infra/modules/web-app.bicep`, `src/app/services/web_app_package.py`, `src/app/services/web_app_readiness_verification.py`, `scripts/deploy_web_app_code.py`, `scripts/verify_web_app_readiness.py`, `tests/test_web_app_package.py`, `tests/test_web_app_readiness_verification.py`, `tests/test_verify_web_app_readiness_script.py` | Build configuration, packaging, deployment-command behavior, and hosted-readiness verification are implemented and offline-tested only. Check mode makes no HTTP request; live mode is explicit and read-only. No live infrastructure deployment, code deployment, hosted request, RBAC, managed-identity authentication, Foundry verification, or agent invocation has occurred; no production-readiness claim is made |

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
extraction can be added later. The offline Foundry contract already defines the
prompt guardrails, expected JSON shape, parser validation, and mapping into the
current extraction and urgency output models. The service can exercise that
contract through an injected fake client in offline tests, and a lazy live
adapter now matches the same seam for a future manual SDK smoke test. The
backend owns side effects such as persistence, notifications, and review state;
the AI provider should only return structured reasoning output.

The agent path follows the same responsible AI pattern: `NurseIntakeAgent` is
an external reasoning boundary, and agent contract validation runs before the
app trusts model/agent output. Valid output can provide summary and urgency
classification. Invalid output uses a safe fallback for nurse review, while
deterministic red-flag rules still evaluate the raw intake text and may promote
final urgency. The processing trace records agent usage, warnings, and final urgency source for audit-friendly review.

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
blob, caller phone, and idempotency metadata. A Speech transcription provider
boundary now exists with an offline mock provider and Azure Speech scaffold, but
the route remains text-only.

Deferred speech work:

- Live Azure Speech transcription service
- Audio upload or ACS recording transcription
- Voice intake or call automation workflow
- Audio retention and cleanup workflow

This keeps the current app honest: it demonstrates transcript processing and an
offline Speech provider boundary, not live Azure Speech.

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

- Cosmos queue-summary and voicemail-idempotency lookup parity are deferred
- Cosmos live list-query validation, pagination, and aggregation tuning are deferred
- Application Insights runtime logging/telemetry hardening is deferred
- Web App infrastructure, its remote-build setting, deterministic packaging,
  explicit code-deployment request, and read-only hosted-readiness verifier are
  represented and offline-tested; live deployment and verifier execution are
  deferred
- System-assigned identity and project-scoped Foundry Agent Consumer RBAC are represented in separate IaC boundaries
- RBAC deployment, live authorization, and managed-identity invocation are deferred
- Package creation and deployment-request acceptance do not imply hosted
  health; hosted readiness does not imply RBAC, managed-identity authentication,
  Foundry access, or inference success
- Key Vault is deferred
- App Service Authentication / Entra ID protection is deferred
- Confirmed ACS SMS handset delivery is not implemented and remains pending
  external toll-free verification and future delivery tracking

## 7. Explicitly Deferred AI-103 / Azure Work

The following are future work, not current implementation:

- Live Azure AI Foundry structured extraction
- Azure AI Foundry Agent/tool orchestration, if still useful after the simpler
  Foundry provider path
- Azure Speech transcription service
- Live Web App infrastructure and code deployment plus execution of hosted
  readiness checks
- Live RBAC deployment and hosted managed-identity authentication/invocation
- Agent-specific RBAC scope
- Key Vault
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

- Live RBAC deployment and managed-identity authentication
- Disposable Web App infrastructure and code deployment followed by hosted
  readiness verification; the Python build setting is already offline-tested
- Key Vault
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
4. Disposable mock-only Web App infrastructure and code deployment, followed
   by separately proven hosted readiness checks
5. Live RBAC and managed-identity validation when explicitly approved
6. Key Vault and App Service auth/protected routes
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
