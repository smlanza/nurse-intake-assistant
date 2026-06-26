# Local Mock Demo Guide

## Purpose

Use this guide to run the Nurse Intake Assistant locally in safe mock mode and
demonstrate the current MVP nurse workflow without Azure resources.

The flow covers text intake, the nurse case queue, case retrieval, human review,
mock email notification inspection, and mock SMS notification inspection.

## Safe local configuration

Use mock providers for the local demo:

```bash
APP_MODE=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=false
```

In mock mode, no real email or SMS is sent. Mock notifications are recorded in
memory for local/demo inspection only.

## Start the API

From the project root, start the FastAPI app with uvicorn:

```bash
.venv/bin/python -m uvicorn src.app.main:app --reload
```

The examples below use:

```bash
BASE_URL=http://127.0.0.1:8000
```

## Demo step 1: submit text intake

Submit a safe fictional sample intake with `POST /intake/text`:

```bash
curl -X POST "$BASE_URL/intake/text" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My name is Jane Doe. DOB: 1980-04-15. I need a medication refill."
  }'
```

The response should include:

```text
reviewStatus="PendingReview"
notificationEmailSent=true
notificationSmsSent=true
```

Save the returned `id` as `case_id` for later steps.

## Demo step 2: list the nurse queue

List saved cases with `GET /cases`:

```bash
curl "$BASE_URL/cases"
```

The response is a JSON array of case documents.

## Demo step 3: filter pending-review cases

Filter the nurse queue with `GET /cases?reviewStatus=PendingReview`:

```bash
curl "$BASE_URL/cases?reviewStatus=PendingReview"
```

The case created in step 1 should appear with `reviewStatus` set to
`PendingReview`.

## Demo step 4: retrieve the saved case

Retrieve the saved case with `GET /cases/{case_id}`:

```bash
curl "$BASE_URL/cases/{case_id}"
```

Replace `{case_id}` with the case id returned by `POST /intake/text`.

## Demo step 5: review the case

Mark the case reviewed with `POST /cases/{case_id}/review`:

```bash
curl -X POST "$BASE_URL/cases/{case_id}/review" \
  -H "Content-Type: application/json" \
  -d '{
    "reviewedBy": "nurse-demo",
    "reviewNotes": "Called patient back and routed to clinic."
  }'
```

The response should include:

```text
reviewStatus="Reviewed"
reviewedBy="nurse-demo"
reviewNotes="Called patient back and routed to clinic."
reviewedAt=<UTC timestamp>
```

This step reinforces that AI output requires nurse review and that the system is
an intake assistant, not an autonomous medical decision-maker.

## Demo step 6: filter reviewed cases

Confirm the case moved to the reviewed queue with
`GET /cases?reviewStatus=Reviewed`:

```bash
curl "$BASE_URL/cases?reviewStatus=Reviewed"
```

The reviewed case should appear with `reviewStatus` set to `Reviewed`.

## Demo step 7: inspect mock email notifications

Verify recorded mock email notifications with `GET /notifications/email`:

```bash
curl "$BASE_URL/notifications/email"
```

The response should include an entry for the created case. In mock mode, no real
email is sent.

## Demo step 8: inspect mock SMS notifications

Verify recorded mock SMS notifications with `GET /notifications/sms`:

```bash
curl "$BASE_URL/notifications/sms"
```

The response should include an entry for the created case. In mock mode, no real
SMS is sent.

## Safety notes

This guide is for local mock demo mode only. It does not require Azure
resources, ACS connection strings, Cosmos keys, access keys, real contact
details, or real provider credentials.

Do not commit secrets, connection strings, real phone numbers, or provider
credentials.

## Current limitations

Live ACS SMS handset delivery remains pending external toll-free verification
and is not required for this local demo. Live ACS SMS sending is not implemented
as part of this local mock workflow.
