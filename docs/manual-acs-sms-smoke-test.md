# Manual ACS SMS Smoke Test Guide

## Purpose

This guide is a placeholder checklist for future live ACS SMS verification. It
captures the intended manual smoke-test flow before live ACS SMS sending is
implemented.

## Current status

Live ACS SMS sending is not implemented yet. Mock SMS works locally, and ACS SMS
has fake-client tests and failure handling, but no live Azure SMS SDK path is
active.

## Future required configuration

Future live ACS SMS smoke testing will require:

```bash
SMS_PROVIDER=acs
ACS_SMS_CONNECTION_STRING=
ACS_SMS_FROM_PHONE_NUMBER=
NURSE_NOTIFICATION_PHONE_NUMBER=
DEMO_SUPPRESS_NOTIFICATIONS=false
```

## Planned local run command

When live ACS SMS support exists, run the app locally with uvicorn:

```bash
.venv/bin/python -m uvicorn src.app.main:app --reload
```

## Planned smoke-test steps

1. Confirm the future ACS SMS settings are present only in local environment
   variables.
2. Start the API with uvicorn.
3. Submit a safe intake with `POST /intake/text`.
4. Confirm the returned case id can be used for follow-up verification.
5. Review the response fields for notification results.

## Expected future results

After a successful live ACS SMS send, the text intake response should include:

```text
notificationSmsSent=true
```

`notificationEmailSent` behavior should remain independent of live ACS SMS
success or failure.

## Failure-handling expectations

ACS SMS send failure should not crash intake processing. Failed SMS should leave:

```text
notificationSmsSent=false
```

The case should still be saved and returned for nurse review.

## Safety notes

Do not commit secrets, connection strings, access keys, or real phone numbers.
Keep live ACS SMS values in local environment variables or a secure secret store
when that future path is implemented.

## Current limitations

- No Azure SMS SDK dependency has been added yet.
- `create_acs_sms_client` is still a placeholder/factory boundary.
- live ACS SMS smoke testing has not been completed yet.
