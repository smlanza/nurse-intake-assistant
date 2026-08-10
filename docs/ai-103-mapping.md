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
TELEMETRY_PROVIDER=none
```

With those defaults, the demo makes no live Azure calls and sends no real email
or SMS.

## 2. Implemented AI-103-Aligned Capabilities

| AI-103 area | Current implementation | Evidence in repo | Status |
|---|---|---|---|
| Generative AI app design | `CaseProcessingService` orchestrates extraction, urgency merge, persistence, and notifications; AI provider factory selects the configured provider; `MockAiService` returns structured extraction, summary, and advisory classification; Pydantic models define API and output contracts | `src/app/services/case_processing_service.py`, `src/app/services/ai_service_factory.py`, `src/app/services/mock_ai_service.py`, `src/app/models/ai_outputs.py`, `src/app/models/case.py` | Implemented locally with mock AI |
| Azure AI Foundry / agent orchestration readiness | `FoundryAiService` and `NurseIntakeAgent` are application-integrated runtime boundaries with application-owned structured contracts and validation before trusting model/agent output. Packaged metadata, invocation, and synchronous combined-proof operations remain execution-mechanism-neutral. `HostedFoundryAgentSshTransport` preserves one-process transport, fixed probes, and a live-proven non-invoking check | `scripts/smoke_application_foundry_extraction.py`, `scripts/smoke_application_foundry_agent.py`, `src/app/services/hosted_foundry_agent_proof.py`, `src/app/services/hosted_foundry_agent_ssh_transport.py`, `scripts/run_hosted_foundry_agent_ssh_transport.py` | Application-integrated Foundry execution remains separately live-proven: application-integrated structured extraction and application-integrated Microsoft Foundry Agent execution both passed their production-composed boundaries. Offline tests use fakes and make no Azure calls. Project-scoped Consumer RBAC, deterministic packaging and deployment, hosted readiness, current-artifact equality, direct SSH transport, and the packaged non-invoking check remain separately proven. SSH hosted managed-identity execution is unsupported. Hosted managed-identity metadata access remains unproven, as does hosted Agent invocation. The WebJob trigger mechanism remains retired, and no replacement hosted execution mechanism is selected |
| Offline Foundry evaluation baseline and guidance | A strict repository-owned fictional v1 dataset, provider-neutral candidate contract, deterministic exact/set scorer, application-composed single-mode runner and CLI, and prompt/schema/evaluation guidance establish a reusable offline baseline. Expected urgency labels remain `Routine` or `Urgent`; observed contract-invalid output may use safe `Unknown` urgency only in application-consistent fallback states | `evaluation/fictional-intake-baseline-v1.json`, `evaluation/fictional-intake-baseline-v1-candidates.json`, `src/app/services/foundry_evaluation.py`, `src/app/services/foundry_application_evaluation.py`, `scripts/evaluate_foundry_application.py`, `docs/foundry-prompt-schema-evaluation.md` | Implemented offline without Azure, network, external persistence, or notifications. Each CLI run selects one application mode, uses deterministic fake clients, and emits sanitized JSON. Observed `Unknown` scores as an ordinary mismatch instead of being fabricated or crashing evaluation; deterministic-rule and nurse-review evidence remain scoreable. It is not a live Foundry evaluation run, not model-as-judge evaluation, not a provider comparison, not subjective clinical-quality scoring, and not clinical validation |
| Responsible AI / human oversight | Responsible AI pattern: urgency is advisory only; invalid agent output uses safe fallback values instead of crashing intake processing; deterministic red-flag rules supplement AI and may promote final urgency; red-flag matching is negation-aware; nurse review is persisted; no autonomous clinical decision-making is implemented | `src/app/services/urgency_rules_service.py`, `src/app/services/nurse_intake_agent_contract.py`, `src/app/config/red_flags.yaml`, `src/app/routes/cases.py`, `tests/test_red_flags.py`, `tests/test_case_processing_service.py`, `docs/architecture.md` | Implemented human review and deterministic safety rules |
| Natural language processing and Speech readiness | Text intake and voicemail transcript intake convert natural language into patient fields, reason, symptoms, summary, missing fields, intake status, and advisory urgency. The offline/mock provider boundary remains implemented, the Azure SDK adapter is implemented, and one fixed-fictional standalone Azure Speech transcription is live-proven through the production factory/service/adapter | `src/app/routes/intake.py`, `src/app/services/speech_transcription_service.py`, `src/app/services/speech_transcription_factory.py`, `src/app/services/azure_speech_transcription_adapter.py`, `scripts/smoke_azure_speech_transcription.py`, `tests/fixtures/fictional_speech_intake.wav`, `tests/test_azure_speech_transcription_smoke.py`, `docs/runbooks/live-azure-speech-transcription-prerequisites.md` | Check mode validates the owned PCM fixture and emits deterministic sanitized JSON without recognition. One supervised standalone attempt returned the expected normalized transcript, made one Azure call and no mutation, and used no route, persistence, or notification path. Application routes remain text/already-transcribed-text only; human nurse review remains mandatory; route-level audio ingestion and voice automation remain deferred |
| Azure service integration boundaries | Cosmos repository and container factory with point reads/upserts plus cross-partition filtered case-list queries; ACS Email/SMS boundaries; typed sanitized intake telemetry with a no-op default, lazy Azure Monitor adapter, production-composed standalone ingestion proof, private READY-bound Application Insights identity, and sanitized wire-shape diagnostics; Bicep baseline for Cosmos, storage, Log Analytics, Application Insights, and optional Azure Web App hosting | `src/app/services/cosmos_case_repository.py`, `src/app/services/cosmos_container_factory.py`, `src/app/services/email_notification_sender.py`, `src/app/services/sms_notification_sender.py`, `src/app/models/intake_telemetry.py`, `src/app/services/application_insights_resource_identity.py`, `src/app/services/azure_monitor_intake_telemetry.py`, `src/app/services/application_insights_intake_telemetry_proof.py`, `src/app/services/application_insights_telemetry_wire_diagnostic.py`, `scripts/smoke_application_insights_intake_telemetry.py`, `infra/main.bicep`, `infra/modules/web-app.bicep`, `infra/README.md` | READY privately binds the exact validated component name and Azure-returned ARM ID to the current environment in a schema-v5 receipt; public output exposes only bounded proof booleans, legacy receipts fail closed, and the standalone proof consumes rather than derives or discovers identity. Two supervised standalone attempts emitted exactly once each, but both bounded verifications rejected the relevant row as `telemetry_record_invalid`, including the corrected string-wire attempt. The offline diagnostic classifier exposes only allowlisted field names and fixed mismatch/type enums; no deterministic failed-attempt window remains for a live read-only diagnosis. Live and hosted Web App telemetry remain unproven. This is neither clinical validation nor production monitoring; queue-summary and voicemail-idempotency lookup parity, live Cosmos validation, and production hardening are deferred |
| Application architecture | FastAPI routes support intake, case list, filtering, summary, lookup, nurse review, demo seed/reset, notification inspection, health, and static demo/legal pages | `src/app/routes/`, `src/app/main.py`, `src/app/static/demo.html`, `tests/test_cases_route.py`, `tests/test_demo_page_route.py`, `tests/test_demo_reset_route.py`, `tests/test_notifications_route.py` | Implemented local MVP |
| Notification status semantics | Legacy booleans remain backward-compatible while explicit email/SMS status fields distinguish `MockRecorded`, `Accepted`, `Failed`, `Suppressed`, and `NotAttempted`; SMS delivery confirmation remains false until future tracking exists | `src/app/models/case.py`, `src/app/services/case_processing_service.py`, `tests/test_case_processing_service.py`, `docs/architecture.md` | Implemented semantics |
| Testing and reliability | Pytest covers provider factories, repositories, routes, safety rules, notification behavior, static pages, and stable documentation guardrails. Azure-dependent slices additionally require a checked-in prerequisite runbook with authentication, authoritative Bicep, fail-fast stages, and current read-only proof | `tests/`, `pytest.ini`, `docs/demo-smoke-test.md`, `docs/runbooks/live-foundry-agent-consumer-rbac-prerequisites.md` | Implemented project discipline; automated tests make no Azure calls |
| Reusable Foundry infrastructure | One Bicep module defines an Entra-oriented AIServices account, child project, and explicitly parameterized model; full-stack and disposable entry points reuse it. The Foundry what-if boundary returns sanitized counts for seven allowed change types and fails closed on malformed or unknown shapes; a separate verifier accepts Azure's qualified `<account>/<project>` child-resource name | `infra/modules/foundry.bicep`, `infra/main.bicep`, `infra/foundry-only.bicep`, `scripts/deploy_foundry_infra.py`, `scripts/verify_foundry_infra.py` | Current read-only verification of an explicit operator-approved parameter set proved the AIServices account, child project, endpoint contract, and model deployment. Disposable names are not permanent defaults |
| Managed-identity and RBAC readiness | Optional IaC defines a Linux Web App system identity and separate project-scoped Consumer assignment. The verifier resolves and validates Azure's returned project ID without manual construction. The outer deployment name is deterministic while the nested module derives the distinct `${deployment().name}-assignment` name; project scope, fixed role, deterministic assignment GUID, and identity lookup remain unchanged | `infra/foundry-agent-consumer-rbac.bicep`, `infra/modules/foundry-agent-consumer-rbac.bicep`, `src/app/services/foundry_agent_consumer_rbac_verification.py`, `tests/test_foundry_agent_consumer_rbac_bicep.py` | After the collision correction and a fresh matching preview, Azure accepted the project-scoped Consumer assignment deployment. A separate read-only verifier proved exactly one direct assignment for the Web App system identity at the exact project scope. Token use, hosted metadata access, agent operation, and invocation remain unproven |
| Key Vault infrastructure and authorization readiness | `main.bicep` optionally creates the repository-owned zero-secret RBAC-mode vault beside the Web App but never composes runtime RBAC. After exact current vault and Web App identity verification, the daily coordinator reuses one correct direct assignment or offers the existing evidence-bound, default-no standalone Key Vault Secrets User deployment, independently rereads it, and conditionally gates READY; the human Reader boundary remains separate | `infra/main.bicep`, `infra/modules/key-vault.bicep`, `infra/key-vault-reader-rbac.bicep`, `infra/modules/key-vault-reader-rbac.bicep`, `infra/key-vault-secrets-user-rbac.bicep`, `infra/modules/key-vault-secrets-user-rbac.bicep`, `src/app/services/key_vault_live_proof.py`, `src/app/services/daily_azure_environment_rebuild.py`, `tests/test_daily_azure_environment_rebuild.py` | Offline daily-generation Key Vault runtime RBAC orchestration is implemented, including principal-churn invalidation, exact independent verification, safe reuse, evidence-bound Bicep repair, and conditional READY proof. Live daily-generation runtime RBAC is not yet proven. Existing live vault infrastructure proof remains valid; operator Reader authorization and zero-secret metadata proof remain unproven. Live secret retrieval, credential migration, App Service references, and production secret operations remain deferred |
| Repeatable application deployment readiness | An explicit CLI deploys Web App infrastructure through the existing `main.bicep` with Foundry disabled; its local reader enforces the exact shared hosted settings contract, and what-if exposes sanitized change counts only. Separate boundaries verify Bicep-owned configuration, package and deploy code, and check `/health`, `/version`, and `/demo/status` | `src/app/services/web_app_hosting_contract.py`, `src/app/services/web_app_infra_deployment.py`, `scripts/deploy_web_app_infra.py`, `src/app/services/web_app_configuration_verification.py`, `scripts/verify_web_app_configuration.py`, `src/app/services/web_app_package.py`, `scripts/deploy_web_app_code.py`, `src/app/services/web_app_readiness_verification.py`, `scripts/verify_web_app_readiness.py` | Current verification proved configuration, system identity, mock-safe hosted posture, application deployment, artifact equality, and hosted readiness. Check modes make no Azure or HTTP call. Direct project-scoped Consumer RBAC is separately live-proven; managed-identity Foundry access and invocation remain unproven |

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
`FoundryAiService` is the live Azure AI Foundry structured-extraction boundary.
The contract defines prompt guardrails, expected JSON shape, parser validation,
and mapping into the current extraction and urgency output models. The
fixed-fictional application smoke composes that provider through
`compose_application(settings)` and `CaseProcessingService`. The
application-integrated path is live-proven with valid structured output, no
fallback, deterministic urgency-rule evaluation, in-memory persistence,
suppressed notifications, mandatory nurse review, and no Azure mutation. The
backend continues to own side effects; the AI provider returns only structured
output.

The agent path follows the same responsible AI pattern: `NurseIntakeAgent` is
an external reasoning boundary, and agent contract validation runs before the
app trusts model/agent output. Valid output can provide summary and urgency
classification. Invalid output uses a safe fallback for nurse review, while
deterministic red-flag rules still evaluate the raw intake text and may promote
final urgency. The processing trace records agent usage, warnings, and final urgency source for audit-friendly review.

Application-integrated Microsoft Foundry Agent execution is separately
live-proven through production composition with valid Agent output, no
fallback, deterministic urgency-rule execution, in-memory persistence,
suppressed notifications, mandatory nurse review, and no Azure mutation.
Neither application-integrated path proves hosted managed-identity token
acquisition, hosted Foundry metadata access, or hosted Foundry invocation.

The fixture-based offline Foundry baseline is provider-neutral and does not
invoke either application path. Separately, the application evaluation CLI
selects exactly one structured-extraction or Agent mode and uses deterministic
fake clients while the existing runner processes all eight cases through
production composition. Both paths reuse the same strict candidate and scorer.
A small fictional dataset and separate intentionally imperfect candidate
fixture provide exact structured-field, set-based symptom and missing-field,
urgency, deterministic-rule, and nurse-review evidence. Reports expose only
sanitized case IDs, counts, rates, match booleans, and safe error categories.
The baseline and application CLI are not live Foundry evaluation, model-as-judge
evaluation, provider comparison, or clinical validation. Prompt/schema/evaluation
guidance is documented in `docs/foundry-prompt-schema-evaluation.md`.
Expected advisory, final, and deterministic-rule labels remain binary
`Routine` or `Urgent`. A contract-invalid observed candidate may instead carry
safe `Unknown` advisory urgency and the application-consistent fallback final
urgency. Those observed values score as mismatches rather than being converted
or causing evaluation to abort. This correction was deterministic and offline;
no model, Agent, or live Foundry evaluation ran.

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
blob, caller phone, and idempotency metadata. The Speech transcription provider
boundary now has an offline mock provider and an opt-in Azure SDK adapter with
lazy construction and injected-fake coverage, but neither route invokes it and
both routes remain text-only.

The standalone fixed-fictional transcription boundary is live-proven. Exactly
one recognition attempt through the production Speech factory, service, and
Azure SDK adapter returned the application-owned expected normalized text. It
made one Azure call, no Azure mutation, and did not invoke a route, persist a
case, attempt a notification, or perform clinical processing. This single
proof is not clinical validation or general Speech reliability validation.

Deferred route-level audio and voice work:

- Audio upload and microphone capture
- ACS recording ingestion and transcription
- Voice intake and ACS call automation
- Streaming transcription
- Audio retention and cleanup
- Production clinical audio workflows

This keeps the current app honest: it demonstrates transcript processing and a
live-proven standalone fixed-fictional Speech boundary, not route-integrated
audio ingestion, general voice intake, or production Speech processing.

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
- An application-owned optional Key Vault secret provider boundary with local
  default selection, deterministic configuration validation, lazy Azure client
  construction, exact-name fake-client verification, private value handling,
  and sanitized failure categories, all implemented and proven offline
- One typed terminal intake telemetry event per processing attempt, with a no-op
  default and an explicitly selected lazy Azure Monitor adapter
- One standalone telemetry smoke boundary that production-composes a single
  fixed-fictional local intake, emits once, and performs bounded read-only
  allowlist verification with no infrastructure mutation
- One standalone fixed-fictional Azure Speech transcription through the
  production factory/service/adapter, with no route or application side effect

Scope boundaries:

- Cosmos queue-summary and voicemail-idempotency lookup parity are deferred
- Cosmos live list-query validation, pagination, and aggregation tuning are deferred
- The standalone Application Insights ingestion proof is implemented and
  offline-tested; READY identity handoff is private and fail-closed. Two live
  fixed-fictional emissions separately used fresh compatible READY evidence, but
  both strict verifications stopped on `telemetry_record_invalid`. Sanitized
  offline wire-shape diagnostics are implemented, but no deterministic prior
  query window remains; live or App Service-hosted telemetry remain unproven
- Web App infrastructure, its explicit deployment CLI, remote-build setting,
  deterministic packaging, read-only configuration verifier, code-deployment request, and
  read-only hosted-readiness verifier are represented and offline-tested; live
  infrastructure, configuration, package, code-deployment, and readiness proof
  all succeeded as separate stages
- The deployment CLI and configuration verifier share one exact mock-provider
  and notification-suppression contract. What-if emits only sanitized counts;
  proposed deletes require review and never trigger deployment automatically
- System-assigned identity and project-scoped Foundry Agent Consumer RBAC are represented in separate IaC boundaries
- The explicit RBAC deployment and read-only assignment-verification boundaries
  are live-proven separately: Azure accepted the project-scoped Consumer
  deployment, then a read-only verifier proved exactly one direct assignment.
  The final fresh READY generation subsequently reused and reverified that
  exact assignment without mutation. No token acquisition, hosted Foundry
  verification, or invocation occurred
- The packaged App Service-hosted prompt-agent verifier is offline-tested only. Its system-assigned
  identity credential and metadata reads do not prove hosted authorization
- The verifier's exact five non-secret settings use a disabled-by-default tagged
  Bicep configuration; ordinary Web App deployment omits them, while explicit
  opt-in requires all five nonblank values and enables matching read-only proof.
  Direct `main.bicep` and reusable `web-app.bicep` deployments reject whitespace
  through trim-aware nested-module `minLength` validation without experimental
  Bicep features.
  The seven mock-safe application settings remain unchanged.
- A separate generation-bound one-file WebJob package, upload, immutable
  handoff, and fixed-resource Kudu discovery boundary exists. Live handoff and
  discovery succeeded, proving generation binding and registration of the
  fixed `run.py` WebJob. Neither proof establishes execution or Foundry access.
- Multiple fresh supervised trigger attempts returned
  `trigger_acceptance_ambiguous`, and Azure exposed no safely correlatable
  execution record. The current WebJob trigger-and-correlation mechanism is
  retired from supported operations; this is not a claim that Azure WebJobs
  are universally impossible.
- The preserved retired reconciliation design made one history read and
  allowed private exact-run correlation only for exactly one eligible known
  run. Zero, multiple, malformed, or unsupported results remain blocked and
  never authorize retriggering. Those code contracts are historical evidence,
  not a recommended AI-103 exercise.
- Hosted managed-identity metadata access and fixed-fictional hosted invocation
  remain unproven; the application-integrated structured-extraction and Agent
  paths are separately live-proven
- The ordinary application package contains execution-mechanism-neutral,
  offline-tested metadata, invocation, and synchronous combined-proof
  operations. Direct App Service SSH transport, its one-tunnel lifecycle, both
  `APP_PATH` probes, and the packaged non-invoking check are live-proven. SSH
  hosted managed-identity execution is unsupported, and no replacement hosted
  execution mechanism is selected
- The separate packaged hosted invocation boundary is offline-tested only. It
  accepts no operator prompt, uses one fixed fictional request, validates only
  approved output sections, and performs no persistence or notification work
- Infrastructure deployment, configuration verification, code deployment,
  hosted readiness, WebJob discovery, RBAC verification, managed-identity
  metadata verification, and agent invocation remain distinct proof
  boundaries. Trigger acceptance and correlated status belong to the retired
  mechanism
- Configuration verification does not prove code deployment. Package creation
  and deployment-request acceptance do not imply hosted health; hosted readiness
  does not imply RBAC, managed-identity authentication, Foundry access, or
  inference success
- Key Vault infrastructure is live-deployed and its exact control-plane
  identity, successful provisioning, RBAC mode, and absent legacy policies are
  proven. Current-generation managed-identity RBAC orchestration and READY
  gating are implemented offline, but live daily acceptance is unproven.
  Zero-secret metadata proof, retrieval, current-credential migration, App
  Service Key Vault references, and production rotation remain deferred
- App Service Authentication / Entra ID protection is deferred
- Confirmed ACS SMS handset delivery is not implemented and remains pending
  external toll-free verification and future delivery tracking

## 7. Explicitly Deferred AI-103 / Azure Work

The following are future work, not current implementation:

- Hosted managed-identity metadata verification and fixed-fictional-data invocation
- Agent-specific RBAC scope
- Live acceptance of daily-generation Key Vault runtime RBAC, completion of
  zero-secret metadata proof, live retrieval, current-credential migration,
  App Service references, and production secret rotation/operations
- App Service Authentication / Entra ID protection
- App Service-hosted telemetry configuration and verification
- Audio upload, microphone capture, ACS recording ingestion, streaming
  transcription, audio retention/cleanup, and production clinical audio workflows
- ACS phone intake/call automation
- ACS SMS delivery reports/status tracking
- Retry/durable processing
- Production security, compliance, audit, and clinical workflow hardening

## 8. Exam ROI For Future Slices

Highest AI-103 ROI:

- Managed-identity authentication and hosted Foundry verification

Medium AI-103 ROI:

- Live acceptance of the offline daily-generation Key Vault RBAC contract
- App Service Authentication / Entra ID route protection

Lower direct exam ROI but strong portfolio value:

- ACS phone intake
- Full phone-recording/callback workflow
- Production dashboard polish

## 9. Recommended Azure Implementation Order

1. Select the next slice later from medium-value security and operations work; do not continue SSH acceptance or automatically select a replacement hosted execution mechanism
2. Key Vault: run the separate live acceptance of daily-generation least-privilege authorization
3. App Service Authentication and protected routes
4. App Service-hosted telemetry configuration and verification
5. ACS phone intake and route-level audio ingestion
6. Retry/durable processing
7. Advanced Foundry Agent/tool orchestration only if useful

This order prioritizes AI-103 learning value before lower-exam-value telephony
workflow work.

## 10. Scope Honesty Checklist

When presenting the capstone, do not imply that the current MVP already has:

- Hosted managed-identity Foundry access or invocation
- Route-integrated audio ingestion or voice workflows
- ACS phone intake
- App Service authentication
- Live Key Vault integration or production secret management
- Confirmed SMS handset delivery
- Production clinical readiness

Accurate portfolio framing:

```text
Built a mock-first Nurse Intake Assistant in FastAPI with live-proven
application-integrated Microsoft Foundry structured-extraction and Agent modes,
deterministic urgency rules, mandatory nurse review, in-memory smoke
persistence, suppressed smoke notifications, and Azure-ready provider
boundaries for Cosmos DB and ACS Email/SMS. A separate fixed-fictional Azure
Speech provider proof is live-proven without route integration or side effects.
```

Future-facing framing:

```text
The offline packaged hosted Foundry proof composition is implemented. Direct
App Service SSH transport and prerequisite probes are live-proven, and the
packaged non-invoking check is live-proven through that transport. SSH hosted
managed-identity execution is unsupported, and runtime identity markers remain
outside the operator and transport boundary.
Application-integrated Foundry execution remains separately live-proven.
Hosted managed-identity metadata access and hosted Agent invocation remain
unproven and separate. The packaged proof operations remain
execution-mechanism-neutral, no replacement hosted execution mechanism is
selected, and the WebJob trigger mechanism remains retired.
```
