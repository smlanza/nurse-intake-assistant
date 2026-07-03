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

Use safe mock defaults:

```bash
APP_MODE=mock
AI_PROVIDER=mock
SPEECH_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=false
```

Run the offline-safe provider preflight in mock-safe mode:

```bash
python scripts/preflight.py --all
```

The consolidated preflight checks Cosmos Repository, Foundry, Azure Speech, ACS
Email, and ACS SMS configuration without live service behavior. In default mock
mode, `SKIP is expected and safe` because the corresponding live provider is
not enabled:

```text
Nurse Intake Assistant Preflight
Offline-safe checks only. No Azure clients, Azure calls, model calls, audio processing, repository reads/writes/queries, email sends, or SMS sends are performed.
SKIP Cosmos Repository: APP_MODE is not cosmos.
Guidance: Keep APP_MODE=mock for local demo.
SKIP Foundry: AI_PROVIDER is not foundry.
Guidance: Keep AI_PROVIDER=mock for local demo.
SKIP Azure Speech: SPEECH_PROVIDER is not azure.
Guidance: Keep SPEECH_PROVIDER=mock for local demo.
SKIP ACS Email: EMAIL_PROVIDER is not acs.
Guidance: Keep EMAIL_PROVIDER=mock for local demo.
SKIP ACS SMS: SMS_PROVIDER is not acs.
Guidance: Keep SMS_PROVIDER=mock for local demo.
Preflight summary: PASS=0, SKIP=5, FAIL=0. Completed safely with no failed checks.
```

If you explicitly enable a live provider without its required local
configuration, `FAIL means required configuration is missing` for that
explicitly enabled provider, not that a live service call failed. For example,
`APP_MODE=cosmos` without Cosmos settings fails safely with exit code 1:

```text
FAIL Cosmos Repository: Missing required configuration: COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE_NAME, COSMOS_CONTAINER_NAME.
Guidance: Set missing Cosmos variables or restore APP_MODE=mock.
Preflight summary: PASS=0, SKIP=4, FAIL=1. One or more checks failed.
```

The preflight shows missing variable names, but secret values are not printed.
Even in failure mode it remains offline-safe: No Azure clients, Azure calls,
model calls, audio processing, repository reads/writes/queries, email sends, or
SMS sends are performed.

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
