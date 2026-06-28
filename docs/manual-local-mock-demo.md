# Local Mock Demo Guide

## Purpose

Use this guide to run the Nurse Intake Assistant locally in safe mock mode and
demonstrate the current MVP nurse workflow without Azure resources.

The flow covers text intake validation, case creation, the nurse queue, queue
summary counts, case retrieval, human review, mock email notification
inspection, and mock SMS notification inspection.

## Safe Local Configuration

Use mock providers for the local demo:

```bash
APP_MODE=mock
AI_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=false
```

Mock mode sends no real email or SMS. Mock notifications are recorded in memory
for local/demo inspection only.

## Start The API

From the project root, start the FastAPI app with uvicorn:

```bash
.venv/bin/python -m uvicorn src.app.main:app --reload
```

The examples below use:

```bash
BASE_URL=http://127.0.0.1:8000
```

## Demo Step 1: Reset Demo State

Optionally clear in-memory cases and recorded mock notifications before a demo
run with `POST /demo/reset`:

```bash
curl -X POST "$BASE_URL/demo/reset"
```

The response should confirm that cases, mock email notifications, and mock SMS
notifications were cleared.

## Demo Step 2: Seed Representative Demo Cases

For a repeatable local demo, seed a deterministic nurse queue with
`POST /demo/seed`:

```bash
curl -X POST "$BASE_URL/demo/seed"
```

The response should include `success=true`, `seededCaseCount`, and deterministic
`caseIds`. Seeded cases appear in `GET /cases` and `GET /cases/summary` and
include urgent, routine, pending-review, reviewed, needs-follow-up, text-intake,
voicemail-transcript, and mock notification status examples.

Calling the seed endpoint repeatedly does not create duplicate seed cases.

## Demo Step 3: Open The Demo Page

Open the local demo page:

```text
http://127.0.0.1:8000/demo
```

Use the clickable Demo Workflow navigation to move through matching numbered
sections. Seed Demo Data, then Load Recent Cases, Load Queue Summary, click
Select for Review on a case, confirm the page jumps to Nurse Review and focuses
the populated case id field, confirm review notes are cleared for the selected
case, submit the review, confirm Recent Cases and Queue Summary refresh
automatically, confirm Recent Cases shows persisted review metadata for the
reviewed case, and reset demo state when done.

## Demo Step 4: Submit A Valid Text Intake

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

## Demo Step 5: Check Intake Validation

Requests with empty, blank, whitespace-only, and too-short intake text are
rejected before case processing.
Rejected intake text does not create cases or notifications.

```bash
curl -X POST "$BASE_URL/intake/text" \
  -H "Content-Type: application/json" \
  -d '{"text": ""}'

curl -X POST "$BASE_URL/intake/text" \
  -H "Content-Type: application/json" \
  -d '{"text": "   "}'

curl -X POST "$BASE_URL/intake/text" \
  -H "Content-Type: application/json" \
  -d '{"text": "hi"}'
```

These requests should return a validation error instead of creating a case or
recording mock email/SMS notifications.

## Demo Step 6: List The Nurse Queue

List saved cases with `GET /cases`:

```bash
curl "$BASE_URL/cases"
```

The response is a JSON array of case documents.

## Demo Step 7: Filter The Nurse Queue

Filter pending-review cases with `GET /cases?reviewStatus=PendingReview`:

```bash
curl "$BASE_URL/cases?reviewStatus=PendingReview"
```

Filter reviewed cases later with `GET /cases?reviewStatus=Reviewed`:

```bash
curl "$BASE_URL/cases?reviewStatus=Reviewed"
```

Filter urgent cases with `GET /cases?urgency=Urgent`:

```bash
curl "$BASE_URL/cases?urgency=Urgent"
```

Filter by an inclusive created-date range with
`GET /cases?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD`:

```bash
curl "$BASE_URL/cases?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD"
```

The case created in step 2 should appear in the pending queue with
`reviewStatus` set to `PendingReview`.

## Demo Step 8: View Queue Summary

View dashboard-style queue counts with `GET /cases/summary`:

```bash
curl "$BASE_URL/cases/summary"
```

Date-filter summary counts with
`GET /cases/summary?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD`:

```bash
curl "$BASE_URL/cases/summary?fromDate=YYYY-MM-DD&toDate=YYYY-MM-DD"
```

Summary counts include total cases, pending review cases, reviewed cases, urgent
cases, routine cases, and pending urgent cases.

## Demo Step 9: Retrieve The Saved Case

Retrieve the saved case with `GET /cases/{case_id}`:

```bash
curl "$BASE_URL/cases/{case_id}"
```

Replace `{case_id}` with the case id returned by `POST /intake/text`.

## Demo Step 10: Review The Case

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

## Demo Step 11: Confirm Reviewed Cases

Confirm the case moved to the reviewed queue with
`GET /cases?reviewStatus=Reviewed`:

```bash
curl "$BASE_URL/cases?reviewStatus=Reviewed"
```

The reviewed case should appear with `reviewStatus` set to `Reviewed`.

## Demo Step 12: Inspect Mock Email Notifications

Verify recorded mock email notifications with `GET /notifications/email`:

```bash
curl "$BASE_URL/notifications/email"
```

The response should include an entry for the created case. In mock mode, no real
email is sent.

## Demo Step 13: Inspect Mock SMS Notifications

Verify recorded mock SMS notifications with `GET /notifications/sms`:

```bash
curl "$BASE_URL/notifications/sms"
```

The response should include an entry for the created case. In mock mode, no real
SMS is sent.

## Demo Step 14: Reset Demo State

Clear seeded cases, manually submitted local cases, and mock notification
records with `POST /demo/reset`:

```bash
curl -X POST "$BASE_URL/demo/reset"
```

After reset, `GET /cases` should return an empty array and
`GET /cases/summary` should return zero counts.

## Safety Notes

This guide is for local mock demo mode only. It does not require Azure
resources, ACS connection strings, Cosmos keys, access keys, Azure AI keys,
model deployment names, real contact details, or real provider credentials.

Do not commit secrets, connection strings, real phone numbers, real email
addresses, access keys, or provider credentials.

## Current Limitations

Live ACS SMS handset delivery remains pending external toll-free verification
and is not required for this local mock demo.

Cosmos list/summary multi-day queue querying remains a future enhancement. The
local mock queue supports list and summary filtering for demo purposes, while
Cosmos cross-partition queue and summary querying is intentionally out of scope
for now.
