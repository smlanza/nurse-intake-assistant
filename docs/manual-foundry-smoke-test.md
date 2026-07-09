# Manual Foundry Smoke Test

Use this checklist for the manual Azure OpenAI / Foundry structured extraction
smoke test. The current automated test suite must remain offline and must not
call Azure.

Current status:

- `AI_PROVIDER=mock` remains the safe local default.
- The Foundry prompt/schema/parser contract is implemented and tested offline.
- `FoundryAiService` can use an injected fake client through
  `complete_structured_extraction(prompt, model_deployment_name)`.
- The Foundry live client adapter is opt-in, matches the fake-client seam, and
  uses lazy SDK imports/client construction.
- `scripts/smoke_foundry_extraction.py` provides an opt-in manual CLI with
  separate preflight and explicit live smoke modes.
- The script can load a local `.env.foundry.local` file for its own process
  with `--env-file`; existing shell environment variables still win.
- Automated tests use fake SDK/client objects only.
- The validated live path is `--live-client-mode azure-openai-endpoint` with
  fictional routine medication-refill input. It completed structured extraction
  and urgency classification, including advisory disclaimer output.
- The `foundry-project-endpoint` path remains available for diagnosis but may
  fail depending on project endpoint auth/client behavior.

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
AZURE_OPENAI_ENDPOINT=
AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME=
```

The smoke script has two explicit live client modes:

- `foundry-project-endpoint` is the default. It uses
  `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`, expected to classify as
  `services.ai.azure.com`.
- `azure-openai-endpoint` is optional. It uses `AZURE_OPENAI_ENDPOINT`,
  expected to classify as `openai.azure.com`.

Do not put an Azure OpenAI endpoint in `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`.
Both modes reuse `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`; the value is never
printed. The Azure OpenAI endpoint smoke path uses Microsoft Entra bearer-token
provider auth through `DefaultAzureCredential` and the SDK token provider helper.
It uses the Azure OpenAI v1 path shape internally, normalizing
`AZURE_OPENAI_ENDPOINT` to a base URL ending in `/openai/v1/`. The endpoint may
be provided with or without `/openai/v1`; the deployment name setting is passed
as the OpenAI `model` parameter.
Diagnostics report only the safe auth mode label
`entra-bearer-token-provider` and token scope category
`cognitiveservices.default`; token values and token provider details are never
printed. API key support is not added.

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
python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live --diagnose --live-client-mode azure-openai-endpoint
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

The default `--live` mode preserves the Foundry project endpoint path. Try
`--live --diagnose --live-client-mode azure-openai-endpoint` only after
`--check` passes and the default project endpoint mode reaches request
execution but fails with a safe category such as authentication failed. The
manual path validated for this capstone is `azure-openai-endpoint`.

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

## Foundry Agent Smoke CLI

Use `scripts/smoke_foundry_agent.py` only for manual Azure AI Foundry Agent
validation with fictional data only. The default local demo remains
mock/offline: `AGENT_PROVIDER=mock`, `AI_PROVIDER=mock`, `APP_MODE=mock`,
`EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock`, and `SPEECH_PROVIDER=mock`.

Create a local `.env.foundry-agent.local` from
`.env.foundry-agent.local.example` or export temporary shell variables:

```bash
AGENT_PROVIDER=foundry-agent
AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT=<your-foundry-agent-project-endpoint>
AZURE_AI_FOUNDRY_AGENT_ID=<your-foundry-agent-id>
```

The script also preserves the existing `AGENT_PROVIDER=foundry` smoke alias.
Prefer `AGENT_PROVIDER=foundry-agent` for new manual checks.

## Foundry Agent Instruction Pack

Before configuring the Azure AI Foundry Agent, print the versioned instruction
pack:

```bash
python scripts/smoke_foundry_agent.py --print-agent-instructions
```

This command is offline. It does not load Azure settings, does not require an
env file, does not create a Foundry Agent client, does not invoke an agent, and
does not call Azure.

The printed instructions are safe to copy into Azure AI Foundry Agent
configuration. They include:

- instruction version
- copyable agent instructions
- expected JSON shape for the local `NurseIntakeAgent` contract
- fictional test input
- safe manual validation command reminders

The instruction pack is intended to align manual Azure Agent configuration with
the local `NurseIntakeAgent` output contract. Live verification still requires
running `--live --json` manually after `--check` passes.

The instruction pack and smoke success do not make the app production clinical
software. Human nurse review remains mandatory before clinical action.

Example `--check` command:

```bash
python scripts/smoke_foundry_agent.py --check
```

Example `--env-file` check command:

```bash
python scripts/smoke_foundry_agent.py --env-file .env.foundry-agent.local --check
```

Shell environment variables override env-file values. The env file is loaded
for the script process only and values are reported only as configured/missing.
Endpoint values and agent IDs are not printed.

`--check` does not call Azure. No Foundry Agent client is created in --check
mode, no agent invocation is made, no cases are persisted, and no email or SMS
is sent. It validates required settings, reports optional SDK visibility, and
prints a sanitized environment readiness summary.
In plain terms: --check does not call Azure.

The check summary reports only safe metadata:

- provider
- mode: `check`
- ready/not-ready status through the message text
- required setting names present
- required setting names missing
- optional setting names present, when applicable
- SDK availability
- the static `--live --json` command hint
- a sanitized recommended next step

Required setting names for manual Foundry Agent live validation are:

- `AGENT_PROVIDER`
- `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT` or
  `AZURE_AI_FOUNDRY_PROJECT_ENDPOINT`
- `AZURE_AI_FOUNDRY_AGENT_ID`

If the required settings and optional SDK package are visible, `--check`
recommends running the manual live JSON validation command. If settings are
missing, it recommends adding only the missing variable names. If the SDK is
not visible, it recommends installing the optional SDK dependencies without
changing local mock/demo behavior.

Example `--live` command:

```bash
python scripts/smoke_foundry_agent.py --live
```

Example `--env-file` live command:

```bash
python scripts/smoke_foundry_agent.py --env-file .env.foundry-agent.local --live
```

Example sanitized JSON live command:

```bash
python scripts/smoke_foundry_agent.py --env-file .env.foundry-agent.local --live --json
```

`--live` remains manual and opt-in. It is the only mode intended to construct
the Foundry Agent path and may call Azure. It uses the script's built-in
fictional medication-refill intake only, does not send notifications, does not
write to Cosmos, does not call FastAPI routes, and does not require the FastAPI
server to be running.
In plain terms: --live remains manual and opt-in.

`--live --json` prints a deterministic sanitized result with these fields:
`ok`, `mode`, `provider`, `category`, `message`, `agent_attempted`,
`agent_output_valid`, `fallback_used`, `fields_present`, and
`recommended_next_step`. It does not print raw exception messages, stack
traces, full endpoints, agent IDs, bearer tokens, prompts, instructions, raw
model output, connection strings, real patient/contact data, email addresses,
phone numbers, or PHI.

When `AGENT_PROVIDER=foundry-agent` or `AGENT_PROVIDER=foundry` is configured,
`/demo/status`, `/ops`, and `python scripts/preflight.py --foundry-agent` may
show this same manual validation command as a static safe hint. Those readiness
surfaces remain configuration-only: showing the command does not create a
Foundry Agent client, invoke an agent, or call Azure.

If live validation fails, the plain output path prints a sanitized failure
category and a next-step hint. The JSON output path reports the same kind of
safe result as structured data.

Safe Foundry Agent live failure categories include:

- missing_configuration
- sdk_unavailable
- authentication_or_authorization_failed
- azure_request_failed
- contract_invalid
- response_parse_failed
- unexpected_error

For `--live --json`, `response_parse_failed` means the agent did not return
parseable structured JSON. `contract_invalid` means the agent returned
parseable structured data that did not match the expected extraction contract
or the parsed result violated the `NurseIntakeAgent` output contract.
`authentication_or_authorization_failed` points to Azure login, tenant, or RBAC
problems. `azure_request_failed` means the live request reached the Azure-facing
path but failed with a non-auth request category. `unexpected_error` is a
sanitized catch-all for failures outside the known configuration, SDK, auth,
request, parsing, and contract buckets.

`category=success` means the manual smoke command received an agent result that
parsed and satisfied the local Nurse Intake Agent contract for the built-in
fictional medication-refill intake. It does not make the app production
clinical software, does not remove the nurse-review requirement, does not
enable `/demo` to call Azure, and does not validate hosting, auth, Key Vault,
Speech, phone intake, durable retry, ACS delivery, or production frontend
behavior.

Do not claim live Foundry Agent behavior is verified unless this manual
`--live` path has been run successfully in the intended Azure environment.
Passing `--check` means local configuration is present and no Azure call was
made. Live verification still requires running `--live --json` manually.

After any manual live check, return the local demo to mock/offline mode:

```bash
AGENT_PROVIDER=mock
```

## Troubleshoot With Diagnose

Use `--live --diagnose` only for a manual troubleshooting pass after `--check`
passes but `--live` fails with a safe category:

```bash
python scripts/smoke_foundry_extraction.py --env-file .env.foundry.local --live --diagnose
```

Diagnostic mode prints sanitized status only: required config names present
yes/no, endpoint shape classification (`services.ai.azure.com`,
`openai.azure.com`, or `unknown`), deployment name present yes/no, SDK import
availability, required endpoint present yes/no, live client mode
(`foundry-project-endpoint` or `azure-openai-endpoint`), endpoint/client
compatibility (`compatible`, `incompatible`, or `unknown`), Azure CLI token
probe status, Azure OpenAI API path mode (`openai-v1`), base URL shape category
(`openai.azure.com/openai/v1`), auth mode, safe token scope category, and model
parameter source when that mode is selected, failure phase, sanitized top-level
and root exception class names, bounded exception-chain class names, safe HTTP
status category (`401`, `403`, `404`, `429`, `5xx`, or `unknown`), the existing
safe failure category, and the existing safe next-step hint.

If the endpoint/client combination is incompatible or unknown, `--live` fails
before request execution and prints a safe next-step hint without making an
Azure call.

If `azure-openai-endpoint` mode reaches request execution and still reports a
sanitized `401` after this bearer-token-provider path, treat it as likely Azure
RBAC/resource authentication configuration rather than a local endpoint-shape
problem.

If it reports a sanitized `404` after this v1 path, check whether the deployment
is reachable behind that Azure OpenAI endpoint and supports the called API
shape.

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

A successful live smoke response should:

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
