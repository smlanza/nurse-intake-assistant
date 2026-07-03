# Demo Readiness Checklist

Use this checklist before an interview or capstone demo. Keep the demo
mock-first, fictional, and conservative.

## Pre-Demo Setup

```bash
source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
APP_MODE=mock AI_PROVIDER=mock SPEECH_PROVIDER=mock EMAIL_PROVIDER=mock SMS_PROVIDER=mock uvicorn src.app.main:app --reload
```

Automated tests are offline only. They must not call Azure, models, Speech,
Cosmos, ACS, or live notification services.

## Local Mock Demo Path

1. Open `http://127.0.0.1:8000/demo`.
2. Use demo reset if the state is messy.
3. Seed demo data.
4. Submit a fictional text intake.
5. Load recent cases and queue summary.
6. Select a case for review.
7. Load the nurse handoff note for the selected case.
8. Submit nurse review.
9. Inspect mock email/SMS notifications if relevant.
10. Reset demo state before handing off or repeating the demo.

## Safe Talking Points

- The default demo is a local mock demo.
- Manual Azure OpenAI / Foundry structured extraction smoke has been validated
  separately with fictional medication-refill input.
- The live validation is through a manual smoke script only; it is not wired
  into the default demo path.
- Automated tests remain offline and deterministic.
- Nurse review is required before any clinical action.
- Urgency output is advisory only.
- Use no real PHI, real phone numbers, real email addresses, secrets, tokens,
  credentials, connection strings, API keys, endpoint values, or deployment
  names in the demo.

## Do Not Claim

- Do not claim production readiness.
- Do not claim clinical decision support or autonomous medical decision-making.
- Do not claim live phone intake, ACS call automation, or live Azure Speech
  transcription.
- Do not claim Azure hosting unless separately deployed and verified.
- Do not claim real email/SMS notifications in the local mock demo.
- Do not claim the system replaces nurse judgment.
- Do not claim HIPAA, security, compliance, Key Vault, retry/durable
  processing, Agents, MCP/A2A, or production operations are complete.

## Optional Live Smoke

Run this only as an optional manual smoke test with fictional input and local
env-file settings:

```bash
python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live --diagnose --live-client-mode azure-openai-endpoint
```

Do not show or paste real environment values. The smoke script redacts endpoint
values, deployment names, prompts, model responses, tokens, credentials, raw
exceptions, request URLs, and tracebacks.

## Troubleshooting

- If demo state is messy, use demo reset and seed fresh fictional data.
- If the Azure smoke path fails, keep the interview demo in mock mode and
  describe the safe diagnostic category only.
- If tests fail, do not demo live changes.
- If local provider settings leaked into your shell, restore mock defaults
  before running the app or tests.
