# Manual Foundry Smoke Test

Use this checklist for a future manual Azure AI Foundry structured extraction
smoke test. The current automated test suite must remain offline and must not
call Azure.

Current status:

- `AI_PROVIDER=mock` remains the safe local default.
- The Foundry prompt/schema/parser contract is implemented and tested offline.
- `FoundryAiService` can use an injected fake client through
  `complete_structured_extraction(prompt, model_deployment_name)`.
- The Foundry live client scaffold is opt-in and matches the fake-client seam.
- A real Azure AI Foundry SDK call is still deferred until a future live
  implementation slice.

Do not use real patient data, real phone numbers, real email addresses,
connection strings, secrets, provider credentials, or PHI in this smoke test.

## Prerequisites

Future live smoke testing will require:

- Azure AI Foundry project
- Compatible deployed model
- Project endpoint
- Model deployment name
- Future Azure authentication method selected by the live implementation slice
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

Run this only after a future slice implements the live Azure AI Foundry SDK
adapter.

1. Confirm `git status` is clean.
2. Confirm the full test suite passes in mock/offline mode.
3. Set the Foundry environment variables locally.
4. Set `AI_PROVIDER=foundry`.
5. Keep `EMAIL_PROVIDER=mock` and `SMS_PROVIDER=mock` unless separately testing
   ACS notifications.
6. Start the app locally.
7. Submit a fictional `POST /intake/text` medication refill intake.
8. Submit a fictional urgent symptom intake.
9. Submit a fictional incomplete intake missing callback number.
10. Verify each case response includes expected extraction, summary, advisory
    urgency, and missing-field behavior.
11. Verify notification behavior remains controlled/mock unless ACS is being
    tested separately.
12. Restore `AI_PROVIDER=mock`.
13. Rerun the full test suite.
14. Document the result in `docs/progress.md`.
