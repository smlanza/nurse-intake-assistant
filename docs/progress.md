# Nurse Intake Assistant Progress

## Current Status

Completed:
- FastAPI app skeleton
- Health route
- Pydantic models
- Red-flag urgency rules engine
- Mock AI service
- Case processing service
- Text intake API route
- In-memory case repository and shared app-level persistence
- Case retrieval route: `GET /cases/{case_id}`
- Mock email notification sender
- Optional notification suppression in `CaseProcessingService`
- App settings for app mode, notification suppression, and Cosmos DB configuration
- Email notification inspection route: `GET /notifications/email`
- Cosmos case repository using an injected Cosmos-style container
- Repository factory for selecting in-memory or Cosmos persistence by app mode
- FastAPI dependency wiring now creates the shared app-level case repository
  through `create_case_repository(settings)` in mock mode
- Cosmos container factory:
  `create_cosmos_container(settings, cosmos_client_class=None)`
- Azure Cosmos SDK dependency added to `requirements.txt`
- Repository factory now supports `APP_MODE=cosmos` without an injected
  container by calling `create_cosmos_container(settings)`
- Decision: the Cosmos cases container will use `/createdDate` as its partition
  key
- Case retrieval route accepts optional `createdDate` query parameter and passes
  it to `repository.get_by_id` as `created_date`
- Minimal Bicep infrastructure baseline in `infra/main.bicep`
- `infra/README.md` with Azure CLI build, validate, deploy, and cleanup commands
- `.env.example` documents Cosmos settings while keeping `APP_MODE=mock` as the
  safe default local mode
- `docs/manual-cosmos-smoke-test.md` documents the manual local-to-Azure Cosmos
  verification path
- Manual local-to-Azure Cosmos smoke test completed successfully
- `CosmosCaseRepository` now supports the synchronous Azure Cosmos SDK container
  methods while preserving async fake-container support in tests
- Text intake request source metadata is persisted after route-level
  `sourceSystem` and `sourceCallId` assignment
- Cosmos-backed case lookup now returns a clean HTTP 400 when `createdDate` is
  missing, rather than bubbling the repository partition-key requirement as HTTP
  500
- ACS Email provider scaffolding completed through RED then GREEN TDD stages
- `EMAIL_PROVIDER` setting defaults to `mock`
- ACS Email configuration settings were added:
  `ACS_EMAIL_CONNECTION_STRING`, `ACS_EMAIL_SENDER_ADDRESS`, and
  `NURSE_NOTIFICATION_EMAIL`
- `AcsEmailNotificationSender` placeholder exists for provider selection tests
- `create_email_notification_sender(settings)` selects mock or ACS email sender
  by provider setting, with case-insensitive and whitespace-tolerant matching
- FastAPI dependency setup now creates the shared app-level email notification
  sender through `create_email_notification_sender(settings)`
- Mock/default notification behavior remains preserved after factory wiring
- `AcsEmailNotificationSender` has minimal send behavior covered by fake-client
  tests without live Azure calls
- ACS Email payload tests verify the generated message uses the configured
  sender address and default nurse recipient, includes case id, urgency, summary,
  and patient/callback information when available, and does not include the ACS
  connection string
- `AcsEmailNotificationSender` supports both injected clients and injected
  client factories
- `AcsEmailNotificationSender` lazily creates the ACS Email client on first send
  when no client is injected
- Created ACS Email clients are reused across sends
- `create_acs_email_client(connection_string)` lazily imports the Azure
  Communication Email SDK client
- Azure Communication Email SDK dependency is listed in `requirements.txt`
- `docs/manual-acs-email-smoke-test.md` documents the manual ACS Email smoke-test
  checklist

Current working local pipeline:

POST /intake/text
→ CaseProcessingService
→ MockAiService
→ UrgencyRulesService
→ create_case_repository(settings)
→ InMemoryCaseRepository for `APP_MODE=mock`
→ create_email_notification_sender(settings)
→ MockEmailNotificationSender for `EMAIL_PROVIDER=mock` (unless suppressed)
→ CaseDocument response

Available demo/read routes:
- `GET /cases/{case_id}` returns a saved case in mock/default mode without
  requiring `createdDate`.
- `GET /cases/{case_id}?createdDate=YYYY-MM-DD` passes `createdDate` to the
  repository as `created_date`, supporting efficient Cosmos point reads when the
  client knows the case date.
- In mock/default mode, `GET /cases/{case_id}` continues to work without
  requiring `createdDate`.
- In Cosmos mode, `GET /cases/{case_id}` without `createdDate` returns HTTP 400
  with a response detail explaining that `createdDate` is required for
  Cosmos-backed case lookup.
- `GET /notifications/email` returns recorded mock email notifications in send order.

Repository support:
- `InMemoryCaseRepository` is used by the running FastAPI app.
- Case documents include a date-only `createdDate` field.
- `InMemoryCaseRepository.get_by_id(case_id, created_date=None)` accepts the
  optional `created_date` parameter for interface compatibility and ignores it.
- `CosmosCaseRepository` serializes and upserts case documents through an injected
  Cosmos-style container. It reads with `item=case_id` and
  `partition_key=createdDate` when `created_date` is supplied, and maps
  configured not-found exceptions to `None`.
- `CosmosCaseRepository` supports both synchronous Azure Cosmos SDK container
  methods and async fake container methods used by tests.
- `CosmosCaseRepository.get_by_id(case_id, created_date=...)` supports efficient
  point reads with the `/createdDate` partition key.
- `CosmosCaseRepository` raises `MissingCasePartitionKeyError` when
  `created_date` is missing for Cosmos lookup.
- `create_case_repository(settings, cosmos_container=None)` selects the in-memory
  repository for `APP_MODE=mock` and the Cosmos repository for
  `APP_MODE=cosmos`. Mode matching ignores case and surrounding whitespace.
- In Cosmos mode, `create_case_repository(settings)` calls
  `create_cosmos_container(settings)` and wraps the returned container in
  `CosmosCaseRepository`.
- Injected Cosmos containers still take precedence for tests.
- Mock mode still returns `InMemoryCaseRepository` and does not call Cosmos
  container creation.
- The repository factory is wired into the FastAPI dependencies for mock mode,
  and mock mode remains unchanged.

Cosmos container support:
- Bicep uses `/createdDate` for the Cosmos cases container partition key.
- `create_cosmos_container(settings, cosmos_client_class=None)` validates
  `COSMOS_ENDPOINT` and `COSMOS_KEY`, creates a Cosmos client, retrieves the
  configured database, and retrieves the configured container.
- Production usage lazily imports the Azure Cosmos SDK client.
- Tests can inject a fake client class to avoid real Azure access and network
  calls.
- Tests cover missing `COSMOS_ENDPOINT`, missing `COSMOS_KEY`, and valid
  client/database/container retrieval through fakes.
- Manual smoke testing verified that the local FastAPI app can use a deployed
  Cosmos DB account with `APP_MODE=cosmos`.

App settings:
- `APP_MODE` defaults to `mock`.
- `DEMO_SUPPRESS_NOTIFICATIONS` defaults to `false`.
- `EMAIL_PROVIDER` defaults to `mock`.
- `ACS_EMAIL_CONNECTION_STRING`, `ACS_EMAIL_SENDER_ADDRESS`, and
  `NURSE_NOTIFICATION_EMAIL` default to `None`.
- `COSMOS_DATABASE_NAME` defaults to `nurse-intake`.
- `COSMOS_CONTAINER_NAME` defaults to `cases`.
- `COSMOS_ENDPOINT` and `COSMOS_KEY` default to `None`.
- Cosmos environment values are trimmed; blank endpoint and key values become
  `None`.
- ACS Email environment values are trimmed; blank ACS Email values become
  `None`.

Email notification support:
- Mock email remains the default local mode.
- `MockEmailNotificationSender` remains the default notification sender.
- `create_email_notification_sender(settings)` returns
  `MockEmailNotificationSender` for `EMAIL_PROVIDER=mock`.
- `EMAIL_PROVIDER=acs` selects the ACS Email provider.
- `create_email_notification_sender(settings)` returns
  `AcsEmailNotificationSender` for `EMAIL_PROVIDER=acs` after validating the ACS
  connection string, sender address, and nurse notification email.
- Required ACS Email settings are `ACS_EMAIL_CONNECTION_STRING`,
  `ACS_EMAIL_SENDER_ADDRESS`, and `NURSE_NOTIFICATION_EMAIL`.
- Unknown `EMAIL_PROVIDER` values raise a clear configuration error.
- Mock provider mode does not require ACS Email settings.
- FastAPI dependencies create the shared app-level email sender through
  `create_email_notification_sender(settings)`.
- In mock/default mode, `GET /notifications/email` still returns recorded mock
  email notifications in send order.
- `DEMO_SUPPRESS_NOTIFICATIONS=true` still suppresses email notifications.
- `AcsEmailNotificationSender.send_case_notification(...)` can build an
  ACS-style email payload and submit it through an injected fake client in tests.
- ACS Email sender tests use an injected fake client and do not call live Azure.
- The generated ACS Email payload includes case id, urgency, summary, and
  patient/callback information when available.
- Tests verify the ACS connection string is not included in the email payload.
- `AcsEmailNotificationSender` supports injected fake clients and injected fake
  client factories for tests.
- If no client is injected, the sender lazily creates an ACS Email client on the
  first send and reuses it across subsequent sends.
- `create_acs_email_client(connection_string)` lazily imports
  `azure.communication.email.EmailClient`.
- Real ACS Email sending is not implemented yet.
- Real ACS SDK integration and live ACS Email sending are still not implemented.
- The Azure Communication Email package is listed in `requirements.txt`.
- Manual ACS Email smoke-test checklist:
  `docs/manual-acs-email-smoke-test.md`.
- No live ACS Email send has been executed yet.
- Do not commit real ACS connection strings or secrets.

Not yet implemented:
- Application hosting infrastructure
- Azure AI Foundry, Speech, ACS Email, ACS SMS, and Key Vault resources
- Real email provider
- SMS provider
- Authentication

Infrastructure support:
- `infra/main.bicep` is a resource-group-scope MVP baseline.
- It creates a serverless Azure Cosmos DB account, Cosmos SQL database, `cases`
  container using `/createdDate` as the partition key, Azure Storage account,
  Log Analytics workspace, and Application Insights.
- Parameters cover environment name, location, project name, Cosmos database
  name, and Cosmos container name.
- Outputs include Cosmos account name, Cosmos endpoint, database name, container
  name, Application Insights name, and Application Insights connection string.
- The template does not include secrets.
- `az bicep build --file infra/main.bicep` passed.
- Azure deployment group validation passed against `rg-nurse-intake-dev` in
  `eastus`.
- Actual Azure deployment succeeded.
- Verified in the Azure Portal that the resource group contained Application
  Insights, Log Analytics workspace, Azure Cosmos DB account, and Storage
  account.
- Dev resource group cleanup was planned with:
  `az group delete --name rg-nurse-intake-dev --yes`.
- Manual Cosmos smoke test deployment:
  - Resource group: `rg-nurse-intake-dev`
  - Region: `eastus`
  - Cosmos account: `nurse-intake-dev-mvtiwfmiol4pw`
  - Database: `nurse-intake`
  - Container: `cases`
  - Endpoint verified:
    `https://nurse-intake-dev-mvtiwfmiol4pw.documents.azure.com:443/`
  - No Cosmos keys or secrets were committed or documented.
- Manual smoke test safe intake:
  - Text: Jane Doe medication refill demo intake
  - Saved case id: `58053e1d-11bf-457d-8959-ee48c81b7f31`
  - Saved `createdDate`: `2026-06-24`
  - `POST /intake/text` returned HTTP 200
  - `GET /cases/{case_id}?createdDate=2026-06-24` returned HTTP 200
  - Direct Azure Cosmos SDK read confirmed the case existed in the deployed
    `cases` container
  - Follow-up TDD slice changed `GET /cases/{case_id}` without `createdDate` in
    Cosmos mode from HTTP 500 to HTTP 400 with a clear client-facing message
- Dev resource group was deleted after verification. Final check:
  `az group exists --name rg-nurse-intake-dev` returned `false`.

Latest test result:
- 108 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

## Next Step

Commit and push the ACS Email SDK dependency/checklist documentation and progress
documentation.

After that, the recommended next TDD slice is RED-stage-only tests for improving
the ACS Email sender's production error handling around SDK send failures,
without live Azure calls. The failing tests should be reviewed before
implementation.

Do not start hosting, Key Vault, Azure AI Foundry, ACS SMS, or authentication
yet.

## Workflow

1. Run pytest.
2. Run git status.
3. Review output with ChatGPT.
4. Commit and push.
5. Ask ChatGPT for the next Codex prompt.
