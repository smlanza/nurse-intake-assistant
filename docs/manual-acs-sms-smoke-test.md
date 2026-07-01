# Manual ACS SMS Smoke Test Guide

## Purpose

This guide records the ACS SMS smoke-test checklist and current stopping point.
It includes an offline-safe `--check` preflight and remains a
placeholder/checklist for future live ACS SMS verification after external
toll-free verification, carrier, and Azure regulatory workflow are complete.

## Current status

Live ACS SMS is integrated far enough to reach the Azure Communication Services SMS
SDK/send-request path. Mock SMS remains the primary demo path. Live handset
delivery is not confirmed yet. Confirmed live ACS SMS handset delivery is not implemented yet.

ACS Email live smoke testing was previously completed successfully.

## Required preflight configuration

The safe preflight and future live ACS SMS smoke testing use:

```bash
SMS_PROVIDER=acs
ACS_SMS_CONNECTION_STRING=endpoint=https://placeholder-resource.communication.azure.com/;accesskey=placeholder-secret
ACS_SMS_FROM_PHONE_NUMBER=+15555550100
NURSE_NOTIFICATION_PHONE_NUMBER=+15555550123
DEMO_SUPPRESS_NOTIFICATIONS=false
```

Use placeholder values only in docs and tests. Do not paste or commit real ACS
connection strings, access keys, provider credentials, real phone numbers, or
real PHI.

## Safe preflight command

Run the ACS SMS configuration preflight before starting any manual SMS delivery
attempt:

```bash
python scripts/smoke_acs_sms.py --check
```

Required environment variables:

- `SMS_PROVIDER=acs`
- `ACS_SMS_CONNECTION_STRING`
- `ACS_SMS_FROM_PHONE_NUMBER`
- `NURSE_NOTIFICATION_PHONE_NUMBER`

Preflight success means the required settings are present for the ACS SMS
provider boundary and optional Azure Communication SMS SDK visibility was
reported. It does not prove handset delivery because it creates no ACS SMS
client, makes no Azure network call, and sends no SMS.

Preflight failure means one or more required settings are missing or
`SMS_PROVIDER` is not set to `acs`. The script prints only variable names and
safe next-step hints; it must not print configured connection strings, phone
numbers, stack traces, or raw exception details.

Live handset delivery remains deferred until toll-free verification, carrier,
and Azure regulatory workflow are complete.

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
Do not paste those values into docs, tests, logs, prompts, or commits. Keep live
ACS SMS values in local environment variables or a secure secret store when
that future path is implemented.

Restore mock defaults after any local ACS SMS preparation:

```bash
SMS_PROVIDER=mock
ACS_SMS_CONNECTION_STRING=
ACS_SMS_FROM_PHONE_NUMBER=
NURSE_NOTIFICATION_PHONE_NUMBER=
```

Mock SMS remains the default behavior for local demo and automated tests.

## Current limitations

- The Azure SMS SDK dependency has been added, but live handset delivery is
  still externally blocked.
- `create_acs_sms_client` is the factory boundary for the ACS SMS SDK client.
- live ACS SMS smoke testing has not been completed yet.
- Future enhancement: capture ACS message id/status or delivery report
  semantics.
