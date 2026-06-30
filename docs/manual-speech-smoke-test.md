# Manual Azure Speech Smoke-Test Preparation

## Purpose

Use this guide to prepare for a future manual Azure Speech transcription smoke
test while keeping the current project offline-safe. This slice adds a
configuration preflight only. It does not implement live audio upload, phone
intake, ACS call automation, or Azure Speech transcription.

The automated test suite must remain offline and deterministic. It must not
call Azure Speech or require Azure credentials.

## Prerequisites

Future manual/live testing still requires:

- Azure Speech resource
- Azure Speech endpoint
- Azure Speech region
- Local authentication and SDK setup appropriate for the live environment
- A later implementation slice that explicitly adds live transcription

The current CLI can only verify local configuration and optional SDK package
visibility.

## Safe Environment Variables

Keep mock mode as the default for normal development and tests:

```bash
SPEECH_PROVIDER=mock
```

For a manual preflight only, use placeholders like these in your local shell or
uncommitted `.env` file:

```bash
SPEECH_PROVIDER=azure
AZURE_SPEECH_ENDPOINT=https://demo-speech-resource.cognitiveservices.azure.com/
AZURE_SPEECH_REGION=demo-region
```

Do not commit real endpoints tied to production resources, keys, secrets,
connection strings, real phone numbers, real email addresses, or real patient
data.

## Run The Preflight

Run:

```bash
python scripts/smoke_speech_transcription.py --check
```

The `--check` mode validates that:

- `SPEECH_PROVIDER=azure`
- `AZURE_SPEECH_ENDPOINT` is present
- `AZURE_SPEECH_REGION` is present
- The optional Azure Speech SDK package appears importable or unavailable

The SDK check is informational. Missing SDK support is reported clearly and
does not by itself make the preflight fail.

## What Successful Preflight Means

A successful preflight means local Azure Speech settings are present and the
manual setup is ready for a future live transcription slice.

It also confirms: No Speech client was created, it did not process audio, no
audio was uploaded, no FastAPI route was called, no cases were persisted, no
notifications were sent, and the script did not make an Azure network call.

## What It Does Not Prove

This preflight does not prove:

- Azure Speech credentials or resource access work
- Audio can be uploaded or transcribed
- Phone intake or ACS call automation works
- The FastAPI intake contract changed
- Notifications were sent or delivered
- The app is production-ready clinical software

Manual/live Azure Speech transcription remains deferred until a later explicit
implementation slice.

## Roll Back To Mock Mode

After any manual preparation, restore the safe local default:

```bash
SPEECH_PROVIDER=mock
```

Normal local tests and demos should continue to use already-transcribed text
with the mock/offline Speech provider boundary.

## Safety Notes

- Use fictional/demo-only sample text.
- Do not use PHI or real patient data.
- Do not use real phone numbers or real email addresses.
- Do not commit secrets, keys, credentials, or live provider settings.
- This capstone project is for local demo and AI-103 preparation only, with no
  production clinical use.
