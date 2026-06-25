# Manual ACS SMS Smoke Test Guide

## Purpose

This guide records the ACS SMS smoke-test checklist and current stopping point.
It remains a placeholder/checklist for future live ACS SMS verification after
external toll-free verification is complete.

## Current status

ACS SMS is integrated far enough to reach the Azure Communication Services SMS
SDK/send-request path. Mock SMS remains the primary demo path. Live handset
delivery is not confirmed yet. Confirmed live ACS SMS handset delivery is not implemented yet.

ACS Email live smoke testing was previously completed successfully.

## Future required configuration

Live ACS SMS smoke testing uses:

```bash
SMS_PROVIDER=acs
ACS_SMS_CONNECTION_STRING=
ACS_SMS_FROM_PHONE_NUMBER=
NURSE_NOTIFICATION_PHONE_NUMBER=
DEMO_SUPPRESS_NOTIFICATIONS=false
```

## Local run command

Run the app locally with uvicorn:

```bash
.venv/bin/python -m uvicorn src.app.main:app --reload
```

## Smoke-test steps

1. Confirm ACS SMS settings are present only in local environment variables.
2. Start the API with uvicorn.
3. Submit a safe intake with `POST /intake/text`.
4. Confirm the returned case id can be used for follow-up verification.
5. Review the response fields for notification results.

## Latest smoke attempt

The local app was run with:

```text
APP_MODE=mock
SMS_PROVIDER=acs
DEMO_SUPPRESS_NOTIFICATIONS=false
```

`POST /intake/text` returned HTTP 200, and the response showed:

```text
notificationSmsSent=true
```

Handset SMS delivery was not confirmed.

## Expected results

After a successful live ACS SMS send-request path, the text intake response
should include:

```text
notificationSmsSent=true
```

`notificationEmailSent` behavior should remain independent of ACS SMS success or
failure.

Important: `notificationSmsSent=true` currently means the application/provider
send path accepted or completed without raising. It does not prove carrier
delivery to the handset.

## Failure-handling expectations

ACS SMS send failure should not crash intake processing. Failed SMS should leave:

```text
notificationSmsSent=false
```

The case should still be saved and returned for nurse review.

## Current blocker

- The initial ACS free trial number showed SMS unavailable, so it cannot be used
  for SMS delivery.
- A paid ACS toll-free number was acquired.
- Azure Portal showed U.S./Canada toll-free SMS verification is mandatory.
- Regulatory document submission was attempted, but Azure Portal returned
  "Server not responding / Unable to access regulatory documents right now."
- Live handset delivery is pending toll-free verification and external
  Azure/carrier regulatory workflow completion.

## MVP decision

Do not block the project on toll-free verification. Mock SMS inspection remains
the primary demo path for SMS. ACS SMS is integrated at the SDK/send-request
level, with handset delivery pending external verification.

## Safety notes

Do not commit secrets, connection strings, access keys, or real phone numbers.
Keep live ACS SMS values in local environment variables or a secure secret store
when that future path is implemented.

## Current limitations

- The Azure SMS SDK dependency has been added, but live handset delivery is
  still externally blocked.
- `create_acs_sms_client` is the factory boundary for the ACS SMS SDK client.
- live ACS SMS smoke testing has not been completed yet.
- Future enhancement: capture ACS message id/status or delivery report
  semantics.
