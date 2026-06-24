# Manual ACS Email Smoke Test

Use this checklist to manually verify ACS Email notification sending from the
local FastAPI app. This is a manual smoke test and automated tests must not run
it.

Do not commit `.env` or real ACS connection strings or secrets.

## 1. Confirm Prerequisites

- An Azure Communication Services Email resource is available.
- The sender address is verified and ready to send mail.
- You have a safe nurse recipient email address for test delivery.
- The local virtual environment has project requirements installed.

## 2. Configure Local `.env`

Set local email configuration:

```bash
EMAIL_PROVIDER=acs
ACS_EMAIL_CONNECTION_STRING=endpoint=https://your-resource.communication.azure.com/;accesskey=your-secret
ACS_EMAIL_SENDER_ADDRESS=DoNotReply@your-verified-domain.example
NURSE_NOTIFICATION_EMAIL=nurse-test-recipient@example.com
DEMO_SUPPRESS_NOTIFICATIONS=false
```

Keep `APP_MODE=mock` unless this smoke test is intentionally combined with
Cosmos verification.

## 3. Start The App

Start FastAPI locally with the `.env` file:

```bash
.venv/bin/uvicorn src.app.main:app \
  --reload \
  --env-file .env
```

## 4. Submit A Safe Test Intake

Send a safe demo request to `POST /intake/text`:

```bash
curl -s -X POST http://127.0.0.1:8000/intake/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My name is Jane Doe. DOB: 1980-04-15. My callback number is +1 (555) 555-0123. I need a medication refill.",
    "sourceSystem": "manual-acs-email-smoke-test",
    "sourceCallId": "manual-email-smoke-001"
  }'
```

Confirm the API returns HTTP 200 and includes a case id.

## 5. Confirm Email Delivery

Check the mailbox configured in `NURSE_NOTIFICATION_EMAIL`. Confirm an email was
sent to the configured nurse recipient and that it contains the safe test case
details.

## 6. Restore Safe Local Defaults

Stop the local app and reset `.env` back to mock email mode:

```bash
EMAIL_PROVIDER=mock
ACS_EMAIL_CONNECTION_STRING=
ACS_EMAIL_SENDER_ADDRESS=
NURSE_NOTIFICATION_EMAIL=
```

Leave `DEMO_SUPPRESS_NOTIFICATIONS` in the value needed for your next local
test.
