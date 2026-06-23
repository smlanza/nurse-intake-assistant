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

Current working local pipeline:

POST /intake/text
→ CaseProcessingService
→ MockAiService
→ UrgencyRulesService
→ create_case_repository(settings)
→ InMemoryCaseRepository for `APP_MODE=mock`
→ MockEmailNotificationSender (unless suppressed)
→ CaseDocument response

Available demo/read routes:
- `GET /cases/{case_id}` returns a saved case in mock/default mode without
  requiring `createdDate`.
- `GET /cases/{case_id}?createdDate=YYYY-MM-DD` passes `createdDate` to the
  repository as `created_date`, supporting efficient Cosmos point reads when the
  client knows the case date.
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
- `CosmosCaseRepository.get_by_id(case_id, created_date=...)` supports efficient
  point reads with the `/createdDate` partition key.
- `CosmosCaseRepository` raises a clear error when `created_date` is missing for
  Cosmos lookup.
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

App settings:
- `APP_MODE` defaults to `mock`.
- `DEMO_SUPPRESS_NOTIFICATIONS` defaults to `false`.
- `COSMOS_DATABASE_NAME` defaults to `nurse-intake`.
- `COSMOS_CONTAINER_NAME` defaults to `cases`.
- `COSMOS_ENDPOINT` and `COSMOS_KEY` default to `None`.
- Cosmos environment values are trimmed; blank endpoint and key values become
  `None`.

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
- Outputs include Cosmos account name, Cosmos endpoint, database name, and
  container name.
- The template does not include secrets.

Latest test result:
- 77 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

## Next Step

Validate the Bicep baseline with Azure CLI, then plan the next infrastructure
slice for application hosting.

## Workflow

1. Ask ChatGPT for next Codex prompt.
2. Paste prompt into Codex.
3. Run pytest.
4. Run git status.
5. Review output with ChatGPT.
6. Commit and push.
