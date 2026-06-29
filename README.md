# Nurse Intake Assistant

AI-assisted nurse intake capstone project for Azure AI-103 preparation.

## Phase 1 MVP

- Patient intake via text
- AI-generated summary
- Urgency classification
- Nurse notification
- Basic storage/logging

## Local Mock Demo Walkthrough

This project demonstrates a local mock/demo only nurse intake workflow for the
AI-103 capstone: intake text is converted into a case, mock AI output is shown
for nurse review, queue summary counts are updated, and mock email/SMS
notifications can be inspected without contacting live services.

Safety boundary:

- This is local mock/demo only, with no production clinical use.
- Mock mode sends no real email or SMS.
- AI output requires human nurse review before any clinical action.
- Do not use real patient data, real phone numbers, secrets, connection
  strings, or provider credentials in the local demo.

Use safe mock defaults:

```bash
APP_MODE=mock
AI_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=false
```

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
5. submit the nurse review.
6. submit a text intake.
7. submit a voicemail transcript intake.
8. Inspect mock email/SMS notifications.
9. reset demo state.

This MVP intentionally does not include hosting, authentication, Key Vault,
Azure Speech, live Azure AI Foundry extraction, ACS SMS delivery tracking, retry
logic, or a frontend framework.

For the fuller manual checklist, see `docs/demo-smoke-test.md`. For API-level
local demo commands, see `docs/manual-local-mock-demo.md`.

## Static Legal Pages

The demo legal placeholder pages are served by the FastAPI app from `src/app/static/`:

- `/static/privacy.html`
- `/static/terms.html`

Run locally with `uvicorn src.app.main:app --reload`, then open the pages from the local FastAPI host.
