# Manual Foundry Smoke Test

Use this checklist for a future manual Azure AI Foundry structured extraction
smoke test. The current automated test suite must remain offline and must not
call Azure.

Current status:

- `AI_PROVIDER=mock` remains the safe local default.
- The Foundry prompt/schema/parser contract is implemented and tested offline.
- `FoundryAiService` can use an injected fake client through
  `complete_structured_extraction(prompt, model_deployment_name)`.
- The Foundry live client adapter is opt-in, matches the fake-client seam, and
  uses lazy SDK imports/client construction.
- `scripts/smoke_foundry_extraction.py` provides an opt-in manual CLI scaffold
  with separate preflight and explicit live smoke modes.
- The script can load a local `.env.foundry.local` file for its own process
  with `--env-file`; existing shell environment variables still win.
- Automated tests use fake SDK/client objects only.
- A real Azure AI Foundry smoke test has not been performed yet.

Do not use real patient data, real phone numbers, real email addresses,
connection strings, secrets, provider credentials, or PHI in this smoke test.

## Prerequisites

Future live smoke testing still requires:

- Azure AI Foundry project
- Compatible deployed model
- Azure AI Foundry project endpoint
- Model deployment name
- Azure authentication method and SDK package setup appropriate for the live
  environment
- Local environment variables, either exported in the shell or stored in a
  local `.env.foundry.local` copied from `.env.foundry.local.example`:

```bash
AI_PROVIDER=foundry
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=
AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME=
```

`AZURE_AI_FOUNDRY_PROJECT_ENDPOINT` is expected to be the Azure AI Foundry
project endpoint shape used by the current live adapter, classified as
`services.ai.azure.com`. An Azure OpenAI endpoint shape such as
`openai.azure.com` is a different client/auth path and is not wired into this
manual smoke script. If an Azure OpenAI endpoint is needed later, add that path
as a separate explicit slice rather than putting it in
`AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`.

Keep notification providers in mock mode unless the smoke test is explicitly
combined with a separate ACS notification test:

```bash
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
```

Prefer the env-file form so Foundry settings do not leak into normal pytest or
local demo shells:

```bash
python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --check
python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live
python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live --diagnose
```

Inline shell environment variables still work for a short manual session:

```bash
AI_PROVIDER=foundry \
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://your-foundry-project-endpoint.example.invalid \
AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME=your-model-deployment-name \
python scripts/smoke_foundry_extraction.py --check
```

The `--check` command validates local Foundry configuration and reports
optional SDK visibility without creating the AI service, making a model call,
persisting cases, sending notifications, writing to Cosmos, or calling FastAPI
routes.

The `--live` command is the only mode intended to make a live Foundry call. It
does not persist cases, does not send notifications, does not write to Cosmos,
does not call FastAPI routes, and does not require the FastAPI server to be
running. It prints a small safe result summary for fictional input only.

If `--live` fails, the script prints the existing generic safe failure message,
then a safe diagnostic category. It intentionally does not print raw exception
details, stack traces, endpoints, deployment names, prompts, tokens, connection
strings, or secrets.

Safe diagnostic categories include:

- client construction failed
- Azure credential unavailable
- authentication failed
- authorization/RBAC failed
- deployment or model not found
- endpoint rejected request
- rate limited
- model response parsing failed
- unknown live smoke failure

Common next checks are endpoint type, deployment name, Azure login/RBAC, SDK
compatibility, and whether the model response still matches the structured JSON
contract.

## Troubleshoot With Diagnose

Use `--live --diagnose` only for a manual troubleshooting pass after `--check`
passes but `--live` fails with a safe category:

```bash
python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live --diagnose
```

Diagnostic mode prints sanitized status only: required config names present
yes/no, endpoint shape classification (`services.ai.azure.com`,
`openai.azure.com`, or `unknown`), deployment name present yes/no, SDK import
availability, live client mode (`foundry-project-endpoint`), endpoint/client
compatibility (`compatible`, `incompatible`, or `unknown`), Azure CLI token
probe status, failure phase, sanitized top-level and root exception class names,
bounded exception-chain class names, safe HTTP status category (`401`, `403`,
`404`, `429`, `5xx`, or `unknown`), the existing safe failure category, and the
existing safe next-step hint.

If the endpoint/client combination is incompatible or unknown, `--live` fails
before request execution and prints a safe next-step hint without making an
Azure call.

It still redacts endpoint values, deployment names, prompts, model responses,
tokens, credentials, connection strings, raw exception messages, raw response
bodies, request URLs, authorization headers, tracebacks, stack traces, real
emails, real phone numbers, and PHI. This is manual diagnostic output only; it
does not make the app production-ready and does not change automated tests.

One known manual failure pattern is a 401 authentication/token/audience failure.
Treat that as an Azure login, endpoint type, token audience, or RBAC check; do
not paste raw exception details or credentials into project files.

Restore mock defaults afterward:

```bash
AI_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
```

If `.env.foundry.local` was used, no shell restore should be needed. Verify
normal mock mode before running the full suite:

```bash
python scripts/smoke_foundry_extraction.py --check
```

That command should fail safely unless Foundry settings are intentionally still
present in the shell.

## Safe Fictional Inputs

Medication refill:

```text
Demo patient Alex Morgan requests a callback about a routine medication refill.
Callback number is demo-callback-001. No chest pain, shortness of breath, or
severe symptoms reported.
```

Urgent symptom example:

```text
My name is Jordan Smith. DOB: 1970-09-09. My callback number is
demo-callback-002. I have chest pain and shortness of breath.
```

Incomplete intake:

```text
My name is Alex Lee. DOB: 1975-03-20. I need a medication refill.
```

## Expected Validation Behavior

A successful future live response should:

- Map into the existing `ExtractionSummaryResult` model.
- Map into the existing `UrgencyClassificationResult` model.
- Keep urgency advisory only.
- Make clear that nurse review is required.
- Populate `missing_fields` when required data is missing.
- Preserve uncertainty in `uncertain_fields` when the model is unsure.

Invalid model output should fail clearly through the contract parser:

- Malformed JSON should fail with a clear contract error.
- Non-object JSON should fail with a clear contract error.
- Unsupported urgency values should fail with a clear contract error.

## Non-Goals

This smoke test does not cover:

- ACS phone intake
- Azure Speech
- Key Vault
- App Service hosting
- App Service authentication
- SMS delivery tracking
- Retry or durable processing
- Production clinical use
- PHI or real patient data
- Automated tests that call Azure

## Future Live Checklist

Run this only after the live Azure AI Foundry SDK package and authentication
are configured locally.

1. Confirm `git status` is clean.
2. Confirm the full test suite passes in mock/offline mode.
3. Copy `.env.foundry.local.example` to `.env.foundry.local` and fill in local
   Foundry placeholders, or set temporary shell variables for this session.
4. Set `AI_PROVIDER=foundry` only for the manual smoke command.
5. Keep `EMAIL_PROVIDER=mock` and `SMS_PROVIDER=mock` unless separately testing
   ACS notifications.
6. Run `python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --check`.
7. Run `python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live`.
8. Optionally start the app locally for a separate manual API check.
9. Submit a fictional `POST /intake/text` medication refill intake only if the
   separate API check is in scope.
10. Submit a fictional urgent symptom or incomplete intake only if explicitly
   extending the manual smoke pass.
11. Verify each result includes expected extraction, summary, advisory
    urgency, and missing-field behavior.
12. Verify notification behavior remains controlled/mock unless ACS is being
    tested separately.
13. Restore or verify `AI_PROVIDER=mock`.
14. Rerun the full test suite.
15. Document the result in `docs/progress.md`.
