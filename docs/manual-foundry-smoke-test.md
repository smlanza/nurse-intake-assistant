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
  that exercises the configured Foundry provider with fictional input only.
- Automated tests use fake SDK/client objects only.
- A real Azure AI Foundry smoke test has not been performed yet.

Do not use real patient data, real phone numbers, real email addresses,
connection strings, secrets, provider credentials, or PHI in this smoke test.

## Prerequisites

Future live smoke testing still requires:

- Azure AI Foundry project
- Compatible deployed model
- Project endpoint
- Model deployment name
- Azure authentication method and SDK package setup appropriate for the live
  environment
- Local environment variables:

```bash
AI_PROVIDER=foundry
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=
AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME=
```

Keep notification providers in mock mode unless the smoke test is explicitly
combined with a separate ACS notification test:

```bash
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
```

After a future live environment is configured, run the opt-in script manually:

```bash
python scripts/smoke_foundry_extraction.py --check
python scripts/smoke_foundry_extraction.py
```

The `--check` command validates local Foundry configuration and optional SDK
availability without creating the AI service, making a model call, persisting
cases, sending notifications, or calling FastAPI routes.

The default command runs the opt-in smoke test. It does not persist cases, does
not send notifications, and does not call FastAPI routes. It prints a small
safe result summary for fictional input only.

## Safe Fictional Inputs

Medication refill:

```text
My name is Jane Doe. DOB: 1980-04-15. My callback number is demo-callback-001.
I need a medication refill.
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
3. Set the Foundry environment variables locally.
4. Set `AI_PROVIDER=foundry`.
5. Keep `EMAIL_PROVIDER=mock` and `SMS_PROVIDER=mock` unless separately testing
   ACS notifications.
6. Run `python scripts/smoke_foundry_extraction.py --check`.
7. Run `python scripts/smoke_foundry_extraction.py`.
8. Optionally start the app locally for a separate manual API check.
9. Submit a fictional `POST /intake/text` medication refill intake only if the
   separate API check is in scope.
10. Submit a fictional urgent symptom or incomplete intake only if explicitly
   extending the manual smoke pass.
11. Verify each result includes expected extraction, summary, advisory
    urgency, and missing-field behavior.
12. Verify notification behavior remains controlled/mock unless ACS is being
    tested separately.
13. Restore `AI_PROVIDER=mock`.
14. Rerun the full test suite.
15. Document the result in `docs/progress.md`.
