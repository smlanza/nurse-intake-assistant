# Nurse Intake Assistant

AI-assisted nurse intake capstone project for Azure AI-103 preparation.

## Phase 1 MVP

- Patient intake via text
- AI-generated summary
- Urgency classification
- Nurse notification
- Basic storage/logging

## Static Legal Pages

The demo legal placeholder pages are served by the FastAPI app from `src/app/static/`:

- `/static/privacy.html`
- `/static/terms.html`

Run locally with `uvicorn src.app.main:app --reload`, then open the pages from the local FastAPI host.
