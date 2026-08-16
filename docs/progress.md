# Nurse Intake Assistant Progress

Active resume document; June 2026 history is in `docs/archive/progress-2026-06.md`.

## Current Status

Latest verified test baseline: 3,457 passed full suite; 1 existing FastAPI/TestClient `StarletteDeprecationWarning`.

The daily coordinator's Azure App Service convergence policy is complete
offline. A supervised run showed a matching OneDeploy operation taking about
four minutes before terminal success and the hosted application requiring
additional startup time. One required absolute ten-minute monotonic deadline
covers the complete deployment flow and is supplied to every reconciliation
path; no helper can create a new timing budget. Deployment-history reads are
bounded by the remaining time, and the deadline is checked before and after
each read. Evidence returned at or after the deadline is discarded and cannot
establish terminal success or failure. Submission-command acceptance is not
terminal deployment proof; READY requires terminal history evidence
attributable to the current command. After acceptance or safe reuse, one absolute five-minute
budget covers coordinator calls to the one-shot hosted-readiness proof, with
HTTP timeouts bounded by the remaining budget. A valid older artifact exercises
all three endpoints and may be retried, but it is never accepted until
`/version` exactly matches the current package. Malformed, unsafe, unrelated,
ambiguous, or deterministic failures remain immediate and fail-closed.

The preferred daily path is now owned exclusively by
`docs/runbooks/daily-azure-operator-runbook.md`; its command order is not
duplicated here.

`docs/runbooks/daily-azure-operator-runbook.md` is the only normal
operator-facing Azure procedure. `start` delegates to the authoritative rebuild
coordinator and includes startup cleanup preflight. `stop` delegates to the
default-no `scripts/cleanup_daily_azure_environment.py` service. Cleanup
success requires `resource_group_absent=true`, `foundry_tombstones_absent=true`, `speech_tombstones_absent=true`, `key_vault_tombstones_absent=true`, and
`daily_environment_clean=true`. A supervised approved Speech purge executed and
Azure removed the owned tombstone, but the service incorrectly classified the
successful empty-output completion as `speech_purge_failed`; an immediate
read-only inspection conclusively proved the environment clean. The offline
correction accepts command-style process success while retaining final absence proof. SSH hosted managed-identity acceptance is retired; any future hosted execution mechanism requires a separate architecture decision.

The daily-generation Key Vault runtime RBAC architecture is implemented offline. Initial application infrastructure creates the Web App and zero-secret RBAC-mode vault without the runtime role assignment. The coordinator then proves the exact current vault and Web App identity, reuses one correct direct Secrets User assignment or offers the existing evidence-bound default-no standalone Bicep deployment when conclusively absent, and independently rereads it before READY. The principal remains private and generation-bound, so identity churn cannot reuse yesterday's proof. Live daily rebuild acceptance under this changed contract is not yet proven. Consumer RBAC remains among the standalone optional workflows outside READY. WebJob evidence recovery remains exceptional, and the trigger-and-correlation path is retired and must not be reused without a new explicit architecture decision.

The standalone Azure Speech proof boundary is live-proven for one repository-owned fixed-fictional WAV through the production Speech factory, service, and Azure SDK adapter. Exactly one recognition attempt returned a valid normalized transcript matching the application-owned expected text. The proof invoked no intake route, persisted no case, attempted no notification, and mutated no Azure resource. Mock remains the safe default.

**Active implementation direction:** App Service Authentication v2 configuration is live-proven. Initial opt-in remains disabled by default. No Entra app registration occurred. The dedicated existing-parent workflow can deploy only the exact `authsettingsV2` child. Its safe preview proved one Authentication `Modify`, zero parent Web App, App Service plan, or unrelated changes, and zero deletes or unsupported actions. Explicit operator approval preceded exactly one intended Authentication mutation and attributable terminal deployment success. The bounded read-only semantic verifier then returned `authentication_configuration_verified`. It uses independently supplied, operator-local `OPERATOR_ENTRA_APPLICATION_ID` and `OPERATOR_ENTRA_TENANT_ID`; neither expected identifier is derived from Azure or committed.
The unauthenticated runtime perimeter is also live-proven. Exactly `/health`, `/version`, and `/demo/status` remained anonymously reachable, while `/demo`, `/cases`, `/docs`, and `/openapi.json` returned the required unauthenticated App Service Authentication behavior. The bounded verifier returned `authentication_perimeter_verified` without credentials, cookies, redirect following, retries, application mutation, or Azure mutation.
Interactive authenticated access remains unproven. The final acceptance boundary is implemented and reached its operator-supervised Microsoft Entra login step, but the first sign-in attempt stopped at sanitized error `AADSTS700054`: `response_type 'id_token' is not enabled for the application`. No identity, request, correlation, callback, nonce, state, credential, token, or session value is recorded. FastAPI still has no parallel authentication layer; application authorization and nurse roles/groups remain deferred.
Mock mode and no-op intake telemetry remain the safe defaults, hosted
notifications remain suppressed, and all AI output continues to require human
nurse review.

The current MVP is a local mock/demo only Nurse Intake Assistant capstone flow covering intake, mock AI extraction, urgency, nurse review, notifications, and a local demo UI.

Important constraints:
- Local mock/demo only
- No production clinical use
- No live Azure integration in the demo page
- Mock mode sends no real email or SMS
- AI output requires human nurse review
- Do not commit secrets, connection strings, real contact data, credentials, or patient data

## Current Resume Point

For Authentication, do not change FastAPI authentication logic, the Authentication verifier, the runtime-perimeter verifier, or `authsettingsV2`. Resume narrowly: (1) rebuild or verify fresh daily READY if the disposable environment no longer exists; (2) if rebuilt, re-establish current Authentication configuration and runtime-perimeter evidence for the same environment generation; (3) verify the exact existing Entra app registration through the operator-known application identity; (4) enable ID token issuance only in that application's interactive or implicit-hybrid Authentication setting, without enabling Access tokens absent a later independently proven need; (5) do not create a client secret or certificate or change redirect URIs, API permissions, tenant configuration, roles/groups, or `authsettingsV2` unless a separately diagnosed blocker requires it; (6) perform exactly one fresh operator-supervised Entra sign-in attempt and verify only fixed protected `GET /demo`; and (7) record `authenticated_application_access_verified` only if `/demo` loads after authentication. On a different sign-in error, stop on its first sanitized error and diagnose it separately without stacking configuration changes.
The application-owned Key Vault boundary includes one approved live deployment of the exact repository-owned vault. Independent control-plane verification proved the Azure-returned identity, successful provisioning, Azure RBAC mode, and no legacy access policies, but the bounded metadata-only zero-secret check failed closed as `secret_metadata_read_failed`. A dedicated fixed-role operator Key Vault Reader Bicep/verification workflow is complete offline; live preflight privately proved the current signed-in user and exact vault, then stopped without mutation at `authorization_scope_mismatch` because only wrong-scope/inherited authorization was returned. Operator Key Vault Reader remains unproven and zero-secret proof remains unknown. Exact current-generation Web App runtime RBAC orchestration and READY gating are implemented offline, but their live daily acceptance remains unproven. The application provider still defaults to local; no secret was created, retrieved, deleted, or migrated, live retrieval remains unproven, and credential migration remains deferred. Azure Speech closure is complete. Bounded OneDeploy and hosted-readiness convergence are complete offline. One required absolute deadline governs each convergence stage; submission acceptance remains separate from terminal deployment proof, and exact current-command attribution, safe hosted posture, and current-artifact equality remain mandatory. A READY receipt remains valid only while environment and configuration match; deletion or rebuild invalidates it.
`.env.speech.local` remains ignored and secret-bearing; mock remains the safe default. Consumer RBAC remains optional; WebJob discovery and immutable evidence recovery remain separate technical boundaries.

The final fresh disposable generation reached READY, including live-proven
Foundry infrastructure, prompt-agent configuration, immutable routing, Web App
configuration, current application deployment and artifact equality, and
hosted readiness. Generation handoff then succeeded, the fixed triggered
WebJob was discovered, and the direct project-scoped Consumer assignment was
reused and verified without mutation.

Multiple fresh supervised WebJob trigger attempts returned sanitized
`trigger_acceptance_ambiguous`. Azure exposed no safely correlatable execution
record for those attempts. The trigger-and-correlation implementation is now
retired from supported operations; it was not reliably provable enough for this
capstone. This decision does not claim that Azure WebJobs are universally
impossible. Operator-supervised direct App Service SSH remains non-invoking only, and compatibility mode returns `ssh_hosted_identity_execution_unsupported`. The unsupported SSH managed-identity metadata execution production path is retired. The execution-mechanism-neutral metadata verification, invocation, and combined-proof operations remain available, while hosted metadata access and invocation remain unproven. WebJob trigger/correlation remains retired, and no replacement hosted execution topology is selected. Separately, application-integrated Microsoft Foundry Agent execution and structured extraction remain live-proven.
Offline Foundry evaluation baseline v1 is implemented with eight fictional intake cases, a separate intentionally imperfect candidate fixture, strict provider-neutral contracts, deterministic exact/set metrics, and sanitized JSON output. Expected urgency labels remain `Routine` or `Urgent`; observed contract-invalid output may carry safe `Unknown` urgency under strict fallback invariants, where it scores as a mismatch without aborting evaluation. The baseline makes no Azure or network call and performs no persistence or notification work.

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
- `infra/modules/web-app.bicep`: reusable initial-create module and direct existing-Web-App reconciliation boundary with offline-tested Linux hosting, system-assigned identity, and remote build; initial Authentication opt-in invokes the single authoritative `infra/modules/web-app-authentication.bicep`, whose existing-parent boundary can deploy only `authsettingsV2`.
- `src/app/services/web_app_infra_deployment.py`: sanitized, purpose-bound initial-create and reconciliation contracts; its generic orchestrator rejects the `web_app_authentication` purpose. `scripts/deploy_web_app_infra.py` provides offline check and explicit what-if/live operation with nondefault `--reconcile-existing-web-app` selection. `scripts/accept_web_app_authentication.py` is the dedicated guarded existing-parent Authentication workflow; its narrow live what-if, terminal deployment success, and bounded semantic configuration verification are proven. Interactive sign-in remains unproven.
- `src/app/services/web_app_hosting_contract.py`: exact seven-setting contract
  plus a separate exact five-setting hosted-verifier contract shared by
  infrastructure deployment and configuration verification.
- `infra/foundry-agent-consumer-rbac.bicep`: explicit independent assignment entry point; `infra/modules/foundry-agent-consumer-rbac.bicep`: project-scoped Foundry Agent Consumer role module.
- `infra/modules/key-vault.bicep`: optional RBAC-mode vault with zero secrets; `infra/key-vault-secrets-user-rbac.bicep` and `infra/modules/key-vault-secrets-user-rbac.bicep`: independent exact-vault-scope Key Vault Secrets User assignment for the existing Web App system identity.
- `src/app/services/foundry_agent_consumer_rbac_deployment.py` and `scripts/deploy_foundry_agent_consumer_rbac.py`: offline check plus explicit what-if/live request boundary for that exact entry point.
- `src/app/services/foundry_agent_consumer_rbac_verification.py` and `scripts/verify_foundry_agent_consumer_rbac.py`: offline check plus explicit read-only assignment proof for the exact identity, role, and project scope.
- Packaged `src/app/operations/verify_hosted_foundry_agent.py`: strict system-identity metadata verification using the existing agent contract.
- Fixed packaged WebJob `App_Data/jobs/triggered/verify-hosted-foundry-agent/run.py`
  and `scripts/run_hosted_foundry_agent_verification.py`: offline check plus
  live-proven one-read discovery plus preserved but retired trigger,
  accepted-but-uncorrelatable reconciliation, and status boundaries.
- `src/app/services/hosted_foundry_agent_webjob_state_recovery.py`,
  `scripts/recover_hosted_foundry_agent_webjob_state.py`, and the dedicated
  recovery reference: separate offline manifest inspection and default-no,
  reservation-held quarantine/reinspection of immutable lifecycle evidence;
  the canonical operator runbook owns the exceptional procedure.
- Packaged `src/app/operations/invoke_hosted_foundry_agent.py`: separate strict system-identity boundary for one fixed fictional invocation and sanitized application-contract proof; check mode is offline and live remains explicit.
- `infra/foundry-only.bicep`: preferred lightweight entry point for disposable daily Foundry validation.
- `infra/foundry-only.example.bicepparam`: committed fictional example; `infra/foundry-only.bicepparam` is ignored, operator-local, and must not be committed.
- `scripts/deploy_foundry_infra.py`: approved deployment boundary; `scripts/verify_foundry_infra.py`: approved read-only verification boundary.
- `src/app/services/web_app_package.py`: deterministic source deployment package boundary; `scripts/package_web_app.py`: offline check/package CLI; `scripts/deploy_web_app_code.py`: explicit existing-Web-App deployment CLI.
- `src/app/services/web_app_readiness_verification.py`: sanitized hosted readiness contract; `scripts/verify_web_app_readiness.py`: offline check and explicit read-only live CLI.
- `src/app/services/web_app_configuration_verification.py`: Bicep-owned hosting contract verifier; `scripts/verify_web_app_configuration.py`: offline check and explicit read-only Azure CLI boundary.
- `src/app/services/web_app_authentication_verification.py` and `scripts/verify_web_app_authentication.py`: sanitized offline and bounded live Authentication v2 semantic proof; configuration verification is live-proven. `src/app/services/web_app_authentication_runtime_verification.py` and `scripts/verify_web_app_authentication_runtime.py` own the live-proven anonymous-versus-protected runtime perimeter. The final authenticated-access acceptance boundary is implemented, but interactive sign-in and authenticated protected access remain unproven.

## Daily Disposable Azure Environment Gate

Every new Azure session starts **NOT READY** until fresh current-session proof
exists. The coordinator's startup preflight determines whether the exact owned
environment is absent, conclusively healthy and reusable, or stale and eligible
for separately approved cleanup. Use the environment for development, testing,
and demonstrations, then run the explicit standalone cleanup at day's end.
End-of-day deletion remains expected; reduced readiness scope does not make the
resources permanent. The permanent procedure is
`docs/runbooks/daily-azure-operator-runbook.md`. The former
`docs/runbooks/daily-disposable-azure-environment-rebuild.md` is an
implementation index that points to the canonical procedure.

`scripts/daily_azure.sh start` is the preferred daily path for operators; it
delegates to authoritative `scripts/rebuild_daily_azure_environment.py`
`--live --json`. The wrapper's `check` runs both offline contracts, while the
detailed Python services remain implementation and audit boundaries.
Azure-dependent Codex prompts still require a fresh
current-session `daily_environment_ready=true` result. READY now requires
current startup cleanup inspection and clean-state proof, resource-group,
Foundry infrastructure, prompt-agent and immutable routing, Web App
infrastructure/configuration, application artifact deployment or safe reuse,
hosted readiness proof, and a validated Application Insights identity privately
bound to a reread schema-v5 receipt. Public output exposes only proof booleans;
legacy receipts fail closed. The coordinator does not perform Consumer RBAC, WebJob discovery or execution,
managed-identity verification, metadata access, hosted agent invocation,
end-of-day cleanup, intake processing, or notifications. Its primary fresh path
is startup preflight -> missing disposable environment -> `infra/main.bicep` ->
Foundry/agent verification -> Web App/configuration -> application deployment
-> hosted readiness -> `DAILY AZURE ENVIRONMENT READY`. A healthy verified
environment follows the existing reuse path without deletion. Same-day unsafe
or ambiguous Web App drift remains fail-closed.

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
deployment separate from prompt-agent creation. Consumer RBAC remains optional,
standalone, separate, and explicitly authorized. The current WebJob
trigger/status path is retired. Managed-identity proof, metadata verification,
and invocation remain unproven. Keep cleanup separately approved and
ownership-scoped, and complete the expected standalone end-of-day cleanup after
the workday.
Never commit session identifiers, endpoints, credentials, tokens, secrets,
real contact information, or patient data.

## Prerequisites Before The Next TDD Slice

Begin Azure-dependent work with the canonical daily runbook and fresh READY
proof. The old
`docs/runbooks/live-hosted-foundry-agent-verification-prerequisites.md` is now
an implementation reference for the retired WebJob path, not a prerequisite
sequence. Direct SSH remains only a proven non-invoking transport boundary;
its managed-identity execution mode is unsupported, and no replacement hosted execution topology is selected.

Do not claim as complete:
- Hosted managed-identity Agent execution remains unproven; the supervised
  application-integrated Foundry Agent path is separately live-proven.
- No live Azure behavior is claimed for `/demo` by default;
  `AGENT_PROVIDER=mock` remains the safe local/demo default, and human nurse
  review remains mandatory.
- Route-integrated audio ingestion, audio processing, and voice automation; the standalone fixed-fictional Azure Speech proof is separately live-proven
- Managed-identity token acquisition, hosted Foundry metadata access, and invocation remain unproven live despite separately proven RBAC deployment and direct assignment
- ACS phone intake/call automation, live Key Vault deployment, RBAC verification, and access,
  migration of current credentials, successful interactive App Service sign-in
  and authenticated application access,
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
- `TELEMETRY_PROVIDER=none`

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
  imports/client construction and obtains its inference client through `AIProjectClient.get_openai_client()`. Both the standalone manual smoke and the production-composed application-integrated path are live-proven.
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
- `SPEECH_PROVIDER=mock` uses an offline transcription boundary for already-transcribed text.
- `SPEECH_PROVIDER=azure` selects the lazy SDK adapter. Its standalone proof CLI is live-proven for the fixed-fictional fixture only and requires an ignored, secret-bearing local Speech configuration file.
- Mock email remains the default local mode.
- `EMAIL_PROVIDER=acs` selects ACS Email and requires
  `ACS_EMAIL_CONNECTION_STRING`, `ACS_EMAIL_SENDER_ADDRESS`, and
  `NURSE_NOTIFICATION_EMAIL`.
- `SMS_PROVIDER=mock` records mock SMS notifications in memory.
- `SMS_PROVIDER=acs` selects ACS SMS and requires
  `ACS_SMS_CONNECTION_STRING`, `ACS_SMS_FROM_PHONE_NUMBER`, and
  `NURSE_NOTIFICATION_PHONE_NUMBER`.
- `TELEMETRY_PROVIDER=none` selects the inert sink; `azure-monitor` selects a
  lazy adapter. The standalone proof is offline-ready; one live attempt stopped before adapter construction.

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
- Offline Speech boundary, mock provider, lazy Azure SDK adapter, provider factory, owned fictional WAV, sanitized fixed-proof CLI, offline check, and one supervised live acceptance
- Deterministic urgency rules with negation-aware red-flag handling
- Structured missing-field validation, intake completion status, and follow-up
  prioritization
- Human-in-the-loop nurse review with persisted review metadata
- Mock repository support plus Cosmos repository/container factory support
- Email/SMS notification provider scaffolding, fake-client tests, ACS Email
  smoke-test documentation, and ACS SMS SDK/send-request boundary
- Notification status semantics and queue summary notification counts
- Typed intake telemetry plus a production-composed, fixed-fictional, bounded read-only ingestion proof
- Mock queue filtering, ordering, summary, and pagination
- Deterministic copy-friendly nurse handoff notes for saved cases
- Demo seed/reset endpoints and local demo UI with handoff note display
- Voicemail transcript intake with optional recording metadata and mock-mode
  idempotency
- Swagger/OpenAPI examples for text and voicemail transcript intake
- Swagger/OpenAPI metadata and safe example for the handoff note route
- README local mock demo walkthrough and manual demo/smoke-test docs
- Minimal Bicep infrastructure baseline and manual Cosmos smoke test
- Optional offline Key Vault exact-name secret-access boundary plus optional RBAC-mode infrastructure and a separate exact-vault-scope Key Vault Secrets User assignment contract
- No Azure calls in tests, PHI, production clinical behavior, hosted authentication, live Key Vault deployment/RBAC verification/retrieval or credential migration, phone intake automation, retry/durable processing, or frontend work were added.

## Infrastructure Summary

- `infra/main.bicep` is a resource-group-scope MVP baseline.
- It provisions Cosmos DB, a Cosmos SQL database, a `cases` container using
  `/createdDate`, a storage account, Log Analytics, and Application Insights.
- It can optionally provision a Linux App Service plan and Web App with a system-assigned identity and remote-build setting; `deployApp=false` preserves the existing default.
- It can optionally provision a deterministic repository-owned Azure RBAC-mode Key Vault with zero secrets; `deployKeyVault=false` preserves the existing default.
- A separate template can explicitly assign Foundry Agent Consumer at project scope without coupling access to `main.bicep`.
- A separate template can assign only Key Vault Secrets User to the existing Web App system identity at exact vault scope without coupling authorization to ordinary vault creation.
- The allowlisted package builder and explicit deployment CLI keep code upload
  separate from infrastructure, RBAC, startup checks, and Foundry operations.
- The Web App infrastructure CLI uses `main.bicep` for initial creation and the dedicated reconciliation entry point for an existing drifted Web App; neither path creates the resource group.
- `infra/README.md` documents Azure CLI build, validate, deploy, and cleanup commands.
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

- Successful Microsoft Entra interactive sign-in and authenticated protected application access; application authorization and nurse/application roles or groups
- Agent-specific RBAC scope
- Live hosted managed-identity verification and agent invocation
- Live Key Vault deployment, exact RBAC verification, live retrieval, current-credential migration, App Service references, and production secret rotation/operations
- Route-integrated audio ingestion, voice automation, streaming, retention, and generalized or production clinical audio workflows
- ACS SMS delivery tracking
- Application-level durable retry processing
- Production frontend
- Production clinical UI or autonomous medical decision-making

## Recommended Next Slice

The packaged synchronous hosted proof operation remains execution-mechanism-neutral, direct App Service SSH transport is live-proven and non-invoking only, SSH hosted managed-identity execution is unsupported, and no replacement hosted execution topology is selected. The next Authentication step is the narrow Entra correction described in the Current Resume Point: with fresh current-generation evidence, enable ID token issuance only for the exact existing application registration, then perform one fresh operator-supervised sign-in and verify only protected `GET /demo`. Do not change `authsettingsV2`, FastAPI authentication, redirect URIs, API permissions, tenant configuration, credentials, roles, or groups as part of that correction. Authorization remains deferred.

## Current Slice Status

- A fresh supervised daily run accepted an exact nine-create Web App/zero-secret-vault preview, then the named resource-group deployment reached terminal `Failed`: eight expected resources succeeded, while the exact vault create returned Azure `ConflictError` because one matching soft-deleted vault tombstone retained the deterministic name. The coordinator correctly reported mutation as unknown from the nonzero synchronous CLI result because command exit alone cannot distinguish pre-submission failure from partial creation; the bounded deployment record now proves mutation occurred. A genuine RED showed canonical cleanup ignored the blocker. The existing default-no cleanup workflow now binds only the exact subscription, original resource-group ARM ID, location, type, deterministic name, and unambiguous vault multiplicity; it carries active identity across group deletion, purges only the approved tombstone, and independently proves absence before startup can continue. Verification passed 707 focused regressions and the 3,488-test full suite. Diagnosis used read-only Azure calls and made no mutation; no secret was created, read, or migrated. The current partial generation requires canonical supervised `scripts/daily_azure.sh stop`, followed only after verified clean output by a fresh `scripts/daily_azure.sh start`; live acceptance remains unproven.
- The standalone Application Insights smoke is offline-tested to use production
  composition, in-memory persistence, suppressed notifications, one emission,
  and bounded read-only verification. Two separately authorized supervised runs each used fresh private schema-v5 READY, production-composed one fixed-fictional in-memory intake, suppressed both notification paths, completed one adapter emission call, and made no Azure mutation; both bounded queries rejected an in-window expected-name row as `telemetry_record_invalid`, including the second run after strict string encoding/decoding correction. A sanitized offline diagnostic classifier now identifies only an allowlisted field, fixed mismatch reason, and fixed wire type without relaxing verification or exposing values. No exact failed-attempt window was persisted, so a live diagnostic query is unavailable without guessing or broadening. Live and App Service-hosted telemetry remain unproven; this is neither clinical validation nor production monitoring.
- Direct App Service SSH transport is live-proven. Fresh matching READY evidence preceded one supervised acceptance that started exactly one tunnel and proved readiness; both fixed `APP_PATH` probes passed, and the packaged non-invoking check passed. No managed-identity metadata verification or Agent invocation occurred. Interrupt and private host-key cleanup completed, the process was reaped, and sanitized inspection found no matching tunnel process. No retry or alternate transport occurred.
- `src/app/services/hosted_foundry_agent_proof.py` composes the existing hosted metadata verifier and fixed-fictional invocation boundary in one exact-type, exact-boolean, fail-closed sequence. The packaged metadata, invocation, and combined-proof operations remain available as execution-mechanism-neutral boundaries without selecting a hosted topology. Their offline checks remain deterministic and sanitized.
- `HostedFoundryAgentSshTransport` preserves the live-proven one-tunnel lifecycle, authoritative loopback readiness proof, two fixed `APP_PATH` probes, packaged non-invoking check, private output and host-key handling, and guaranteed interrupt/terminate/kill reaping. `--live-tunnel` remains the only supported live SSH mode. `--live-metadata-verification` now returns `ssh_hosted_identity_execution_unsupported` deterministically before configuration proof, approval, service, tunnel, probe, remote-command, credential, metadata, or Agent activity.
- The first supervised SSH metadata attempt returned `missing_configuration`; private propagation of the exact five preverified settings corrected that boundary. The next attempt returned `not_running_in_hosted_environment`, proving the SSH process lacks the App Service application-worker identity environment. Managed identity was never attempted. Runtime identity markers remain App Service-owned and are never forwarded. SSH managed-identity execution is retired, hosted metadata access and invocation remain unproven, no replacement mechanism was selected, and the repository is at a clean architectural decision point.
Architecture impact: updated the existing hosted Foundry SSH execution section because direct SSH managed-identity execution is now unsupported and no replacement hosted execution topology is selected.
- The blocked application-output adapter slice exposed a canonical representation mismatch: invalid Agent fallback output could safely contain `Unknown`, while the candidate contract required a fabricated binary urgency. The canonical evaluator now keeps expected advisory, final, and deterministic-rule labels binary while allowing only application-consistent `Unknown` urgency states on contract-invalid observed candidates. `Unknown` remains an ordinary advisory/final mismatch; deterministic-rule agreement and mandatory nurse review remain scoreable. No adapter was implemented in this correction.
- Final fresh live proof reached READY with Foundry infrastructure,
  prompt-agent configuration, immutable routing, Web App configuration,
  application deployment, artifact equality, and hosted readiness verified.
- Consumer RBAC reuse succeeded with `assignment_reused=true`,
  `assignment_verified=true`, and `azure_mutation_made=false`.
- Multiple fresh supervised trigger attempts returned `trigger_acceptance_ambiguous`;
  Azure exposed no safely correlatable execution record.
- The current WebJob trigger-and-correlation implementation is retired from
  supported operations. Its trigger, reconciliation, and status CLI modes
  remain code history and require a future explicit architecture decision
  before reuse.
- `compose_application(settings)` is now the shared production composition boundary used by both the normal intake route and `scripts/smoke_application_foundry_extraction.py`; the smoke no longer owns a parallel service composition root. Its controlled non-echoing parser, centralized sanitized exception boundary, and repeated authoritative-readiness check remain in place. The first supervised application-integrated invocation reached the provider but returned sanitized `authentication_failed`; no case was persisted, no notification was attempted, and no Azure mutation occurred.
- Independent credential probes succeeded, strongly indicating that the failure was the incorrect Foundry project-endpoint client path rather than a missing Azure login. The final supervised application-integrated structured-extraction smoke succeeded with fixed fictional data: production application composition verified `AI_PROVIDER=foundry`; the corrected lazy `AIProjectClient.get_openai_client()` path invoked Foundry; the output contract was valid; no fallback occurred; deterministic rules were evaluated without needing to promote urgency; exactly one case was persisted only in memory; notifications were suppressed and not attempted; nurse review remained mandatory; and no Azure mutation was attempted. This production-composed structured-extraction path and the separate application-integrated Agent path are now live-proven; hosted managed-identity execution remains unproven, and WebJob invocation remains retired.
- `docs/runbooks/daily-azure-operator-runbook.md` now consolidates the only
  normal operator sequence, optional RBAC, end-of-day cleanup, and exceptional
  immutable-evidence recovery.
- Historical Web App reconciliation rejected one Web App Deploy and nine unidentified Ignore records; the wrapper is removed,
  `--reconcile-existing-web-app` remains standalone, no live direct-module preview has yet succeeded, and no live reconciliation preview or deployment occurred.
  Resume Nurse Intake Assistant application and AI-103 feature development only through a separately frozen slice.

### Historical Slice Results

- A documentation guardrail first failed because the prerequisite runbook was absent, then passed after `docs/runbooks/live-foundry-agent-consumer-rbac-prerequisites.md` and the permanent runbook gate were added. Full GREEN is 1,409 passed with one existing warning.
- Direct read-only diagnostics proved the project scope. Azure then conclusively identified the failed `Microsoft.Resources/deployments` operation as a nested deployment whose name equaled the deterministic outer name, producing `DeploymentActive`.
- RED was 3 failed and 112 passed. GREEN is 115 focused tests after the verifier switched to `az cognitiveservices account project show`, projected only name/ID, accepted leaf or qualified names, validated Azure's returned ID against the approved tuple, and failed closed before assignment reads for malformed or mismatched shapes. The existing Bicep parent/leaf project declaration already matched the authoritative API and was retained.
- Nested-name RED was 1 failed/8 passed; GREEN is 116 focused RBAC tests after the entry point changed only the module deployment name to `${deployment().name}-assignment`. Bicep compiled. One corrected what-if reported create 0, modify 0, delete 0, no-change 0, ignore 10, deploy 0, unsupported 1; the sole Unsupported category remains the expected `Microsoft.Authorization/roleAssignments` resource with no unrelated change.
- After one fresh matching what-if, Azure accepted the project-scoped Foundry Agent Consumer assignment deployment. A separate read-only verifier proved exactly one direct assignment for the Web App system identity at the exact Foundry project scope. Managed-identity token acquisition, hosted Foundry metadata access, and agent invocation remain unproven. No retry, polling, manual assignment, infrastructure or code deployment, token, inference, invocation, cleanup, commit, or push occurred; nurse review and non-production boundaries remain unchanged.

## Reference Docs
- `docs/archive/progress-2026-06.md`
- `docs/runbooks/daily-azure-operator-runbook.md`
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

## TDD Slice Scope And Review Gate

Before implementation, freeze objective, acceptance criteria, allowed files, prohibited work, and required verification. Before adding tests, prove that the required behavior is not already adequately covered.
Builder and reviewer use frozen criteria; review must not add features, optional hardening, speculative failure modes, unrelated refactoring, or broader architecture requirements.

```text
freeze slice -> builder RED to GREEN -> focused and full verification
-> one independent review -> one blocking-finding correction pass -> commit
```
A final review is permitted only when the correction changes a security-critical, authorization, destructive-deployment, concurrency, or persistent-state boundary.

A finding blocks only for a concrete failure against frozen acceptance criteria,
an existing repository contract, authorization or data safety, a reproducible
correctness defect, or a required operator workflow. It must identify the exact
location, concrete failure path, and smallest correction.

Do not block for optional refactoring, naming or style, additional abstractions,
theoretical hardening, unsupported environments, unrequired test permutations,
or future operations. Record useful nonblocking concerns as future-slice candidates.

Stop and split when a correction adds responsibility, materially expands frozen criteria, requires unrelated production changes, or substantially grows the surface.

A slice is ready to commit when:

```text
frozen acceptance criteria satisfied
- no concrete Critical or High defect remains; required focused tests pass
- full suite passes; documentation matches implementation
- git diff --check passes
```
Passing this gate ends the slice; further improvements belong in a later slice.

## Testing Guidance

- For docs-only work, prefer a few semantic guardrails over brittle exact-prose tests; human-reviewed JSON CLI examples use `set -o pipefail` and `python -m json.tool`.
- Before adding a test, inspect focused tests for the same behavior, contract, failure mode, or boundary; do not add one when existing coverage already adequately protects the acceptance criterion. Prefer extending, parameterizing, consolidating, or replacing an existing test when that provides the required coverage without materially reducing clarity. Every new test must protect a distinct required behavior, regression risk, security or safety invariant, contract boundary, or previously uncovered failure path.
- Avoid tests that prove the same behavior through trivial input variations unless those variations represent materially different contracts or risks. Test count is not a success metric; fewer well-targeted tests are preferable to redundant coverage. During slice completion and review, check new tests against existing coverage and remove or consolidate unnecessary overlap before commit. Consolidate only nearby overlap exposed by the current work; broader test-suite cleanup requires a separately frozen maintenance slice.
