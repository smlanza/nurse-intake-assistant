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
- 2026-06-24: Manual ACS Email smoke test completed successfully with the local
  app running in `APP_MODE=mock`, `EMAIL_PROVIDER=acs`, and
  `DEMO_SUPPRESS_NOTIFICATIONS=false`
- ACS sender domain configuration issue was resolved by matching the
  portal-generated sender domain exactly
- `AcsEmailNotificationSender.send_case_notification(...)` returns `True` after
  the ACS client accepts the send
- `CaseProcessingService` applies the email sender result to the returned
  `CaseDocument`, so successful sends are reflected as
  `notificationEmailSent=true`
- ACS Email production failure handling is complete: client creation failures,
  send submission failures, and poller/result failures return `False` instead
  of raising
- `CaseProcessingService` still saves and returns cases when email sending
  fails, leaving `notificationEmailSent=false`
- SMS provider scaffolding is complete
- `SMS_PROVIDER` setting defaults to `mock`
- ACS SMS configuration settings were added:
  `ACS_SMS_CONNECTION_STRING`, `ACS_SMS_FROM_PHONE_NUMBER`, and
  `NURSE_NOTIFICATION_PHONE_NUMBER`
- `MockSmsNotificationSender` and `AcsSmsNotificationSender` placeholders exist
  for provider selection tests
- `create_sms_notification_sender(settings)` selects mock or ACS SMS sender by
  provider setting, with case-insensitive and whitespace-tolerant matching
- Mock SMS mode does not require ACS SMS settings
- Mock SMS notification wiring into intake processing is complete
- `CaseProcessingService` accepts an optional SMS notification sender dependency
- FastAPI dependency setup now creates the shared app-level SMS notification
  sender through `create_sms_notification_sender(settings)`
- Default mock-mode text intake returns `notificationSmsSent=true` when
  notifications are not suppressed
- ACS SMS fake-client send behavior is complete without live Azure calls
- `AcsSmsNotificationSender` supports injected fake clients and injected fake
  client factories
- `AcsSmsNotificationSender` lazily creates the ACS SMS client on first send
  when no client is injected
- Created ACS SMS clients are reused across sends
- `create_acs_sms_client(connection_string)` exists as a placeholder factory
  function without importing the Azure SMS SDK
- ACS SMS production failure handling is complete: client creation failures,
  send submission failures, and send result/status failures return `False`
  instead of raising
- `CaseProcessingService` catches SMS sender exceptions so failed SMS sends do
  not prevent cases from being saved or returned
- SMS failure does not change successful email notification behavior
- Mock SMS notification inspection route is complete:
  `GET /notifications/sms`
- Local mock demo guide is complete:
  `docs/manual-local-mock-demo.md`
- `.env.example` SMS documentation alignment is complete
- Manual ACS SMS smoke-test guide placeholder is complete:
  `docs/manual-acs-sms-smoke-test.md`
- ACS SMS client factory scaffold is complete
- Azure Communication Services SMS SDK dependency alignment is complete
- ACS SMS implementation is code-complete enough to reach the ACS SMS SDK/send
  request path
- 2026-06-25: Live ACS SMS smoke attempt reached the app/provider send path, but
  handset delivery was not confirmed because toll-free SMS verification is still
  pending in the external Azure/carrier regulatory workflow

Current working local pipeline:

POST /intake/text
→ CaseProcessingService
→ MockAiService
→ UrgencyRulesService
→ create_case_repository(settings)
→ InMemoryCaseRepository for `APP_MODE=mock`
→ create_email_notification_sender(settings)
→ MockEmailNotificationSender for `EMAIL_PROVIDER=mock` (unless suppressed)
→ create_sms_notification_sender(settings)
→ MockSmsNotificationSender for `SMS_PROVIDER=mock` (unless suppressed)
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
- `GET /notifications/sms` returns recorded mock SMS notifications in send
  order for local/demo inspection.
- `docs/manual-local-mock-demo.md` documents the local mock demo flow:
  start the app with `uvicorn`, submit `POST /intake/text`, verify
  `GET /cases/{case_id}`, inspect `GET /notifications/email`, and inspect
  `GET /notifications/sms`.
- `docs/manual-acs-sms-smoke-test.md` documents a future live ACS SMS
  smoke-test checklist, including a planned `uvicorn` run step and planned
  `POST /intake/text` verification.

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
- `SMS_PROVIDER` defaults to `mock`.
- `ACS_SMS_CONNECTION_STRING`, `ACS_SMS_FROM_PHONE_NUMBER`, and
  `NURSE_NOTIFICATION_PHONE_NUMBER` default to `None`.
- `COSMOS_DATABASE_NAME` defaults to `nurse-intake`.
- `COSMOS_CONTAINER_NAME` defaults to `cases`.
- `COSMOS_ENDPOINT` and `COSMOS_KEY` default to `None`.
- Cosmos environment values are trimmed; blank endpoint and key values become
  `None`.
- ACS Email environment values are trimmed; blank ACS Email values become
  `None`.
- ACS SMS environment values are trimmed; blank ACS SMS values become `None`.
- The local mock demo guide documents safe default values:
  `APP_MODE=mock`, `EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock`, and
  `DEMO_SUPPRESS_NOTIFICATIONS=false`.
- `.env.example` documents `SMS_PROVIDER=mock` as the safe local default.
- `.env.example` documents empty ACS SMS placeholders:
  `ACS_SMS_CONNECTION_STRING`, `ACS_SMS_FROM_PHONE_NUMBER`, and
  `NURSE_NOTIFICATION_PHONE_NUMBER`.
- `.env.example` preserves existing email and Cosmos sample settings while
  keeping `APP_MODE=mock` as the safe default.
- `docs/manual-acs-sms-smoke-test.md` documents future ACS SMS settings:
  `SMS_PROVIDER=acs`, `ACS_SMS_CONNECTION_STRING`,
  `ACS_SMS_FROM_PHONE_NUMBER`, `NURSE_NOTIFICATION_PHONE_NUMBER`, and
  `DEMO_SUPPRESS_NOTIFICATIONS=false`.

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
- In mock/default mode, `GET /notifications/sms` returns HTTP 200 with recorded
  mock SMS notifications in send order.
- `DEMO_SUPPRESS_NOTIFICATIONS=true` still suppresses email notifications.
- `DEMO_SUPPRESS_NOTIFICATIONS=true` also suppresses SMS notifications.
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
- `AcsEmailNotificationSender.send_case_notification(...)` returns `True` when
  the ACS client accepts the send.
- `AcsEmailNotificationSender.send_case_notification(...)` returns `False`
  instead of raising when ACS client creation, send submission, or poller/result
  handling fails.
- `CaseProcessingService` sets `notificationEmailSent=true` on the returned case
  when the email sender reports a successful send.
- `CaseProcessingService` leaves `notificationEmailSent=false` while still
  saving and returning the case when the email sender reports a failed send.
- Live ACS Email smoke testing is complete.
- The Azure Communication Email package is listed in `requirements.txt`.
- Manual ACS Email smoke-test checklist:
  `docs/manual-acs-email-smoke-test.md`.
- Manual smoke test result from 2026-06-24:
  - `POST /intake/text` returned HTTP 200
  - Response included `notificationEmailSent=true`
  - Response included `notificationSmsSent=false`
  - Response included `sourceSystem=manual-acs-smoke-test`
  - Response included `sourceCallId=acs-smoke-012`
  - A real email notification was received
  - `notificationSmsSent=false` is expected because SMS remains unimplemented
- Do not commit real ACS connection strings or secrets.

SMS notification support:
- Mock SMS is the default local mode.
- `MockSmsNotificationSender` records sent SMS notifications in memory for safe
  local/mock mode.
- `AcsSmsNotificationSender` can build an ACS-style SMS payload and submit it
  through an injected fake client in tests.
- `create_sms_notification_sender(settings)` returns
  `MockSmsNotificationSender` for `SMS_PROVIDER=mock`.
- `SMS_PROVIDER=acs` selects the ACS SMS provider.
- `create_sms_notification_sender(settings)` returns
  `AcsSmsNotificationSender` for `SMS_PROVIDER=acs` after validating the ACS SMS
  connection string, sender phone number, and nurse notification phone number.
- Required ACS SMS settings are `ACS_SMS_CONNECTION_STRING`,
  `ACS_SMS_FROM_PHONE_NUMBER`, and `NURSE_NOTIFICATION_PHONE_NUMBER`.
- Unknown `SMS_PROVIDER` values raise a clear configuration error.
- Mock SMS provider mode does not require ACS SMS settings.
- FastAPI dependencies create the shared app-level SMS sender through
  `create_sms_notification_sender(settings)`.
- `CaseProcessingService` accepts an optional `sms_notification_sender`
  dependency.
- `CaseProcessingService` attempts SMS notification when notifications are not
  suppressed.
- `CaseProcessingService` sets `notificationSmsSent=true` on the returned case
  when the SMS sender reports a successful send.
- `CaseProcessingService` leaves `notificationSmsSent=false` when the SMS sender
  reports a failed send.
- SMS failure does not prevent the case from being saved or returned.
- `CaseProcessingService` catches SMS sender exceptions and leaves
  `notificationSmsSent=false`.
- SMS sender exceptions do not change successful email notification behavior.
- In default mock mode, `POST /intake/text` returns `notificationSmsSent=true`
  when notifications are not suppressed.
- ACS SMS sender tests use injected fake clients and do not call live Azure.
- The generated ACS SMS message includes case id and body/summary text.
- Tests verify the ACS SMS connection string is not included in the SMS payload.
- `AcsSmsNotificationSender` supports injected fake clients and injected fake
  client factories for tests.
- If no client is injected, the sender lazily creates an ACS SMS client on the
  first send using the injected factory and reuses it across subsequent sends.
- `create_acs_sms_client(connection_string)` exists as a placeholder factory
  function and does not import the Azure SMS SDK yet.
- `AcsSmsNotificationSender.send_case_notification(...)` returns `False`
  instead of raising when SMS client creation, send submission, or send
  result/status handling fails.
- `GET /notifications/sms` returns recorded mock SMS notifications for
  local/demo inspection.
- SMS notification inspection responses include recipient, body, and `case_id`.
- Tests verify `GET /notifications/sms` does not expose ACS connection strings
  or secrets.
- `docs/manual-local-mock-demo.md` documents expected mock demo behavior:
  `notificationEmailSent=true` and `notificationSmsSent=true`.
- The local mock demo guide notes that mock mode sends no real email or SMS.
- The local mock demo guide notes not to commit secrets, connection strings, or
  real phone numbers.
- The local mock demo guide notes that live ACS SMS is not implemented yet.
- `.env.example` does not include real phone numbers, real ACS connection
  strings, or access keys.
- `docs/manual-acs-sms-smoke-test.md` documents expected future behavior:
  `notificationSmsSent=true` after successful live ACS SMS send, with
  `notificationEmailSent` remaining independent.
- The ACS SMS smoke-test guide documents failure handling expectations: ACS SMS
  send failure should not crash intake processing, and failed SMS should leave
  `notificationSmsSent=false`.
- The ACS SMS smoke-test guide notes current limitations: no Azure SMS SDK
  dependency has been added, `create_acs_sms_client` is still a placeholder
  factory boundary, and live ACS SMS smoke testing has not been completed.
- The ACS SMS smoke-test guide warns not to commit secrets, connection strings,
  access keys, or real phone numbers.
- `create_acs_sms_client(connection_string)` lazily imports
  `azure.communication.sms.SmsClient`.
- `create_acs_sms_client(connection_string)` calls
  `SmsClient.from_connection_string(connection_string)` and returns the created
  SMS client instance.
- Mock/default app startup does not require the Azure SMS SDK unless ACS SMS
  client creation is requested.
- If the Azure SMS SDK package is missing, `create_acs_sms_client` raises a
  clear `RuntimeError` mentioning `azure-communication-sms` and
  `SMS_PROVIDER=acs` without exposing the ACS SMS connection string, endpoint,
  access key, or secrets.
- The Azure Communication Services SMS package
  `azure-communication-sms` is listed in `requirements.txt`.
- Existing requirements entries remain preserved, including `fastapi`,
  `uvicorn[standard]`, `pytest`, `httpx`, `azure-communication-email`, and
  `azure-cosmos`.
- Local ACS SMS smoke attempt details:
  - The app was run locally with `APP_MODE=mock`, `SMS_PROVIDER=acs`, and
    `DEMO_SUPPRESS_NOTIFICATIONS=false`.
  - `POST /intake/text` returned HTTP 200.
  - The response showed `notificationSmsSent=true`.
  - Handset SMS delivery was not confirmed.
- ACS SMS delivery blocker:
  - The initial ACS free trial number showed SMS unavailable, so it cannot be
    used for SMS delivery.
  - A paid ACS toll-free number was acquired.
  - Azure Portal showed U.S./Canada toll-free SMS verification is mandatory.
  - Regulatory document submission was attempted, but Azure Portal returned
    "Server not responding / Unable to access regulatory documents right now."
  - Live handset delivery is pending toll-free verification and external
    Azure/carrier regulatory workflow completion.
- MVP decision: do not block the project on toll-free verification. Mock SMS
  inspection remains the primary demo path for SMS.
- ACS SMS is documented as integrated at the SDK/send-request level, with
  handset delivery pending external verification.
- Live ACS SMS handset delivery has not been confirmed yet.
- Do not commit real ACS SMS connection strings, secrets, or phone numbers.

Known issues and future enhancements:
- `notificationSmsSent=true` currently means the application/provider send path
  accepted or completed without raising; it does not prove carrier delivery to a
  handset. Future enhancement: capture ACS message id/status or delivery report
  semantics.
- Current red-flag rules are keyword-based and not negation-aware. For example,
  text containing "No chest pain" can still trigger urgent classification.
  Future enhancement: add negation-aware red-flag detection.

Not yet implemented:
- Application hosting infrastructure
- Azure AI Foundry, Speech, ACS Email, ACS SMS, and Key Vault resources
- Confirmed live ACS SMS handset delivery
- ACS SMS delivery report/status tracking
- Negation-aware red-flag detection
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
- 158 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

## Next Step

Reset local `.env` back to safe mock defaults after live ACS Email testing, then
commit and push the ACS Email tracking changes.

ACS Email production failure handling, SMS provider scaffolding, mock SMS wiring
into intake processing, ACS SMS fake-client behavior, and ACS SMS production
failure handling, mock SMS notification inspection, and the local mock demo
guide, `.env.example` SMS documentation alignment, and the manual ACS SMS
smoke-test guide placeholder, the ACS SMS client factory scaffold, and ACS SMS
SDK dependency alignment are complete. ACS SMS reached the SDK/send-request path,
but handset delivery remains pending toll-free verification. Review and commit
the current documentation/code/test changes before selecting the next TDD slice.

Do not start live ACS SMS sending, hosting, Key Vault, Azure AI Foundry, voice
intake, retry logic, or authentication yet.

## Workflow

1. Run pytest.
2. Run git status.
3. Review output with ChatGPT.
4. Commit and push.
5. Ask ChatGPT for the next Codex prompt.
