# Live Azure Speech Transcription Prerequisites

## Purpose and boundary

Use this runbook only to supervise one fixed-fictional Azure Speech proof through
`scripts/smoke_azure_speech_transcription.py`. The proof is non-production and
does not establish clinical readiness, general audio ingestion, or a voice
intake workflow. Application output remains advisory and human nurse review
remains mandatory.

The CLI reads only `tests/fixtures/fictional_speech_intake.wav`. That fixture is
repository-owned fictional audio with an application-owned expected transcript.
Do not substitute another file, patient recording, microphone input, downloaded
audio, or generated runtime audio.

## Required current-session evidence

Before requesting the live command, require all of the following:

1. Complete the applicable steps in
   [`daily-azure-operator-runbook.md`](daily-azure-operator-runbook.md), including
   current-session account verification and fresh `daily_environment_ready=true`
   evidence. Do not copy that procedure here or reuse historical evidence.
2. Identify the exact Azure Speech resource by an approved private operator
   record. Its ownership, enabled subscription, authorization, and intended
   disposable or retained lifecycle must be conclusive. Never adopt an
   unrelated, ambiguous, or unowned resource.
3. Confirm the optional Azure Speech SDK is available in the repository virtual
   environment. SDK visibility is not authentication or resource-access proof.
4. Create an ignored repository-root `.env.speech.local` containing these names:

   ```text
   SPEECH_PROVIDER
   AZURE_SPEECH_ENDPOINT
   AZURE_SPEECH_REGION
   AZURE_SPEECH_KEY
   ```

   Set `SPEECH_PROVIDER=azure`. Supply all values only through the ignored local
   file. Never paste values into commands, source, tests, documentation, output,
   screenshots, or evidence notes. Confirm the file remains ignored with
   `git check-ignore .env.speech.local`.
5. Obtain explicit operator approval for the exact live command below. Account
   readiness, resource ownership, and check-mode success do not imply approval.

Stop if any account, ownership, authorization, SDK, fixture, configuration, or
approval evidence is missing, stale, ambiguous, or unsafe. Do not create,
deploy, adopt, retag, repair, or delete a Speech resource to unblock this proof.

## Offline check

Run from the repository root:

```bash
set -o pipefail

.venv/bin/python scripts/smoke_azure_speech_transcription.py \
  --check \
  --json |
  .venv/bin/python -m json.tool
```

Check mode validates the fixed fixture, expected-transcript contract, result
schema, provider requirements, production factory/service compatibility, and
import-safe SDK visibility. It does not load credentials, construct a Speech
recognizer, submit audio, call Azure, invoke an intake route, persist a case,
record or send a notification, or mutate Azure. `sdk_available=false` fails the
check with `ok=false` and `category=sdk_unavailable`; live mode remains blocked.

## Supervised live command

After rechecking every prerequisite and receiving explicit approval, run exactly:

```bash
set -o pipefail

.venv/bin/python scripts/smoke_azure_speech_transcription.py \
  --config .env.speech.local \
  --live \
  --json |
  .venv/bin/python -m json.tool
```

The command permits one recognition attempt only. Do not retry, poll, select an
alternate fixture, fall back to mock, or change credentials after a failed or
ambiguous result.

Sanitized success requires these fields:

```text
ok=true
category=success
mode=live
fixture_valid=true
fictional_audio=true
provider=azure
adapter_constructed=true
transcription_attempted=true
transcript_valid=true
transcript_matches_expected=true
route_invoked=false
persistence_attempted=false
notification_attempted=false
azure_call_made=true
azure_mutation_made=false
```

The JSON never includes the recognized or expected transcript, audio bytes,
absolute fixture path, endpoint, region, key, resource identifier, raw SDK
object, cancellation details, exception text, or stack trace. A successful SDK
request with a transcript mismatch is a failure.

## Stop and cleanup

Stop after the first live result, whether it succeeds or fails. Do not diagnose
by exposing raw provider details and do not modify infrastructure, credentials,
routes, persistence, notifications, or audio handling in this workflow.

The CLI owns and closes its per-call SDK resources through the existing Speech
service and adapter. It creates, updates, and deletes no Azure resource. If the
approved Speech resource is disposable, follow its separately approved,
ownership-scoped lifecycle procedure; this CLI provides no cleanup command.
Never improvise deletion or treat the daily runbook as ownership proof for a
Speech resource it does not provision.

Patient data, real contact information, microphone input, uploads, intake-route
calls, case processing, persistence, notifications, ACS Calling Automation,
streaming, and production audio workflows are prohibited.
