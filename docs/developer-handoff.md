# Nurse Intake Assistant - Phase 1 Developer Handoff

## 1. Build Goal

Build a single FastAPI application that supports Phase 1 nurse intake processing:

```text
ACS phone recording or protected demo input
→ transcription if audio
→ AI extraction and summarization
→ rules + AI advisory urgency classification
→ Cosmos DB case document
→ nurse notification
→ protected dashboard review
```

The implementation should prioritize demoability, cost control, and clear Azure AI-103 alignment over enterprise-scale architecture.

## Current Integration Status

- Mock demo is the primary interview/demo path. `APP_MODE=mock`,
  `AI_PROVIDER=mock`, `SPEECH_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, and
  `SMS_PROVIDER=mock` remain the safe defaults.
- Live Azure OpenAI / Foundry structured extraction has a manual smoke script:
  `scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live --diagnose --live-client-mode azure-openai-endpoint`.
- The validated live path uses `AZURE_OPENAI_ENDPOINT`, normalizes internally to
  the Azure OpenAI `/openai/v1/` path, uses Entra bearer-token provider auth,
  and passes `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME` as the model parameter.
- Foundry/Azure OpenAI live extraction is not wired into the default demo; the
  app remains mock-first unless explicit manual provider settings are used.
- Prompt-agent configuration is reproducible from the centralized instructions
  through `scripts/deploy_foundry_agent.py`. Its `--check` mode is offline;
  explicit `--live --json` uses `azure-ai-projects` 2.x
  `PromptAgentDefinition`, `agents.create_version()`, and the project Responses
  API agent reference to create and validate one new version with fictional data.
  It is never called during app startup or intake, and live acceptance remains manual.
- Azure Speech remains scaffolded with offline/manual preflight only; no live
  audio transcription or phone intake is part of the default demo.
- ACS Email/SMS have provider scaffolds and offline-safe preflight/manual smoke
  guidance; do not overstate delivery guarantees.
- Cosmos has repository seams and manual point-read style smoke guidance; the
  default local demo remains in-memory.
- Production hosting, authentication, security hardening, compliance, Key
  Vault, retry/durable processing, Agents, MCP/A2A, and clinical production use
  are out of scope for this MVP.
- For interview/demo preparation, use `docs/demo-readiness-checklist.md`.

## 2. Implementation Sequence

Use a backend-first build order.

```text
1. Define Pydantic models and case document schema
2. Implement red-flag rules engine
3. Implement queue priority calculation
4. Implement Cosmos case repository
5. Implement mock-mode services
6. Implement AI extraction/summarization service
7. Implement AI urgency classification service
8. Implement notification policy + notification service
9. Implement dashboard case list/detail/review routes
10. Implement demo text intake form
11. Implement demo audio upload endpoint
12. Implement Azure Speech transcription
13. Implement ACS phone recording callback path
14. Add Bicep deployment
15. Run end-to-end Azure demo tests
```

## 3. Repository Structure

```text
nurse-intake-assistant/
  README.md
  requirements.txt
  .env.example

  src/
    app/
      main.py

      routes/
        dashboard.py
        intake_text.py
        intake_audio.py
        acs_callbacks.py
        cases.py
        health.py

      services/
        ai_agent_service.py
        speech_service.py
        notification_service.py
        case_repository.py
        audio_storage_service.py
        urgency_rules_service.py
        case_processing_service.py

      models/
        case.py
        ai_outputs.py
        notifications.py
        review.py

      config/
        red_flags.yaml
        settings.py

      templates/
        layout.html
        dashboard_case_list.html
        dashboard_case_detail.html
        demo_text_intake.html
        demo_audio_upload.html

      static/
        styles.css

  tests/
    test_red_flags.py
    test_ai_validation.py
    test_case_mapping.py
    test_notification_policy.py
    test_review_update.py

  infra/
    main.bicep
    main.parameters.dev.json

  docs/
    architecture.md
    developer-handoff.md
    ai-103-mapping.md
    manual-setup.md
```

## 4. Runtime Modes

Support two runtime modes.

| Mode | Purpose |
|---|---|
| `APP_MODE=mock` | Local development with fake Speech, fake AI, fake notifications, and local/in-memory data |
| `APP_MODE=azure` | Real Azure Speech, Azure AI Foundry, Cosmos DB, Blob Storage, ACS, Key Vault |

Mock mode should allow dashboard and case pipeline development without Azure dependency.

## 5. Core Routes

### Health

```text
GET /health
```

Returns basic app health.

### ACS Callback Routes

```text
POST /intake/acs/events
POST /intake/acs/recording-callback
```

Responsibilities:

- Receive ACS callback/event.
- Validate callback where feasible.
- Derive idempotency key from recording ID or call ID.
- Create or load initial case record.
- Return quick HTTP acknowledgement.
- Start FastAPI background task for processing.

### Demo Routes

```text
GET  /demo/intake/text
POST /demo/intake/text
GET  /demo/intake/audio-upload
POST /demo/intake/audio-upload
```

Protected by App Service authentication. These are demo-only inputs, not a production patient portal.

### Dashboard Routes

```text
GET  /dashboard
GET  /dashboard/cases
GET  /dashboard/cases/{case_id}
POST /cases/{case_id}/review
POST /cases/{case_id}/retry
```

Dashboard behavior:

- Default to today’s new cases.
- Support date selector.
- Support review status filter: `New`, `Reviewed`, `All`.
- Show urgent cases first.
- Show `Possibly Stuck` if processing status is stale.
- Allow mark reviewed with optional nurse note.
- Allow retry for `ProcessingFailed` or `Possibly Stuck` cases.

## 6. Service Responsibilities

| Service | Responsibility |
|---|---|
| `case_processing_service.py` | Orchestrates end-to-end intake processing |
| `speech_service.py` | Transcribes audio through Azure AI Speech or mock equivalent |
| `ai_agent_service.py` | Calls Azure AI Agent for extraction, summary, and urgency classification |
| `urgency_rules_service.py` | Loads red flag YAML and applies deterministic urgent rules |
| `case_repository.py` | Reads/writes Cosmos DB case documents |
| `notification_service.py` | Sends email/SMS or mock notifications; enforces demo SMS suppression |
| `audio_storage_service.py` | Stores, reads, and deletes temporary audio blobs |
| `settings.py` | Centralized configuration, Key Vault references, environment validation |

## 7. Pydantic Models

### AI Output Models

```python
from pydantic import BaseModel, Field
from typing import Literal

class PatientInfo(BaseModel):
    name: str | None = None
    date_of_birth: str | None = None
    callback_number: str | None = None

class ExtractionSummaryResult(BaseModel):
    patient: PatientInfo
    reason_for_calling: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    summary: str
    missing_fields: list[str] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)
    extraction_notes: str | None = None

class UrgencyClassificationResult(BaseModel):
    urgency: Literal["Routine", "Urgent"]
    urgency_rationale: str
    advisory_disclaimer: str
```

### Case Status Types

```python
from typing import Literal

ProcessingStatus = Literal[
    "Received",
    "Transcribing",
    "AiProcessing",
    "Completed",
    "RetryPending",
    "ProcessingFailed",
]

IntakeStatus = Literal["Complete", "NeedsFollowUp", "ProcessingFailed"]
ReviewStatus = Literal["New", "Reviewed"]
Urgency = Literal["Routine", "Urgent", "Unknown"]
```

## 8. Case Document Shape

```json
{
  "id": "8c2f2b9e-4e28-4f26-b7fa-82b0e9c4d0e1",
  "caseNumber": "NI-20260621-143512-A7F3",
  "createdDate": "2026-06-21",
  "createdUtc": "2026-06-21T14:35:12Z",
  "lastStatusUpdatedUtc": "2026-06-21T14:35:31Z",
  "caseType": "phone-intake",

  "sourceSystem": "AzureCommunicationServices",
  "sourceCallId": "acs-call-xyz789",
  "sourceRecordingId": "acs-recording-abc123",
  "idempotencyKey": "acs-recording-abc123",

  "patient": {
    "name": "Jane Doe",
    "dateOfBirth": "1980-04-15",
    "callbackNumber": "+15555550123"
  },

  "reasonForCalling": "Chest discomfort",
  "symptoms": ["chest discomfort", "shortness of breath"],
  "transcript": "Hi, my name is Jane Doe...",
  "summary": "Patient reports chest discomfort and shortness of breath.",

  "urgency": "Urgent",
  "urgencySource": "RulesAndAI",
  "ruleUrgency": "Urgent",
  "aiUrgency": "Routine",
  "matchedRedFlags": [
    {
      "ruleId": "chest_pain",
      "label": "Chest pain",
      "matchedTerm": "chest pressure"
    }
  ],
  "urgencyRationale": "Red-flag rule matched. Advisory urgency only; nurse review required.",

  "intakeStatus": "NeedsFollowUp",
  "processingStatus": "Completed",
  "reviewStatus": "New",
  "queuePriority": 10,

  "missingFields": ["date_of_birth"],
  "uncertainFields": [],

  "automaticRetryCount": 0,
  "manualRetryCount": 0,
  "maxAutomaticRetries": 1,
  "maxManualRetries": 1,

  "notificationStatus": {
    "email": "Sent",
    "sms": "Sent",
    "failureEmail": "NotSent",
    "failureSms": "NotSent"
  },

  "audioRetentionStatus": "Deleted",
  "audioExpiresUtc": null,
  "temporaryAudioBlobName": null,

  "statusHistory": []
}
```

## 9. Cosmos DB Design

| Setting | Value |
|---|---|
| Account mode | Serverless |
| Database | `nurse-intake` |
| Container | `cases` |
| Partition key | `/createdDate` |
| Document model | One document per case |
| Date format | `yyyy-MM-dd` |

Query defaults:

- Today’s cases by `createdDate`.
- Filter by `reviewStatus`.
- Sort in application logic by `queuePriority`, then `createdUtc`.

## 10. Red Flag Rules Configuration

Path:

```text
src/app/config/red_flags.yaml
```

Example:

```yaml
red_flags:
  - id: chest_pain
    label: Chest pain
    terms:
      - chest pain
      - chest pressure
      - tightness in chest
    urgency: Urgent

  - id: shortness_of_breath
    label: Shortness of breath
    terms:
      - shortness of breath
      - trouble breathing
      - can't breathe
    urgency: Urgent
```

Rules should load on startup and be schema-validated. Invalid config should fail fast during startup.

## 11. Processing Pipeline Pseudocode

```python
async def process_case(case_id: str, source: IntakeSource) -> None:
    case = await repository.get_case(case_id)

    try:
        if source.requires_transcription:
            await repository.update_processing_status(case_id, "Transcribing")
            transcript = await speech_service.transcribe(source.audio_blob_name)
        else:
            transcript = source.text

        await repository.update_processing_status(case_id, "AiProcessing")

        extraction = await ai_agent_service.extract_and_summarize(transcript)
        extraction = validate_or_retry(extraction, ExtractionSummaryResult)

        ai_urgency = await ai_agent_service.classify_urgency(transcript, extraction)
        ai_urgency = validate_or_retry(ai_urgency, UrgencyClassificationResult)

        rule_result = urgency_rules_service.evaluate(transcript, extraction)
        final_case = map_to_case_document(case, transcript, extraction, ai_urgency, rule_result)

        await repository.save_final_case(final_case)
        await notification_service.send_success_notification(final_case)

        if source.temporary_audio_blob_name:
            await audio_storage_service.delete(source.temporary_audio_blob_name)
            await repository.mark_audio_deleted(case_id)

    except Exception as ex:
        await handle_processing_failure(case_id, ex)
```

## 12. Retry Rules

### Automatic Retry

- Triggered after initial failure.
- Runs once.
- No nurse failure notification on first failure.
- If automatic retry fails, mark `ProcessingFailed` and send failure notification.

### Manual Retry

Allowed when:

```text
processingStatus = ProcessingFailed
```

or:

```text
processingStatus IN ("Received", "Transcribing", "AiProcessing", "RetryPending")
AND lastStatusUpdatedUtc older than 15 minutes
```

Manual retry limits:

```text
maxManualRetries = 1
```

Manual retry authorization:

```text
Any authenticated dashboard user
```

Manual retry audit entry:

```json
{
  "timestampUtc": "2026-06-21T22:15:00Z",
  "status": "RetryRequested",
  "message": "Manual retry requested.",
  "actor": {
    "type": "AuthenticatedUser",
    "userPrincipalName": "nurse@example.com"
  }
}
```

## 13. Notification Policy

| Case Source | Success Email | Success SMS | Failure Email | Failure SMS |
|---|---|---|---|---|
| Real ACS phone intake | Yes | Yes | Yes | Yes |
| Demo text intake | Yes | Suppressed | Yes | Suppressed |
| Demo audio upload | Yes | Suppressed | Yes | Suppressed |

Prevent duplicate notifications by checking `notificationStatus` before sending.

## 14. Environment Variables

```text
APP_MODE=mock|azure
APP_BASE_URL=https://...

AZURE_CLIENT_ID=...
KEY_VAULT_URI=https://...

COSMOS_ENDPOINT=...
COSMOS_DATABASE_NAME=nurse-intake
COSMOS_CONTAINER_NAME=cases

STORAGE_ACCOUNT_URL=https://...
TEMP_AUDIO_CONTAINER_NAME=temp-audio

SPEECH_ENDPOINT=...
SPEECH_KEY=...

AZURE_AI_PROJECT_ENDPOINT=...
AZURE_AI_AGENT_ID=...
AZURE_OPENAI_MODEL_DEPLOYMENT=gpt-4.1-mini
AI_EXTRACTION_MODEL_DEPLOYMENT=gpt-4.1-mini
AI_CLASSIFICATION_MODEL_DEPLOYMENT=gpt-4.1-mini

ACS_CONNECTION_STRING=...
ACS_SMS_FROM_NUMBER=...
ACS_EMAIL_SENDER=...
ACS_WEBHOOK_VALIDATION_SECRET=...

NURSE_NOTIFICATION_EMAIL=...
NURSE_NOTIFICATION_PHONE=...
DEMO_SUPPRESS_SMS=true
```

Prefer Key Vault references and managed identity for Azure-hosted deployment.

## 15. Bicep Resource List

The existing full stack keeps Foundry off by default; `foundry-only.bicep` is
the daily disposable path. Both reuse `infra/modules/foundry.bicep`. The offline
check only performs local CLI/Bicep checks, what-if requires an existing group,
and live creates or reuses it. None creates an agent, edits environment files,
or cleans up. Operators supply subscription-valid model, version, provider,
SKU, capacity, region, and quota values, then copy safe outputs manually.
Pytest never calls Azure.

Provision where practical:

```text
App Service Plan
Linux Web App for FastAPI
Storage Account
Blob container for temp audio
Cosmos DB serverless account/database/container
Key Vault
Application Insights / Log Analytics
Azure AI Speech resource
Azure Communication Services resource where practical
Managed identity
RBAC/access assignments
App settings / Key Vault references
```

Document manual setup gaps:

```text
ACS phone number acquisition
ACS email sender/domain verification
Azure AI Foundry project setup
Model deployment / quota setup
Azure AI Agent creation
App Service Authentication / Entra app registration
Callback URL registration if portal-driven
```

## 16. Local Development Setup

Example local startup:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn src.app.main:app --reload
```

Start in mock mode:

```text
APP_MODE=mock
```

Mock mode should allow:

- Creating cases from text form.
- Uploading a sample audio file and using fake transcript.
- Generating deterministic fake AI summary and urgency.
- Viewing dashboard.
- Marking reviewed.
- Triggering retry behavior.

## 17. Unit Test Checklist

Implement unit tests for:

```text
Red-flag rule matching
Pydantic AI output validation
Case document mapping
Queue priority calculation
Notification policy
Review status update
Status history update
Missing-field detection
Demo notification suppression
Manual retry eligibility
Possibly Stuck detection
Audio retention status mapping
```

## 18. Manual End-to-End Demo Tests

Run these before calling Phase 1 complete:

```text
ACS phone intake → dashboard case
Protected audio upload → dashboard case
Protected text intake demo form → dashboard case
Mark reviewed with optional note
Processing failure path
Automatic retry path
Manual retry path
Notification sent/suppressed behavior
Audio cleanup after success
Failed audio retention for retry
```

## 19. Acceptance Criteria

Phase 1 is complete when:

```text
Real path target:
ACS phone call → recording → Speech transcription → AI processing → Cosmos case → nurse notification → dashboard review

Fallback/demo path:
Protected audio upload or text intake demo form → same AI/Cosmos/notification/dashboard pipeline
```

## 20. Implementation Boundaries

Do not build in Phase 1:

```text
Separate frontend app
Production patient portal
Live conversational voice bot
Queue worker / Service Bus architecture
Full RBAC
Escalation workflow
Nurse scheduling integration
Document Intelligence workflow
EHR/patient database integration
```
