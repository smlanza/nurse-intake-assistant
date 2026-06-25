# Local Mock Demo Guide

## Purpose

Use this guide to run the Nurse Intake Assistant locally in safe mock mode and
verify text intake, saved case lookup, mock email notification inspection, and
mock SMS notification inspection.

## Safe local configuration

Use mock providers for the local demo:

```bash
APP_MODE=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=false
```

## Start the API

From the project root, start the FastAPI app with uvicorn:

```bash
.venv/bin/python -m uvicorn src.app.main:app --reload
```

## Demo step 1: submit text intake

Submit a safe sample intake with `POST /intake/text`:

```bash
curl -X POST http://127.0.0.1:8000/intake/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My name is Jane Doe. DOB: 1980-04-15. My callback number is +1 (555) 555-0123. I need a medication refill."
  }'
```

Save the returned `id` as `case_id` for the next step.

## Demo step 2: retrieve the saved case

Verify the saved case with `GET /cases/{case_id}`:

```bash
curl http://127.0.0.1:8000/cases/{case_id}
```

## Demo step 3: inspect mock email notifications

Verify recorded mock email notifications with `GET /notifications/email`:

```bash
curl http://127.0.0.1:8000/notifications/email
```

## Demo step 4: inspect mock SMS notifications

Verify recorded mock SMS notifications with `GET /notifications/sms`:

```bash
curl http://127.0.0.1:8000/notifications/sms
```

## Expected results

The text intake response should include:

```text
notificationEmailSent=true
notificationSmsSent=true
```

The mock email and SMS inspection responses should include entries for the
created case, including recipient, body or message content, and case id details.

## Safety notes

In mock mode, no real email or SMS is sent. Mock notifications are recorded in
memory for local/demo inspection only.

Do not commit secrets, connection strings, real phone numbers, or provider
credentials.

## Current limitations

Live ACS SMS is not implemented yet. This guide covers local mock behavior only.
