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
- `GET /cases/{case_id}` returns a saved case.
- `GET /notifications/email` returns recorded mock email notifications in send order.

Repository support:
- `InMemoryCaseRepository` is used by the running FastAPI app.
- `CosmosCaseRepository` serializes and upserts case documents through an injected
  Cosmos-style container. It reads with `item=case_id` and
  `partition_key=case_id`, and maps configured not-found exceptions to `None`.
- `create_case_repository(settings, cosmos_container=None)` selects the in-memory
  repository for `APP_MODE=mock` and the Cosmos repository for
  `APP_MODE=cosmos`. Mode matching ignores case and surrounding whitespace.
- Cosmos mode currently requires an injected container when using
  `create_case_repository`. The repository factory is wired into the FastAPI
  dependencies for mock mode, and mock mode remains unchanged.

Cosmos container support:
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
- Repository factory fallback from `APP_MODE=cosmos` to real Cosmos container
  creation when no container is injected
- Real email provider
- SMS provider
- Authentication

Latest test result:
- 72 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

## Next Step

Use TDD to wire `create_case_repository` so `APP_MODE=cosmos` can call
`create_cosmos_container(settings)` when no injected container is supplied,
while preserving injected containers and mock mode.

## Workflow

1. Ask ChatGPT for next Codex prompt.
2. Paste prompt into Codex.
3. Run pytest.
4. Run git status.
5. Review output with ChatGPT.
6. Commit and push.
