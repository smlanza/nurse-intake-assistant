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

Current working local pipeline:

POST /intake/text
→ CaseProcessingService
→ MockAiService
→ UrgencyRulesService
→ InMemoryCaseRepository
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
- Cosmos mode currently requires an injected container. The repository factory is
  not yet wired into the FastAPI dependencies.

App settings:
- `APP_MODE` defaults to `mock`.
- `DEMO_SUPPRESS_NOTIFICATIONS` defaults to `false`.
- `COSMOS_DATABASE_NAME` defaults to `nurse-intake`.
- `COSMOS_CONTAINER_NAME` defaults to `cases`.
- `COSMOS_ENDPOINT` and `COSMOS_KEY` default to `None`.
- Cosmos environment values are trimmed; blank endpoint and key values become
  `None`.

Not yet implemented:
- Real Azure Cosmos DB client/container creation
- Real email provider
- SMS provider
- Authentication

Latest test result:
- 67 passed
- 1 existing FastAPI/TestClient `StarletteDeprecationWarning`

## Next Step

Use TDD to wire the repository factory into FastAPI dependencies for mock mode
while preserving current behavior. Add real Cosmos container creation and
configuration as a separate later slice.

## Workflow

1. Ask ChatGPT for next Codex prompt.
2. Paste prompt into Codex.
3. Run pytest.
4. Run git status.
5. Review output with ChatGPT.
6. Commit and push.
