# Manual Azure Speech Smoke Test

## Purpose

Use this guide for the offline-safe Azure Speech proof check. The authoritative
prerequisites and supervised-command procedure remain in
`docs/runbooks/live-azure-speech-transcription-prerequisites.md`.

The standalone provider boundary is live-proven for one repository-owned
fixed-fictional WAV through the production Speech factory, service, and Azure
SDK adapter. Exactly one recognition attempt returned the application-owned
expected normalized text. Do not rerun that live command merely to reconfirm
the documented result.

This is not route-integrated audio processing, general Speech reliability
validation, clinical validation, or production clinical use. Human nurse review
remains mandatory for application-generated output.

## Safe Defaults And Local Configuration

Normal development, tests, demos, and application routes keep the safe default:

```bash
SPEECH_PROVIDER=mock
```

The normal FastAPI routes accept text or already-transcribed voicemail text
only. They do not invoke the Speech provider.

The Speech-specific `.env.speech.local.example` contains placeholder-only names
for `SPEECH_PROVIDER`, `AZURE_SPEECH_ENDPOINT`, `AZURE_SPEECH_REGION`, and
`AZURE_SPEECH_KEY`. Real values belong only in the ignored, uncommitted,
secret-bearing `.env.speech.local` file. Do not display, copy, diff, stage, or
commit that file.

## Offline Check

Run only the offline check during ordinary verification:

```bash
set -o pipefail

.venv/bin/python scripts/smoke_azure_speech_transcription.py \
  --check \
  --json | \
  .venv/bin/python -m json.tool
```

Check mode validates the repository-owned fictional fixture, expected-text
contract, result schema, production factory/service compatibility, and SDK
visibility. It loads no credentials, constructs no Speech adapter or
recognizer, performs no transcription, makes no Azure or network call, invokes
no intake route, persists no case, attempts no notification, and mutates no
Azure resource.

## Proven And Deferred Boundaries

The standalone proof made one Azure call and no Azure mutation. It used no
intake route, persistence, notification, or clinical-processing path and did
not expose the transcript or provider configuration.

The following remain deferred:

- Audio upload and microphone input
- ACS recording ingestion and transcription
- ACS Calling Automation and general voice intake
- Streaming transcription
- Audio retention and cleanup
- Route-integrated and production clinical audio workflows

Use fictional repository-owned audio only. Do not use PHI, patient recordings,
real contact information, or downloaded/runtime-generated replacement audio.
Mock Speech remains the safe default.
