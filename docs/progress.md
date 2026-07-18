# Nurse Intake Assistant Progress

Active resume document; June 2026 history is in `docs/archive/progress-2026-06.md`.

## Current Status
Latest verified test baseline:
- 1,408 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

**Active implementation direction:** The project is deliberately moving from
the local mock capstone into an Azure-first Microsoft Foundry Agent
implementation. Current momentum is:

```text
Disposable Foundry infrastructure
-> immutable prompt-agent lifecycle
-> guarded agent invocation
-> evaluation and Foundry metric publication
-> managed-identity-ready Web App hosting
-> offline-tested App Service remote-build prerequisite
-> explicit offline-tested Web App infrastructure deployment boundary
-> offline-tested Web App configuration verification
-> deterministic source deployment packaging
-> explicit Web App code-deployment request
-> offline-tested hosted Web App readiness verification
-> live-proven project-scoped Foundry Agent Consumer RBAC deployment boundary
-> live-proven read-only direct-assignment verification
-> offline-tested Web App-hosted managed-identity prompt-agent verification
-> offline-tested fixed-fictional-data Web App-hosted prompt-agent invocation boundary
```

Mock mode remains the safe default, hosted notifications remain suppressed,
and all AI output continues to require human nurse review.

The current MVP is a local mock/demo only Nurse Intake Assistant capstone flow covering intake, mock AI extraction, urgency, nurse review, notifications, and a local demo UI.

Important constraints:
- Local mock/demo only
- No production clinical use
- No live Azure integration in the demo page
- Mock mode sends no real email or SMS
- AI output requires human nurse review
- Do not commit secrets, connection strings, real contact data, credentials, or patient data

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
- `infra/modules/web-app.bicep`: optional Linux Web App and system-assigned identity boundary with offline-tested remote-build automation; application hosting remains disabled by default.
- `src/app/services/web_app_infra_deployment.py`: sanitized infrastructure deployment contract; `scripts/deploy_web_app_infra.py`: offline check and explicit what-if/live operator CLI for the existing `main.bicep`.
- `src/app/services/web_app_hosting_contract.py`: exact seven-setting contract
  shared by infrastructure deployment and configuration verification.
- `infra/foundry-agent-consumer-rbac.bicep`: explicit independent assignment entry point; `infra/modules/foundry-agent-consumer-rbac.bicep`: project-scoped Foundry Agent Consumer role module.
- `src/app/services/foundry_agent_consumer_rbac_deployment.py` and `scripts/deploy_foundry_agent_consumer_rbac.py`: offline check plus explicit what-if/live request boundary for that exact entry point.
- `src/app/services/foundry_agent_consumer_rbac_verification.py` and `scripts/verify_foundry_agent_consumer_rbac.py`: offline check plus explicit read-only assignment proof for the exact identity, role, and project scope.
- Packaged `src/app/operations/verify_hosted_foundry_agent.py`: strict system-identity metadata verification using the existing agent contract.
- Packaged `src/app/operations/invoke_hosted_foundry_agent.py`: separate strict system-identity boundary for one fixed fictional invocation and sanitized application-contract proof; check mode is offline and live remains explicit.
- `infra/foundry-only.bicep`: preferred lightweight entry point for disposable daily Foundry validation.
- `infra/foundry-only.example.bicepparam`: committed fictional example; `infra/foundry-only.bicepparam` is ignored, operator-local, and must not be committed.
- `scripts/deploy_foundry_infra.py`: approved deployment boundary; `scripts/verify_foundry_infra.py`: approved read-only verification boundary.
- `src/app/services/web_app_package.py`: deterministic source deployment package boundary; `scripts/package_web_app.py`: offline check/package CLI; `scripts/deploy_web_app_code.py`: explicit existing-Web-App deployment CLI.
- `src/app/services/web_app_readiness_verification.py`: sanitized hosted readiness contract; `scripts/verify_web_app_readiness.py`: offline check and explicit read-only live CLI.
- `src/app/services/web_app_configuration_verification.py`: Bicep-owned hosting contract verifier; `scripts/verify_web_app_configuration.py`: offline check and explicit read-only Azure CLI boundary.

## Pre-Codex Azure Readiness Checklist

This checklist is mandatory before starting any Codex prompt whose acceptance criteria include live Azure operations or depend on Azure infrastructure, Foundry resources, hosted application code, managed identity, RBAC, an agent, or another live prerequisite. The operator, not Codex, must complete it before the implementation thread begins. Every applicable item must prove that required resources are deployed, currently verified, correctly named, and usable.

### 1. Azure authentication and subscription

- [ ] Run the operator login and current-account check:

```bash
az login

az account show \
  --query "{subscription:name,state:state,isDefault:isDefault}" \
  --output table
```

- [ ] Confirm the intended subscription by name, an `Enabled` state, and the intended default selection. Stop before Codex begins if authentication or subscription selection is wrong; never copy subscription or tenant IDs into prompts or documentation.

### 2. Exact approved resource inventory

- [ ] Record the operator-approved names for every applicable resource group, Foundry account, child project, model deployment, Linux Web App, prompt agent and immutable version, managed identity, RBAC role and exact scope, hosted endpoint, and other slice prerequisite.
- [ ] Match every name to fresh repository-owned verifier output. Historical deployment evidence, portal screenshots, assumed names, previous conversation history, and inferred resource groups are not sufficient.

### 3. Authoritative deployment and current usability proof

- [ ] Deploy every missing prerequisite before the Codex prompt through the repository's authoritative Bicep entry points and approved scripts; never substitute portal-only creation, duplicate definitions, or ad hoc Azure CLI provisioning.
- [ ] Run current read-only verification proving provisioning state and usability: Foundry account/project/model and required agent version; hosted code, safe configuration, system identity, and readiness endpoints; and any exact direct RBAC assignment required before managed-identity access.
- [ ] Deploy only the current slice's prerequisites. Keep infrastructure deployment separate from prompt-agent creation; keep hosted code, Foundry provisioning, agent lifecycle, RBAC deployment, RBAC verification, managed-identity verification, and invocation explicit and separately verifiable.

### 4. Azure-Dependent Slice Execution Gate and Azure-Dependent Slice Runbook Gate

- [ ] Complete a checked-in slice-specific runbook under `docs/runbooks/` and name it in the acceptance criteria. It must identify authoritative Bicep ownership, exact approved parameters, repository-approved compile/check/what-if/manual-review/deploy/verify stages, success contracts, and fail-fast stop conditions.
- [ ] Hand Codex only sanitized current evidence and the completed checklist. No Codex implementation prompt or live acceptance criterion may begin until every applicable item is checked; offline RED-to-GREEN work may begin only when it does not claim live readiness.

Missing or unusable prerequisites stop the thread without retry or inferred replacements. General-purpose shell polling loops, repeated sleeps, indefinite waits, and improvised repeated verifier calls are prohibited; use at most one repository-approved bounded completion check only when the runbook requires it. Keep cleanup manual and explicit, use fictional disposable resources, and never commit or disclose secrets, credentials, IDs, real patient data, or real contact information.

### Azure RBAC Slice Lessons Learned

- Foundry infrastructure was not deployed before dependent work began.
- An obsolete resource group was inferred from prior history, and the Azure portal truncated the Foundry account name.
- Foundry existed while the required Linux Web App did not.
- Web App infrastructure existence did not prove application code deployment or hosted readiness.
- Healthy resources did not prove the Consumer RBAC assignment existed.
- The verifier initially used the wrong Foundry project ARM lookup.
- The outer ARM deployment and nested Bicep module used the same deployment name, causing `DeploymentActive`.
- Oversized Codex runs mixed infrastructure deployment, application deployment, readiness monitoring, defect correction, RBAC, and documentation, making state reconciliation difficult.
- Future Azure-dependent slices must complete prerequisite preparation before the narrow Codex implementation prompt begins.

Preferred workflow:

```text
Operator completes runbook and checklist
-> operator supplies exact verified resource inventory
-> Codex performs narrow offline RED-to-GREEN work
-> Codex performs only the explicitly approved live operation
-> separate read-only verification
-> documentation and commit
```

## Prerequisites Before The Next TDD Slice

For every attempt, complete `docs/runbooks/live-foundry-agent-consumer-rbac-prerequisites.md` with an explicit operator-approved parameter set. Deploy and verify Foundry through `infra/foundry-only.bicep`, `scripts/deploy_foundry_infra.py`, and `scripts/verify_foundry_infra.py` only when those resources are absent; otherwise obtain current Foundry, Linux Web App configuration, system-identity, and readiness proof before the RBAC stages. A prompt agent is not required for this project-scoped assignment; its immutable version remains a later prerequisite for hosted metadata verification.
Do not claim as complete:
- Live Azure AI Foundry extraction outside the manual Foundry Agent smoke path
- Historical evidence only: Manual live Foundry Agent smoke passed in an
  earlier slice with `ok=true`, `category=success`, `agent_attempted=true`,
  `agent_output_valid=true`, `fallback_used=false`, and fields `extraction`, `urgency`, and `handoffNote`; no hosted managed-identity smoke has run.
- No live Azure behavior is claimed for `/demo` by default;
  `AGENT_PROVIDER=mock` remains the safe local/demo default, and human nurse
  review remains mandatory.
- Live Azure Speech transcription, audio upload, or audio processing
- Managed-identity token acquisition, hosted Foundry metadata access, and invocation remain unproven live despite separately proven RBAC deployment and direct assignment
- ACS phone intake/call automation, Key Vault, App Service authentication,
  retry/durable processing, SMS delivery tracking, production frontend, or
  production clinical readiness

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
  case-list/query-filter parity, and point-read lookup where supported.
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
- Agent output contract validation added with safe fallback behavior and processing trace warnings.
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
- No Azure calls in tests, PHI, production clinical behavior, hosted
  authentication, Key Vault, phone intake automation, retry/durable processing,
  or frontend work were added.

## Infrastructure Summary

- `infra/main.bicep` is a resource-group-scope MVP baseline.
- It provisions Cosmos DB, a Cosmos SQL database, a `cases` container using
  `/createdDate`, a storage account, Log Analytics, and Application Insights.
- It can optionally provision a Linux App Service plan and Web App with a system-assigned identity and remote-build setting; `deployApp=false` preserves the existing default.
- A separate template can explicitly assign Foundry Agent Consumer at project
  scope without coupling access to `main.bicep`.
- The allowlisted package builder and explicit deployment CLI keep code upload
  separate from infrastructure, RBAC, startup checks, and Foundry operations.
- The Web App infrastructure CLI reuses `main.bicep`, never creates the resource group, and fixes `deployApp=true` with `deployFoundry=false`.
- `infra/README.md` documents Azure CLI build, validate, deploy, and cleanup
  commands.
- Manual Cosmos smoke testing verified local `APP_MODE=cosmos` with a deployed
  Cosmos account and a point read via `createdDate`.
- Manual Azure resource-group validation succeeded July 15, 2026, and created no
  resources. A later live Web App infrastructure deployment request succeeded;
  acceptance does not prove configuration, code deployment, or startup.
- Live read-only configuration verification then proved the complete Bicep-owned
  hosting contract while retaining mock providers and suppressed notifications.
- Deterministic packaging, explicit code deployment, and separate hosted `/health`, `/version`, and `/demo/status` verification also succeeded.
- No secrets are stored in infrastructure files.

## Known Issues And Future Enhancements

- `notificationSmsSent=true` is backward-compatible and should be read with
  `notificationSmsStatus` and `notificationSmsDeliveryConfirmed`.
- Confirmed live ACS SMS handset delivery is pending external toll-free
  verification and carrier/Azure regulatory workflow completion.
- Future enhancement: capture ACS message id/status or delivery report
  semantics for confirmed handset delivery status.
- Cosmos case-list/query-filter parity is covered offline with fakes and no Azure
  calls. Queue-summary and voicemail-idempotency lookup parity, pagination,
  aggregation, and live list validation remain deferred.
- Cosmos voicemail idempotency lookup supports sequential retries offline; live
  validation and atomic concurrent exactly-once guarantees remain deferred.

## Not Yet Implemented / Deferred Scope

- Authentication
- Agent-specific RBAC scope
- Live hosted managed-identity verification and agent invocation
- Key Vault
- Azure Speech/voice intake
- live Azure AI Foundry extraction
- ACS SMS delivery tracking
- Retry logic
- Production frontend
- Production clinical UI or autonomous medical decision-making

## Recommended Next Slice

The exact recommended next boundary is:

Project-scoped Consumer deployment and exact direct-assignment verification are separately proven.
Next narrow live boundary:
```text
Verify the required immutable prompt-agent version
-> hosted managed-identity Foundry metadata verification
```

Continue in small RED-to-GREEN slices with offline automated tests, sanitized
diagnostics, fictional data, explicit manual opt-in for live Azure operations,
mandatory nurse review, and no production clinical-readiness claim. Avoid
low-value frontend polish, unrelated local abstractions, or peripheral features
when a practical Foundry or Agents capability slice is available. Keep ACS
phone intake, Speech, auth, Key Vault, retry/durable processing, and production
frontend deferred unless explicitly scoped.

## Current Slice Status

- A documentation guardrail first failed because the prerequisite runbook was absent, then passed after `docs/runbooks/live-foundry-agent-consumer-rbac-prerequisites.md` and the permanent runbook gate were added. Full GREEN is 1,409 passed with one existing warning.
- Direct read-only diagnostics proved the project scope. Azure then conclusively identified the failed `Microsoft.Resources/deployments` operation as a nested deployment whose name equaled the deterministic outer name, producing `DeploymentActive`.
- RED was 3 failed and 112 passed. GREEN is 115 focused tests after the verifier switched to `az cognitiveservices account project show`, projected only name/ID, accepted leaf or qualified names, validated Azure's returned ID against the approved tuple, and failed closed before assignment reads for malformed or mismatched shapes. The existing Bicep parent/leaf project declaration already matched the authoritative API and was retained.
- Nested-name RED was 1 failed/8 passed; GREEN is 116 focused RBAC tests after the entry point changed only the module deployment name to `${deployment().name}-assignment`. Bicep compiled. One corrected what-if reported create 0, modify 0, delete 0, no-change 0, ignore 10, deploy 0, unsupported 1; the sole Unsupported category remains the expected `Microsoft.Authorization/roleAssignments` resource with no unrelated change.
- After one fresh matching what-if, Azure accepted the project-scoped Foundry Agent Consumer assignment deployment. A separate read-only verifier proved exactly one direct assignment for the Web App system identity at the exact Foundry project scope. Managed-identity token acquisition, hosted Foundry metadata access, and agent invocation remain unproven. No retry, polling, manual assignment, infrastructure or code deployment, token, inference, invocation, cleanup, commit, or push occurred; nurse review and non-production boundaries remain unchanged.

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
