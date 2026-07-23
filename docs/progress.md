# Nurse Intake Assistant Progress

Active resume document; June 2026 history is in `docs/archive/progress-2026-06.md`.

## Current Status

Latest verified test baseline:
- 2,127 passed full suite; 422 passed focused and 471 passed broader
  Web App contract and Modify-policy groups
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

The coordinator-owned command-result adapter is live-proven to reach Azure response classification while preserving the hosted boundary's exact `CommandResult` contract. Discovery then stopped safely as `azure_request_failed`; a separate read-only diagnostic found `alwaysOn=false` and `WEBSITE_SKIP_RUNNING_KUDUAGENT` absent.
Azure `ResourceIdOnly` what-if proves the exact Web App resource identity, not individual changed properties. Before accepting the seven-`NoChange`/one-`Modify` topology, the repository enforces the complete allowed active Web App Bicep resource shape, including exact nested keys, expressions, app settings, tags, and dependency. The authoritative `siteConfig.appSettings` member must be exactly the baseline array concatenated with `hostedFoundryVerifierAppSettings`, and that identifier must resolve to exactly one active top-level declaration parsed structurally outside comments and strings. Matching decoys cannot satisfy either contract. Active relative resources directly parented to `webApp`, including conditional configuration children and slots, are rejected after any balanced `if (...)` condition is parsed before the actual resource body. Approval explicitly describes a resource-level modification and remains default-no, fresh-preview-bound, and separately verified before discovery. Zero, account-only, project-only, or both exact sanitized Foundry-reference `Ignore` records are accepted; duplicates and unrelated evidence remain rejected.

The live Consumer RBAC diagnostic consistently proves exactly 10 Ignore and one
Unsupported record, with zero Create, Modify, Delete, Deploy, Replacement,
NoChange, or unknown actions. Azure what-if does not provide stable canonical
identity evidence for every record, so this exact distribution is a bounded
manual-review preview rather than Azure proof of assignment contents. Repository
safety still requires the validated local Bicep contract, exact approved Web App
principal and Foundry project scope, fixed Consumer role, deterministic assignment
name, and default-no approval. A complete current-generation reread, canonical
fingerprint comparison, second exactly matching preview, constrained deployment,
and separate direct-assignment verification remain mandatory. Exact single-Create
acceptance remains strictly bound to complete identity, parent, scope, principal,
role, assignment-name, and after-properties proof. No Azure, HTTP, or RBAC
operation occurred during this offline implementation; no WebJob,
managed-identity, Foundry, invocation, cleanup, commit, or push operation
occurred. No discovery, trigger, status, metadata, or invocation success is
claimed. The environment remains not ready.

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
-> offline-tested project-scoped Foundry Agent Consumer RBAC deployment boundary
-> current read-only direct-assignment verification reports assignment missing
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
- `infra/main.bicep`: authoritative full initial application entry point; Foundry remains optional through `deployFoundry=false` by default.
- `infra/modules/foundry.bicep`: single reusable AIServices account/project/model module; do not duplicate these definitions.
- `infra/modules/web-app.bicep`: reusable initial-create module and direct existing-Web-App reconciliation boundary with offline-tested Linux hosting, system-assigned identity, and remote build; reconciliation passes the existing plan name and disables plan deployment.
- `src/app/services/web_app_infra_deployment.py`: sanitized, purpose-bound initial-create and reconciliation deployment contract; `scripts/deploy_web_app_infra.py`: offline check and explicit what-if/live operator CLI with nondefault `--reconcile-existing-web-app` selection.
- `src/app/services/web_app_hosting_contract.py`: exact seven-setting contract
  plus a separate exact five-setting hosted-verifier contract shared by
  infrastructure deployment and configuration verification.
- `infra/foundry-agent-consumer-rbac.bicep`: explicit independent assignment entry point; `infra/modules/foundry-agent-consumer-rbac.bicep`: project-scoped Foundry Agent Consumer role module.
- `src/app/services/foundry_agent_consumer_rbac_deployment.py` and `scripts/deploy_foundry_agent_consumer_rbac.py`: offline check plus explicit what-if/live request boundary for that exact entry point.
- `src/app/services/foundry_agent_consumer_rbac_verification.py` and `scripts/verify_foundry_agent_consumer_rbac.py`: offline check plus explicit read-only assignment proof for the exact identity, role, and project scope.
- Packaged `src/app/operations/verify_hosted_foundry_agent.py`: strict system-identity metadata verification using the existing agent contract.
- Fixed packaged WebJob `App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py`
  and `scripts/run_hosted_foundry_agent_verification.py`: offline check plus
  separate one-read discovery, one-request trigger, and receipt-correlated
  one-read status boundaries.
- `src/app/services/hosted_foundry_agent_webjob_state_recovery.py`,
  `scripts/recover_hosted_foundry_agent_webjob_state.py`, and the dedicated
  recovery runbook: separate offline manifest inspection and default-no,
  reservation-held quarantine/reinspection of immutable lifecycle evidence.
- Packaged `src/app/operations/invoke_hosted_foundry_agent.py`: separate strict system-identity boundary for one fixed fictional invocation and sanitized application-contract proof; check mode is offline and live remains explicit.
- `infra/foundry-only.bicep`: preferred lightweight entry point for disposable daily Foundry validation.
- `infra/foundry-only.example.bicepparam`: committed fictional example; `infra/foundry-only.bicepparam` is ignored, operator-local, and must not be committed.
- `scripts/deploy_foundry_infra.py`: approved deployment boundary; `scripts/verify_foundry_infra.py`: approved read-only verification boundary.
- `src/app/services/web_app_package.py`: deterministic source deployment package boundary; `scripts/package_web_app.py`: offline check/package CLI; `scripts/deploy_web_app_code.py`: explicit existing-Web-App deployment CLI.
- `src/app/services/web_app_readiness_verification.py`: sanitized hosted readiness contract; `scripts/verify_web_app_readiness.py`: offline check and explicit read-only live CLI.
- `src/app/services/web_app_configuration_verification.py`: Bicep-owned hosting contract verifier; `scripts/verify_web_app_configuration.py`: offline check and explicit read-only Azure CLI boundary.

## Daily Disposable Azure Environment Gate

Because the operator deletes the resource group to control cost, every new
Azure session starts **NOT READY**: assume the resource group and all dependent
resources are absent until the operator supplies fresh proof from the current
session. The permanent rebuild procedure is
`docs/runbooks/daily-disposable-azure-environment-rebuild.md`.

`scripts/rebuild_daily_azure_environment.py` is the preferred daily path. Its
offline `--check --json` validates stable local configuration and orchestration
contracts; explicit `--live --json` sequences the existing deployment and
verification boundaries, reuses conclusively valid resources, and returns one
sanitized aggregate result. The detailed manual runbook remains the fallback,
recovery, and audit reference. Azure-dependent Codex prompts still require a
fresh current-session `daily_environment_ready=true` result. READY now requires
current-generation WebJob discovery, receipt-bound terminal success,
managed-identity metadata verification, and one fixed-fictional invocation.
The coordinator still does not process intake, send notifications, or delete
the resource group.

The current remediation requires exact subscription, resource-group, Foundry
account/project parent, project scope, principal, fixed role, deterministic
assignment, multiplicity, and boundary proof for the Consumer RBAC preview.
After preview-bound default-no approval, the coordinator freshly verifies the
resource group, Foundry/model and prompt-agent generation, Web App
configuration, deterministic package and deployed readiness generation,
current Web App identity/principal, and RBAC discovery. It recomputes the
shared canonical generation fingerprint, regenerates the sanitized RBAC
what-if, and deploys only when both fresh bindings exactly match the approved
evidence. Stale or unavailable proof stops without deployment or automatic
reapproval. The packaged WebJob accepts only exact application-owned result
types and exact booleans for metadata verification followed by one
fixed-fictional invocation.

Deleting the resource group expires all prior evidence for the resource group,
Foundry AIServices account, child project and model deployment, prompt agent and
immutable version, Linux Web App and system-assigned identity, hosted-verifier
settings, application package and deployed code, readiness endpoints, direct
Consumer RBAC assignment, remote WebJob, managed-identity Foundry access,
metadata verification, and invocation. Previous progress entries, runbook
completion, terminal output, portal screenshots, conversations, resource names,
deployments, and smoke tests cannot satisfy a new session's gate.

Classify each proposed prompt before work begins:

- `offline-only`: local code, tests, or documentation may proceed, but must make
  no current live-Azure or hosted-readiness claim.
- `Azure-dependent`: any prompt whose implementation or acceptance depends on
  live infrastructure, identity, configuration, access, hosted code, or a live
  read. It must not be recommended or started until the daily runbook is
  complete and every prerequisite for that exact narrow slice has fresh,
  sanitized current-session evidence.

If the environment is NOT READY, direct the operator to the daily runbook and
do not issue the dependent prompt. Record the gate once; avoid repeated blocked
slices and progress rewrites that merely rediscover the same absent resources.
The coordinator preserves the independent contracts: Keep infrastructure
deployment separate from prompt-agent creation. WebJob trigger/status,
managed-identity proof, metadata verification, and invocation remain separate
and explicitly authorized. Keep cleanup manual and explicit.
Never commit session identifiers, endpoints, credentials, tokens, secrets,
real contact information, or patient data.

## Prerequisites Before The Next TDD Slice

Before any hosted managed-identity metadata proof, complete
`docs/runbooks/live-hosted-foundry-agent-verification-prerequisites.md` with an
exact operator-approved inventory and fresh evidence. The repository-owned
optional five-setting Bicep/configuration path and fixed manually triggered
WebJob now exist offline. They remain unproven in App Service until separately
authorized infrastructure/configuration verification, code deployment, WebJob
discovery, readiness, and the other runbook prerequisites are freshly completed.
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
- The Web App infrastructure CLI uses `main.bicep` for initial creation and the dedicated reconciliation entry point for an existing drifted Web App; neither path creates the resource group.
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

The next step is selective staging and commit, then one authorized direct,
read-only reconciliation what-if with `--reconcile-existing-web-app`. Confirm one
exact Web App Modify plus only any exact required plan reference before a later
coordinator rerun. Claim no live reconciliation or subsequent hosted-stage
success without fresh current-session evidence; keep those stages separate.

## Current Slice Status

- An absent resource group requires current-run approval before creation. An
  existing group is reusable only with the exact location, usable state, and
  repository daily-purpose tag; otherwise the run stops for explicit manual
  adoption and a rerun.
- Foundry and Web App deployment each require approval bound to the current sanitized preview; package deployment separately binds its proof and uses a restrictive immutable handoff.
- A failed Foundry what-if remains unsafe and now retains its sanitized upstream category and failed guided-plan predicates instead of being mislabeled as an ordinary topology rejection.
- Consumer RBAC diagnostics share the topology normalizer, remain sanitized and
  fail closed, and propagate through the production repository adapter. Missing
  assignment still requires default-no approval, fresh rereads, matching preview
  and fingerprint evidence, guarded deployment, and separate verification.
- Immutable WebJob state remains generation-bound; READY still requires WebJob,
  metadata, and valid fixed-fictional invocation proofs; hosted execution remains
  offline-tested only.
- Linux WebJob hosting is current only with `alwaysOn=true` and the exact baseline Kudu-agent flag. Resource-level Modify approval combines exact identity evidence with the complete locally enforced Bicep Web App shape, an identical fresh preview, one deployment, and separate verification; deployment acceptance alone is not proof. The authoritative app-settings expression must append exactly `hostedFoundryVerifierAppSettings`; its one active top-level declaration is parsed outside comments and strings, and conditional resource bodies are selected only after balanced conditions. Decoy declarations and active relative Web App children or slots are rejected. Exact subsets of the two optional Foundry-reference Ignores are allowed, while duplicate, unrelated, or ambiguous evidence remains rejected. These final parser corrections were offline only: no corrected live policy execution, Azure or HTTP operation, WebJob discovery, trigger, status, managed-identity verification, or invocation occurred or is claimed.
- A live nested-wrapper reconciliation preview produced one Web App Deploy and
  nine unidentified Ignore records with no Modify; the coordinator rejected it
  without mutation. The wrapper is removed and reconciliation now deploys the
  authoritative Web App module directly with plan deployment disabled. No live
  direct-module preview has yet succeeded, and this slice performed no live
  reconciliation preview or deployment.

### Historical Slice Results

- A documentation guardrail first failed because the prerequisite runbook was absent, then passed after `docs/runbooks/live-foundry-agent-consumer-rbac-prerequisites.md` and the permanent runbook gate were added. Full GREEN is 1,409 passed with one existing warning.
- Direct read-only diagnostics proved the project scope. Azure then conclusively identified the failed `Microsoft.Resources/deployments` operation as a nested deployment whose name equaled the deterministic outer name, producing `DeploymentActive`.
- RED was 3 failed and 112 passed. GREEN is 115 focused tests after the verifier switched to `az cognitiveservices account project show`, projected only name/ID, accepted leaf or qualified names, validated Azure's returned ID against the approved tuple, and failed closed before assignment reads for malformed or mismatched shapes. The existing Bicep parent/leaf project declaration already matched the authoritative API and was retained.
- Nested-name RED was 1 failed/8 passed; GREEN is 116 focused RBAC tests after the entry point changed only the module deployment name to `${deployment().name}-assignment`. Bicep compiled. One corrected what-if reported create 0, modify 0, delete 0, no-change 0, ignore 10, deploy 0, unsupported 1; the sole Unsupported category remains the expected `Microsoft.Authorization/roleAssignments` resource with no unrelated change.
- After one fresh matching what-if, Azure accepted the project-scoped Foundry Agent Consumer assignment deployment. A separate read-only verifier proved exactly one direct assignment for the Web App system identity at the exact Foundry project scope. Managed-identity token acquisition, hosted Foundry metadata access, and agent invocation remain unproven. No retry, polling, manual assignment, infrastructure or code deployment, token, inference, invocation, cleanup, commit, or push occurred; nurse review and non-production boundaries remain unchanged.

## Reference Docs
- `docs/archive/progress-2026-06.md`
- `docs/runbooks/daily-disposable-azure-environment-rebuild.md`
- `docs/runbooks/live-hosted-foundry-agent-verification-prerequisites.md`
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

## Architecture Document Change Gate

`docs/architecture.md` is the authoritative, present-tense description of the current system design. It is not a chronological record of TDD slices, progress log, test-results ledger, deployment transcript, or the default destination for every implementation detail.

A future TDD slice may modify it only when a durable system-level architectural contract changes: a component boundary or responsibility; request, data, trust, control, or failure flow; provider or execution mode; persistence or external-service integration boundary; security, identity, RBAC, authorization, or secret-handling rule; deployment topology; authoritative deployment, verification, or operational boundary; or durable system-wide invariant that future contributors must understand.

A bug fix within the existing design; more unit or regression tests; a validation branch that does not alter a system boundary; exact error categories, result fields, status values, or command output; test counts or RED, GREEN, or full-suite results; temporary blockers; deployment incidents; one-time troubleshooting observations; implementation chronology; slice completion status; resume points or next-step instructions; and narrow code details already authoritative in tests or implementation do not justify an architecture update by themselves. Put those details, as appropriate, in `docs/progress.md`, focused tests, an existing runbook, source-code documentation, or commit history.

Before editing `docs/architecture.md`, a slice must:
1. Identify the exact durable architectural contract that changed.
2. Identify the existing authoritative architecture section that owns it.
3. Confirm the change cannot be represented solely through code, tests, progress documentation, or a runbook.
4. Update the existing authoritative section rather than append a slice-specific or historical section.
5. Remove or replace superseded wording.
6. Confirm the same rule is not duplicated elsewhere in the document. If no durable architectural contract changed, leave `docs/architecture.md` untouched.

When justified, describe the current system in present tense; keep the change proportional; preserve one authoritative statement per rule; consolidate nearby duplication; and omit dates, slice names, test counts, command transcripts, and completion narration. Reference runbooks instead of copying operational procedures, omit implementation trivia unless needed to explain a durable boundary, replace stale text instead of appending corrections, and preserve navigability and existing line-count guardrails.

Every substantive TDD slice completion report must contain exactly one concise declaration: `Architecture impact: none.` or `Architecture impact: updated <existing section> because <durable architectural contract changed>.` Do not accept an architecture modification whose report cannot name the changed durable contract.

Future Codex prompts must keep `docs/architecture.md` outside the default writable scope and state: Do not modify `docs/architecture.md` unless the Architecture Document Change Gate is satisfied. Put it in explicit update scope only when the planned slice is already known to alter architecture.

Perform architecture cleanup through periodic focused documentation reviews, not routine accumulation in every TDD slice. Check for duplicated rules, superseded statements, removable code-level detail, operational procedures that belong in or should reference runbooks, disagreement with the current implementation, and headings or sections that describe historical work instead of the present system.

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

- Human-reviewed repository CLI examples that emit JSON pipe through
  `python -m json.tool`, with `set -o pipefail` preserving the repository
  command's failure status. Machine-consumed or captured output, fixtures, and
  historical transcripts remain unmodified.
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
