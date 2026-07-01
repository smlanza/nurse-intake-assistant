# Manual ACS Email Smoke Test

Use this checklist to prepare for and manually verify ACS Email notification
sending from the local FastAPI app. The `--check` preflight is offline-safe:
it validates local configuration, reports optional SDK visibility, creates no
ACS Email client, makes no Azure calls, and sends no email.

The automated tests must not send email or call Azure. Do not commit `.env`, real
ACS connection strings, real email addresses, provider credentials, secrets, or
real PHI. Do not paste those values into docs, tests, logs, prompts, or commits.

## 1. Confirm Prerequisites

- An Azure Communication Services Email resource is available.
- The sender address is verified and ready to send mail.
- You have a safe nurse recipient email address for test delivery.
- The local virtual environment has project requirements installed.

## 2. Configure Local `.env`

Set local email configuration:

```bash
EMAIL_PROVIDER=acs
ACS_EMAIL_CONNECTION_STRING=endpoint=https://placeholder-resource.communication.azure.com/;accesskey=placeholder-secret
ACS_EMAIL_SENDER_ADDRESS=sender-placeholder@example.invalid
NURSE_NOTIFICATION_EMAIL=nurse-recipient-placeholder@example.invalid
DEMO_SUPPRESS_NOTIFICATIONS=false
```

Keep `APP_MODE=mock` unless this smoke test is intentionally combined with
Cosmos verification.

## 3. Run The Safe Preflight

Run the ACS Email configuration preflight before starting any manual delivery
test:

```bash
python scripts/smoke_acs_email.py --check
```

Required environment variables:

- `EMAIL_PROVIDER=acs`
- `ACS_EMAIL_CONNECTION_STRING`
- `ACS_EMAIL_SENDER_ADDRESS`
- `NURSE_NOTIFICATION_EMAIL`

Preflight success means the required settings are present for the ACS Email
provider boundary and optional Azure Communication Email SDK visibility was
reported. It does not prove email delivery because it creates no ACS Email
client, makes no Azure network call, and sends no email.

Preflight failure means one or more required settings are missing or
`EMAIL_PROVIDER` is not set to `acs`. The script prints only variable names and
safe next-step hints; it must not print configured connection strings, email
addresses, stack traces, tokens, or raw exception details.

## 4. Start The App

Start FastAPI locally with the `.env` file:

```bash
.venv/bin/uvicorn src.app.main:app \
  --reload \
  --env-file .env
```

## 5. Submit A Safe Test Intake

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

## 6. Confirm Email Delivery

Check the mailbox configured in `NURSE_NOTIFICATION_EMAIL`. Confirm an email was
sent to the configured nurse recipient and that it contains the safe test case
details.

## 7. Restore Safe Local Defaults

Stop the local app and reset `.env` back to mock email mode:

```bash
EMAIL_PROVIDER=mock
ACS_EMAIL_CONNECTION_STRING=
ACS_EMAIL_SENDER_ADDRESS=
NURSE_NOTIFICATION_EMAIL=
```

Leave `DEMO_SUPPRESS_NOTIFICATIONS` in the value needed for your next local
test. Mock email remains the default behavior for local demo and automated
tests.
