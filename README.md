# Nurse Intake Assistant

AI-assisted nurse intake capstone project for Azure AI-103 preparation.

## Phase 1 MVP

- Patient intake via text
- AI-generated summary
- Urgency classification
- Nurse notification
- Basic storage/logging

## Current Status

- Default local demo: mock mode remains the primary interview/demo path.
- Automated tests: offline only; no Azure calls, model calls, audio processing,
  email sends, or SMS sends.
- Live Azure OpenAI / Foundry structured extraction: manually smoke-tested with
  fictional medication-refill input through
  `scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live --diagnose --live-client-mode azure-openai-endpoint`.
- Clinical boundary: this is not production clinical software; AI output is
  advisory only and requires nurse review before any clinical action.
- Data boundary: do not use real PHI, real phone numbers, real email addresses,
  secrets, tokens, credentials, connection strings, API keys, or real endpoint
  values in demo/smoke-test documentation.

For a concise interview/demo runbook, use
`docs/demo-readiness-checklist.md`.

## Local Mock Demo Walkthrough

This project demonstrates a local mock/demo only nurse intake workflow for the
AI-103 capstone: intake text is converted into a case, mock AI output is shown
for nurse review, queue summary counts are updated, and mock email/SMS
notifications can be inspected without contacting live services.

Safety boundary:

- This is local mock/demo only, with no production clinical use.
- Mock mode sends no real email or SMS.
- Mock/local mode does not call Azure, does not call models, and does not process audio.
- AI output requires human nurse review before any clinical action.
- Do not use real patient data, real phone numbers, secrets, connection
  strings, provider credentials, or real Azure resource identifiers in the
  local demo.
- Use no real Azure resource identifiers in the local mock demo.
- Real Azure providers require explicit provider environment variables and credentials before any live smoke testing.

## Demo Claims

The current demo can safely show local text intake, already-transcribed voicemail transcript intake, deterministic mock AI extraction, urgency classification, nurse review workflow, queue/recent case views and summary counts, deterministic handoff notes, mock email/SMS notification inspection, and offline-safe consolidated preflight checks.

The demo must not claim production clinical readiness, autonomous medical decision-making, live Azure AI Foundry extraction, live Azure Speech transcription, live phone intake/call automation, confirmed ACS SMS handset delivery, or hosting/auth/Key Vault/retry/durable processing.

The boundary remains: human nurse review is required, use fictional/demo data only,
commit no secrets or PHI, and default mock mode makes no Azure calls,
model calls, audio processing, repository reads/writes/queries, email sends, or
SMS sends unless an explicit provider/manual smoke path is intentionally
selected.

The `/demo` page displays read-only, offline-safe readiness from
`GET /demo/status` without exposing secrets, creating Azure clients, or
validating live Azure readiness.

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the test suite:

```bash
python -m pytest
```

For disposable daily Foundry validation, use `infra/foundry-only.bicep`; the
existing full-stack `infra/main.bicep` keeps Foundry optional and disabled by
default. Begin with the offline `scripts/deploy_foundry_infra.py --check`
workflow in [`infra/README.md`](infra/README.md). Infrastructure deployment
never creates the prompt agent or edits local environment files.

Use safe mock defaults:

```bash
APP_MODE=mock
AI_PROVIDER=mock
SPEECH_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=false
```

## Provider Mode Matrix

The provider settings are independent adapter toggles, not an all-or-nothing
Azure switch. It is valid to enable one provider for a manual smoke path while
the rest stay mock. APP_MODE selects the app runtime/storage posture; it does
not automatically switch every provider to Azure. Do not introduce APP_MODE=azure.

Smoke-test scripts are automated checks that are manually invoked unless wired into CI/CD.
They are not run by app startup, /demo, or /demo/status.

| Scenario | Set these variables | Providers that remain mock |
| --- | --- | --- |
| Default local demo mode | `APP_MODE=mock`, `AI_PROVIDER=mock`, `AGENT_PROVIDER=mock`, `SPEECH_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock` | All live providers remain mock/offline |
| Foundry Agent deployment check | `AGENT_PROVIDER=foundry-agent`, Foundry Agent project/name plus `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`; run `scripts/deploy_foundry_agent.py --env-file .env.foundry-agent.local --check`, then explicit `--live --json` only for manual creation/validation | Application runtime and all notification/storage providers remain mock; deployment never runs at startup or intake time |
| Foundry Agent smoke-test mode | `AGENT_PROVIDER=foundry-agent` or the `AGENT_PROVIDER=foundry` smoke alias, `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT`, `AZURE_AI_FOUNDRY_AGENT_NAME`, `AZURE_AI_FOUNDRY_AGENT_VERSION`; run `scripts/smoke_foundry_agent.py --check` before explicit `--live` | `APP_MODE=mock`, `AI_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock`, `SPEECH_PROVIDER=mock` |
| ACS Email smoke-test mode | `EMAIL_PROVIDER=acs`, `ACS_EMAIL_CONNECTION_STRING`, `ACS_EMAIL_SENDER_ADDRESS`, `NURSE_NOTIFICATION_EMAIL`; run `scripts/smoke_acs_email.py --check` | `APP_MODE=mock`, `AI_PROVIDER=mock`, `AGENT_PROVIDER=mock`, `SMS_PROVIDER=mock`, `SPEECH_PROVIDER=mock` |
| ACS SMS smoke-test mode | `SMS_PROVIDER=acs`, `ACS_SMS_CONNECTION_STRING`, `ACS_SMS_FROM_PHONE_NUMBER`, `NURSE_NOTIFICATION_PHONE_NUMBER`; run `scripts/smoke_acs_sms.py --check` | `APP_MODE=mock`, `AI_PROVIDER=mock`, `AGENT_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, `SPEECH_PROVIDER=mock` |
| Azure Speech smoke-test mode | `SPEECH_PROVIDER=azure`, `AZURE_SPEECH_ENDPOINT`, `AZURE_SPEECH_REGION`; run `scripts/smoke_speech_transcription.py --check` | `APP_MODE=mock`, `AI_PROVIDER=mock`, `AGENT_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock` |
| Cosmos persistence smoke-test mode | `APP_MODE=cosmos`, `COSMOS_ENDPOINT`, `COSMOS_KEY`, `COSMOS_DATABASE_NAME`, `COSMOS_CONTAINER_NAME`; see `docs/manual-cosmos-smoke-test.md` | `AI_PROVIDER=mock`, `AGENT_PROVIDER=mock`, `EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock`, `SPEECH_PROVIDER=mock` |

For example, AGENT_PROVIDER=foundry-agent or the AGENT_PROVIDER=foundry smoke
alias while APP_MODE, AI_PROVIDER, EMAIL_PROVIDER, SMS_PROVIDER, and
SPEECH_PROVIDER remain mock is an expected manual Foundry Agent smoke-test
shape.

Run the offline-safe provider preflight in mock-safe mode:

```bash
python scripts/preflight.py --all
```

The consolidated preflight checks Cosmos Repository, Foundry, Foundry Agent,
Azure Speech, ACS Email, and ACS SMS configuration without live service
behavior. In default mock mode, `SKIP is expected and safe` because the
corresponding live provider is not enabled:

```text
Nurse Intake Assistant Preflight
Offline-safe checks only. No Azure clients, Azure calls, model calls, agent calls, audio processing, repository reads/writes/queries, email sends, or SMS sends are performed.
SKIP Cosmos Repository: APP_MODE is not cosmos.
SKIP Foundry: AI_PROVIDER is not foundry.
SKIP Foundry Agent: AGENT_PROVIDER is mock.
SKIP Azure Speech: SPEECH_PROVIDER is not azure.
SKIP ACS Email: EMAIL_PROVIDER is not acs.
SKIP ACS SMS: SMS_PROVIDER is not acs.
Preflight summary: PASS=0, SKIP=6, FAIL=0. Completed safely with no failed checks.
Guidance:
- For the local demo, keep APP_MODE, AI_PROVIDER, AGENT_PROVIDER, SPEECH_PROVIDER, EMAIL_PROVIDER, and SMS_PROVIDER set to mock.
- Enable one live provider at a time only for explicit manual smoke testing.
- This preflight remains offline-safe and does not call Azure.
```

Run the Foundry Agent readiness check by itself when preparing that manual
smoke path:

```bash
python scripts/preflight.py --foundry-agent
```

That check is configuration-only: No Foundry Agent client is created, no agent
was invoked, no Azure call is made, no case is persisted, and no email or SMS is
sent.

If you explicitly enable a live provider without its required local
configuration, `FAIL means required configuration is missing` for that
explicitly enabled provider, not that a live service call failed. For example,
`APP_MODE=cosmos` without Cosmos settings fails safely with exit code 1:

```text
FAIL Cosmos Repository: Missing required configuration: COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE_NAME, COSMOS_CONTAINER_NAME.
Preflight summary: PASS=0, SKIP=5, FAIL=1. One or more checks failed.
Guidance:
- Cosmos Repository: Set missing Cosmos variables or restore APP_MODE=mock.
- A FAIL result means required local configuration is missing; this preflight did not call Azure.
```

The preflight shows missing variable names, but secret values are not printed.
Even in failure mode it remains offline-safe: No Azure clients, Azure calls,
model calls, agent calls, audio processing, repository reads/writes/queries,
email sends, or SMS sends are performed.

Start the app locally:

```bash
uvicorn src.app.main:app --reload
```

Then open:

```text
http://127.0.0.1:8000/demo
```

Expected demo workflow:

1. Click Seed Demo Data.
2. Click Load Recent Cases.
3. Click Load Queue Summary.
4. Click Select for Review on a case.
5. Click Load Handoff Note for the selected case.
6. submit the nurse review.
7. submit a text intake.
8. submit a voicemail transcript intake.
9. Inspect mock email/SMS notifications.
10. reset demo state.

This MVP intentionally does not include hosting, authentication, Key Vault,
Azure Speech, live Azure AI Foundry extraction, ACS SMS delivery tracking, retry
logic, or a frontend framework.

The current default demo remains local mock/offline. Start with
`docs/system-overview.md` for the project map. Azure AI Foundry and Azure
Speech have provider boundaries/scaffolds for future work, but live Azure
validation is manual/future; see `docs/progress.md` for the current resume
point, `docs/manual-foundry-smoke-test.md` for the Foundry checklist, and
`docs/manual-speech-smoke-test.md` for the Speech preflight guide. ACS Email
has an offline-safe preflight plus manual delivery checklist in
`docs/manual-acs-email-smoke-test.md`, and ACS SMS has an offline-safe
preflight plus deferred handset-delivery checklist in
`docs/manual-acs-sms-smoke-test.md`.

Run all offline-safe provider readiness checks from one command:

```bash
python scripts/preflight.py --all
```

For the fuller manual checklist, see `docs/demo-smoke-test.md`. For API-level
local demo commands, see `docs/manual-local-mock-demo.md`. For the future
manual Azure AI Foundry smoke-test checklist, see
`docs/manual-foundry-smoke-test.md`. For offline-safe Azure Speech smoke-test
preparation, see `docs/manual-speech-smoke-test.md`. For offline-safe ACS Email
configuration preflight and the manual delivery checklist, see
`docs/manual-acs-email-smoke-test.md`. For offline-safe ACS SMS configuration
preflight and the deferred handset-delivery checklist, see
`docs/manual-acs-sms-smoke-test.md`.

## Static Legal Pages

The demo legal placeholder pages are served by the FastAPI app from `src/app/static/`:

- `/static/privacy.html`
- `/static/terms.html`

Run locally with `uvicorn src.app.main:app --reload`, then open the pages from the local FastAPI host.
