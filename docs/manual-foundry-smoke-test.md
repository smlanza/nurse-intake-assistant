# Manual Foundry Smoke Test

## Disposable Foundry Infrastructure

The recommended daily path deploys only one Foundry resource, one project, and
one explicitly configured model deployment through `infra/foundry-only.bicep`.
It reuses the same module as optional Foundry support in `infra/main.bicep`.

Run the infrastructure CLI in this order: offline `--check`; optional
non-mutating `--what-if` against an existing resource group; explicit
`--live --json`. Live creates or reuses the group but does not create the Nurse
Intake Agent, edit `.env.foundry-agent.local`, or clean up. Copy the returned
endpoint and deployment name manually. Model/version/provider/SKU/region/quota
values must be valid for the subscription.

```bash
az group delete --name <resource-group-name> --yes --no-wait
```

Tests remain offline, nurse review stays mandatory, and no production clinical
claim is made.

The Foundry-only deployment and subsequent read-only verification succeeded for
the AIServices account, project, endpoint format, and model deployment. Azure
returned the project resource name as `<account>/<project>`. No agent was
created, no inference ran, and cleanup remains a manual operator decision.

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
AZURE_AI_FOUNDRY_AGENT_ENDPOINT=<your-stable-agent-openai-protocol-endpoint>
AZURE_AI_FOUNDRY_AGENT_NAME=<your-foundry-agent-name>
AZURE_AI_FOUNDRY_AGENT_VERSION=<your-foundry-agent-version>
```

The script also preserves the existing `AGENT_PROVIDER=foundry` smoke alias.
Prefer `AGENT_PROVIDER=foundry-agent` for new manual checks.

### Foundry Agent credential boundary

Foundry Agent invocation, immutable-version verification, and prompt-agent
provisioning share one lazy `DefaultAzureCredential` boundary. Local
development can continue to use the existing Azure developer-login credential
chain. An Azure-hosted runtime with a system-assigned managed identity needs no
client-ID setting. For a user-assigned managed identity, set the optional
`AZURE_AI_FOUNDRY_MANAGED_IDENTITY_CLIENT_ID` identifier. The setting identifies
the managed identity; it is not a credential or secret.

This boundary introduces no API key or client secret. Assigning the minimum
required Foundry project role remains an operator/infrastructure
responsibility. This slice did not deploy a managed identity, assign a role, or
run a live Azure authentication test. `AGENT_PROVIDER=mock` remains the safe
default, human nurse review remains mandatory, and managed-identity readiness
does not establish production or clinical readiness.

### App Service-hosted identity verification of the Foundry prompt agent

After separately verifying Foundry infrastructure, deploying and checking the
Web App, reviewing hosted readiness, deploying the Consumer assignment, and
verifying that exact assignment read-only, run the packaged operation from the
deployed Web App environment:

```bash
set -o pipefail

python -m src.app.operations.verify_hosted_foundry_agent --check --json |
  python -m json.tool
python -m src.app.operations.verify_hosted_foundry_agent --live --json |
  python -m json.tool
```

The existing settings must contain the agent project endpoint, stable endpoint,
name, immutable version, and model deployment name. Check mode validates those
contracts and SDK visibility without reading hosted markers or creating a
credential/client. Only explicit live JSON mode requires nonblank
`WEBSITE_INSTANCE_ID`, `IDENTITY_ENDPOINT`, and sensitive `IDENTITY_HEADER`, then creates `ManagedIdentityCredential()` with no
client ID or fallback credential chain. It reads the configured agent and exact
version, then reuses the existing stable endpoint, Responses protocol,
immutable routing, model, and centralized instruction comparisons.

This operation never creates a Responses client, sends a prompt, invokes an
agent, provisions or updates a version, repairs RBAC, retries, polls, or exposes
an HTTP diagnostic route. Success recommends the later separate fictional-data
hosted invocation but does not start it. Results contain no endpoint, hostname,
identity, resource ID, environment value, token, raw SDK response, or exception.
The command closes the project client and credential on success and failure;
cleanup errors are suppressed without replacing the verification result.
This repository has not run the live command and makes no hosted authentication
or authorization claim.

Here, “hosted” means the command runs inside Azure App Service. It verifies a
Foundry prompt agent and is not the Microsoft Foundry Hosted Agents runtime.

```text
Foundry infrastructure verification
-> Web App infrastructure deployment
-> Web App configuration verification
-> Web App code deployment
-> hosted readiness verification
-> Foundry Agent Consumer RBAC deployment
-> read-only RBAC assignment verification
-> hosted managed-identity Foundry Agent verification
-> later, separate fictional-data hosted agent invocation
```

Each arrow is a separate operator-reviewed proof. Keep application, AI, agent,
email, SMS, and Speech providers at their mock defaults and keep hosted
notifications suppressed. Human nurse review and the non-production clinical
boundary remain mandatory.

The application Foundry Agent adapter prefers the current stable per-agent
OpenAI protocol endpoint:

- validate `AZURE_AI_FOUNDRY_AGENT_ENDPOINT` as a complete HTTPS
  `/agents/{name}/endpoint/protocols/openai` base before any SDK/client work
- bind that endpoint to the configured project hostname and project path and
  to the exact configured agent-name path segment; reject credentials, ports,
  query strings, fragments, percent-encoded values, and ambiguous paths
- construct `AIProjectClient` with the project endpoint, shared credential,
  and `allow_preview=True`, then use the SDK-supported
  `get_openai_client(agent_name=<configured-agent-name>)` operation
- let the SDK construct the hosted-agent base URL, authentication and preview
  headers, and API-version query instead of overriding them manually
- verify that the endpoint's server-side version-selection rules contain the
  configured immutable version before guarded invocation
- send the existing fictional intake prompt through `responses.create`
- parse the returned output text with the local `NurseIntakeAgent` contract

`AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT` remains separate and is used for
provisioning and read-only metadata/version verification. The older
project-endpoint agent-reference invocation is compatibility-only and requires
`AZURE_AI_FOUNDRY_AGENT_USE_PROJECT_ENDPOINT_COMPATIBILITY=true` with the stable
endpoint setting blank. When both are configured, the stable endpoint wins.
`AZURE_AI_FOUNDRY_AGENT_ID` is not required for invocation.

## Programmatic Prompt-Agent Provisioning And Separate Invocation

Install the optional current Foundry project SDK without changing the default
mock-demo dependencies:

```bash
python -m pip install -r requirements-foundry-agent.txt
```

The explicit provisioning workflow uses `azure-ai-projects` 2.x:

```text
centralized build_nurse_intake_agent_instructions()
-> PromptAgentDefinition
-> AIProjectClient.agents.list_versions(... latest ...)
-> reuse an identical model/instruction definition
   OR AIProjectClient.agents.create_version() for a missing/changed definition
-> sanitized provisioning result (no invocation)
```

First run the completely offline readiness check. It reads configuration and
checks SDK visibility, but creates no credential/client/version and calls no
Azure service:

```bash
set -o pipefail

python scripts/deploy_foundry_agent.py --check --json |
  python -m json.tool
```

The model setting is `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`. Provisioning
does not require `AZURE_AI_FOUNDRY_AGENT_VERSION`: it reuses the latest version
when the configured model and centralized/versioned instructions match,
creates the agent when no version exists, and creates one updated immutable
version when the definition changed. Repeated identical runs do not create
duplicate versions. Automated tests inject fake clients and make no Azure
calls.

Live provisioning is explicitly opt-in and never invokes the agent:

```bash
set -o pipefail

python scripts/deploy_foundry_agent.py --live --json |
  python -m json.tool
```

The command prints exactly one sanitized JSON result with safe lifecycle and
presence booleans, the instruction version, a safe category/message, and the
recommended separate smoke step. It never prints endpoints, credentials,
agent names/IDs, model deployment names, instructions, prompts, SDK response
objects, raw exception bodies, or stack traces. Do not claim live provisioning
success until an operator runs the command and reviews `category=success`.

Use this exact manual sequence with the ignored local files and fictional
intake data only:

```bash
set -o pipefail

python scripts/verify_foundry_infra.py --json |
  python -m json.tool
python scripts/deploy_foundry_agent.py --check --json |
  python -m json.tool
python scripts/deploy_foundry_agent.py --live --json |
  python -m json.tool
python scripts/verify_foundry_agent.py --check --json |
  python -m json.tool
python scripts/verify_foundry_agent.py --live --json |
  python -m json.tool
python scripts/smoke_foundry_agent_intake.py --check --json --verify-agent-version |
  python -m json.tool
python scripts/smoke_foundry_agent_intake.py --env-file .env.foundry-agent.local --live --json --verify-agent-version |
  python -m json.tool
```

These are separate operator-controlled boundaries: read-only
infrastructure verification, offline provisioning validation, explicitly
opt-in prompt-agent provisioning, offline agent-version verification readiness,
read-only live agent-version verification, and explicitly opt-in invocation.
Supply the required verified infrastructure arguments and manually managed
ignored local environment values described below when running them.

`deploy_foundry_agent.py --check --json` is fully offline: it creates no Azure
client and makes no Azure call. `deploy_foundry_agent.py --live --json` is the
only prompt-agent provisioning operation; it may create, reuse, or update an
immutable Foundry prompt-agent version, but it never invokes the agent.
`verify_foundry_agent.py --check --json` is fully offline.
`verify_foundry_agent.py --live --json` performs read-only agent-object and
immutable-version lookups. It verifies `AgentDetails.id`, non-null
`instance_identity`, `agent_endpoint`, the exact version-selection rule, the
Responses protocol, name/version response contract, model deployment, and
centralized instructions. It never creates or updates a version, creates a
Responses client, or invokes the agent.

Use fictional intake data only. Human nurse review remains mandatory, and this
workflow does not establish production clinical readiness. Never commit
secrets, credentials, access or bearer tokens, raw endpoints, real contact
information, or patient data.

1. Populate ignored `infra/foundry-only.bicepparam`, then deploy or reuse the
   disposable infrastructure through the approved commands:

   ```bash
   set -o pipefail

   python scripts/deploy_foundry_infra.py --mode foundry-only --parameters infra/foundry-only.bicepparam --resource-group <resource-group> --location <location> --check
   python scripts/deploy_foundry_infra.py --mode foundry-only --parameters infra/foundry-only.bicepparam --resource-group <existing-resource-group> --location <location> --what-if --json |
     python -m json.tool
   python scripts/deploy_foundry_infra.py --mode foundry-only --parameters infra/foundry-only.bicepparam --resource-group <resource-group> --location <location> --live --json |
     python -m json.tool
   ```

2. Run read-only infrastructure verification with the sanitized deployment
   outputs:

   ```bash
   set -o pipefail

   python scripts/verify_foundry_infra.py --resource-group <resource-group> --project-endpoint <verified-project-endpoint> --model-deployment-name <verified-model-deployment-name> --json |
     python -m json.tool
   ```

3. Manually populate ignored `.env.foundry-agent.local` with
   `AGENT_PROVIDER=foundry-agent`, the verified project endpoint in
   `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT`, the verified model deployment in
   `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`, the intended agent name in
   `AZURE_AI_FOUNDRY_AGENT_NAME`, the complete stable agent endpoint in
   `AZURE_AI_FOUNDRY_AGENT_ENDPOINT`, and an existing
   `AZURE_AI_FOUNDRY_AGENT_VERSION` when required. Environment-file updates are
   always manual; no script in this workflow modifies the file automatically.
   Keep all application, AI, notification, and Speech providers at their mock
   defaults.

4. Run the offline provisioning check:

   ```bash
   set -o pipefail

   python scripts/deploy_foundry_agent.py --check --json |
     python -m json.tool
   ```

5. Run explicit live provisioning:

   ```bash
   set -o pipefail

   python scripts/deploy_foundry_agent.py --live --json |
     python -m json.tool
   ```

6. Review only the single sanitized JSON result. Provisioning may create a
   missing agent version, reuse an identical immutable version, or create one
   updated immutable version when the definition changed. It never invokes the
   agent. Confirm `ok=true`, `category=success`, `agent_invoked=false`, and
   exactly one of `agent_created`, `agent_reused`, or `agent_updated` is true.

7. In Foundry, inspect the resulting current agent object and manually set its
   name, immutable version, and complete OpenAI protocol endpoint in the ignored
   local environment file. The provisioning script does not edit environment
   files or print raw identifiers or endpoints.

8. Run the offline configured-version verification readiness check:

   ```bash
   set -o pipefail

   python scripts/verify_foundry_agent.py --check --json |
     python -m json.tool
   ```

9. Run the explicit read-only configured-version verification:

   ```bash
   set -o pipefail

   python scripts/verify_foundry_agent.py --live --json |
     python -m json.tool
   ```

   Confirm `ok=true`, `category=success`, `agent_identity_present=true`,
   `stable_endpoint_present=true`,
   `stable_endpoint_matches_configuration=true`,
   `version_selector_present=true`, `responses_protocol_present=true`,
   `immutable_version_verified=true`, `agent_definition_matches=true`,
   `agent_invoked=false`, and `azure_mutation_made=false`. These fields are
   established independently; compatibility-mode verification does not imply
   that a stable endpoint was verified. A null instance identity is reported
   as `legacy_agent_model`; recreate that agent through the existing
   prompt-agent provisioning workflow. The result never prints identity
   values, endpoints, names/versions, model names, instructions, credentials,
   or raw SDK responses.

10. The older direct-agent smoke remains available only for intentional
    project-endpoint compatibility diagnosis:

   ```bash
   set -o pipefail

   python scripts/smoke_foundry_agent.py --live --json |
     python -m json.tool
   ```

    Set `AZURE_AI_FOUNDRY_AGENT_USE_PROJECT_ENDPOINT_COMPATIBILITY=true` and
    leave `AZURE_AI_FOUNDRY_AGENT_ENDPOINT` blank only for this compatibility
    path. New operator validation should use the guarded application smoke.

12. Run the guarded application-level check and explicit live smoke. The check
    validates setting names and SDK visibility but creates no client and makes
    no Azure lookup or model/application invocation. The live command first
    reuses the same read-only immutable-version verifier; only an exact match
    permits the fixed fictional intake to enter the application pipeline:

    ```bash
    set -o pipefail

    python scripts/smoke_foundry_agent_intake.py --check --json --verify-agent-version |
      python -m json.tool
    python scripts/smoke_foundry_agent_intake.py --env-file .env.foundry-agent.local --live --json --verify-agent-version |
      python -m json.tool
    ```

13. Inspect only the sanitized JSON. Confirm the verification section reports
    that the gate was requested, the lookup was attempted, and the immutable
    version matched before `application_intake_attempted=true` and
    `invocation_attempted=true`. Definition drift, a missing version,
    authentication/authorization failure, Azure request failure, or malformed
    verification response stops before either application intake or model
    invocation.

14. Restore `AGENT_PROVIDER=mock`, `APP_MODE=mock`, `AI_PROVIDER=mock`,
    `EMAIL_PROVIDER=mock`, `SMS_PROVIDER=mock`, and `SPEECH_PROVIDER=mock`
    after validation.

15. After review, manually delete the disposable resource group when it is no
    longer needed:

    ```bash
    az group delete --name <resource-group-name> --yes --no-wait
    ```

Do not automate environment-file mutation or resource-group deletion.
Disposable resource-group deletion is always a manual, explicit operator
action.

Provisioning never runs during application import/startup or intake requests.
It does not provide production deployment or clinical readiness. Human nurse
review remains mandatory. After manual validation, restore:

```bash
AGENT_PROVIDER=mock
```

## Application-Level Foundry Agent Text-Intake Smoke

Use this guarded sequence for an operator-controlled application smoke:

1. Deploy or reuse disposable Foundry infrastructure through the existing
   Foundry-only deployment boundary.
2. Provision or reuse the immutable prompt-agent version through
   `deploy_foundry_agent.py`.
3. Manually configure the exact agent name, immutable version, project endpoint,
   stable agent OpenAI protocol endpoint, and model deployment in the existing
   ignored `.env.foundry-agent.local` file; no script edits it.
4. Run `verify_foundry_agent.py --live --json` for the standalone read-only
   exact-version verification.
5. Run `smoke_foundry_agent_intake.py --live --json
   --verify-agent-version` for the guarded application-level smoke.
6. Inspect only the sanitized verification and application-stage output.
7. Restore `AGENT_PROVIDER=mock` and the other mock application/provider
   settings.
8. Manually clean up the disposable resources after review.

The gate prevents agent-client creation and application intake when
exact-version verification fails. It does not run during application startup
or ordinary `/intake/text` requests, establish clinical correctness, remove
mandatory nurse review, or make the application production-ready. The gate is
read-only and runs before invocation; it creates or updates no agent version.
The smoke edits no environment file, uses only fixed fictional data, and keeps
notifications suppressed.

The Foundry workflow has four primary operator-controlled
boundaries:

1. `deploy_foundry_infra.py` and `verify_foundry_infra.py` deploy and verify
   the disposable Foundry infrastructure.
2. `deploy_foundry_agent.py` creates, reuses, or updates the immutable prompt
   agent version without invoking it.
3. `verify_foundry_agent.py` verifies the exact configured immutable version
   and centralized definition through a read-only lookup without mutating or
   invoking it.
4. `smoke_foundry_agent_intake.py` sends one centrally defined fictional
   intake through the existing application-level `POST /intake/text` route
   boundary, in-memory case repository, deterministic safeguards, processing
   trace, nurse-review state, and notification-suppression logic.

Run the application-level offline readiness check first:

```bash
python scripts/preflight.py --all
```

The legacy-formatted consolidated `--all` workflow includes Foundry Agent
Intake readiness alongside the six existing provider checks. Default mock agent
posture is reported as `SKIP`; an explicitly configured safe posture reports
`PASS`; missing or unsafe posture reports `FAIL` with setting names only.

For the standalone sanitized JSON readiness result, run:

```bash
set -o pipefail

python scripts/preflight.py --foundry-agent-intake --json |
  python -m json.tool
```

The consolidated preflight command uses the same pure readiness calculation as
the intake smoke CLI. It returns only missing/unsafe setting names, static
manual guidance, and false side-effect flags. It creates no credential or
Foundry client, processes no intake, saves no case, records no notification,
and makes no Azure call.

The equivalent dedicated readiness command is:

```bash
set -o pipefail

python scripts/smoke_foundry_agent_intake.py --check --json |
  python -m json.tool
```

Check mode validates only setting presence and safe application posture. It
does not create a credential or Foundry client, process an intake, create a
case, record a notification, or call Azure. The required manual posture is:

```bash
APP_MODE=mock
AI_PROVIDER=mock
AGENT_PROVIDER=foundry-agent
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=true
```

The ignored local environment file must also contain the verified Foundry
Agent project endpoint, stable agent endpoint, agent name, and immutable
version. Update it manually; the script never edits environment files.

To validate readiness for the guarded sequence, include the explicit gate:

```bash
set -o pipefail

python scripts/smoke_foundry_agent_intake.py \
  --check \
  --json \
  --verify-agent-version |
  python -m json.tool
```

This gated check also requires
`AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME` and verifies the existing immutable
version SDK surface through the offline readiness seam. Its sanitized result
states that verification is required while confirming that no Azure lookup,
Responses client, model invocation, or application intake occurred. It does
not change application state, edit an environment file, or provision an agent.

Next, run the standalone read-only immutable-version verification:

```bash
set -o pipefail

python scripts/verify_foundry_agent.py \
  --live \
  --json \
  --env-file .env.foundry-agent.local |
  python -m json.tool
```

Live mode requires `--json` and accepts no arbitrary intake-text argument. It
uses the centralized fictional intake only, constructs the existing lazy
Foundry Agent adapter, and exercises the existing application route in-process.
It refuses to run with Cosmos, real email/SMS providers, or unsuppressed
notifications. It does not deploy infrastructure or create an agent version.

For the guarded live path, run:

```bash
set -o pipefail

python scripts/smoke_foundry_agent_intake.py \
  --live \
  --json \
  --verify-agent-version \
  --env-file .env.foundry-agent.local |
  python -m json.tool
```

The option calls the existing `FoundryAgentVerification` boundary first. That
boundary performs the read-only `agents.get_version(...)` lookup and compares
the exact configured agent name/version response contract, model deployment,
and centralized `foundry-agent-intake-v1` instructions. The application agent
and its lazy Responses invocation client are not created when verification
fails. An exact match allows the same fixed fictional intake and existing
application pipeline to proceed; no verifier comparison logic or prompt
definition is duplicated in the smoke script. The verification gate is
read-only: it never creates or updates an agent or agent version, and it runs
before the invocation client is created.

The sanitized live JSON contains only operational booleans/status categories:
agent attempted, agent output valid, fallback used, case saved, intake/review
status, urgency/handoff/processing-trace presence, and notification suppression.
It never prints the case identifier, fictional demographics or callback data,
raw intake, symptoms, summary, prompt/instructions, raw agent output, endpoint,
credential/token, SDK response, full exception, or stack trace.

With the gate enabled, the result adds `stable_endpoint_used`,
`immutable_version_verified`, a `verification` section, and
stage metadata for version lookup, invocation, application intake, temporary
state restoration, and expected safe output-field presence. Lookup, match, and
SDK fields use `true`, `false`, or `null` so the smoke does not claim facts the
verifier did not establish. Temporary-state restoration is reported from an
observed pre/post comparison of the application route, dependency overrides,
application repository, and notification stores. Expected field names are
reported independently without their values. Verification failures retain a
stage-appropriate category and are never reported as invocation failures
because invocation did not occur.

`category=success` requires every application-level postcondition: the route
completed successfully; the agent was attempted; agent output was valid; no
fallback was used; the in-memory case was saved; intake status is `Complete`
or `NeedsFollowUp`; review status remains `PendingReview`; urgency, the handoff
note, and the processing trace are present; the trace contains the required
agent attempt/validity/fallback metadata; and both notification channels remain
suppressed.

Unsuccessful live outcomes are classified without printing response bodies or
exception details:

- `route_request_failed`: the route returned a non-success result, raised an
  expected request-level exception, or could not produce a usable response.
- `agent_not_attempted`: route processing completed and a valid processing
  trace proves the configured agent was not attempted.
- `safe_fallback_used`: the agent was attempted, its output was invalid or it
  raised, and the existing fallback still saved the case safely with pending
  nurse review and suppressed notifications.
- `response_contract_invalid`: a required response, persistence, status,
  urgency, handoff-note, trace, nurse-review, or notification-suppression
  postcondition is absent or invalid.
- `unexpected_error`: an otherwise unclassified internal smoke-runner error.

An agent exception or invalid result can therefore remain a safe application
outcome, but safe fallback is never reported as full live-agent success. If a
fallback result also violates a required safe postcondition, it is classified
as `response_contract_invalid`. The existing fallback and deterministic
red-flag rules are not bypassed.

No live application-level smoke was run for this implementation slice. Do not
claim success until an operator runs the explicit guarded live command with
fictional data and reviews its sanitized JSON result. The gate prevents
application invocation when the configured immutable definition is missing,
unverifiable, or has drifted. It does not run during application startup,
`/demo`, or ordinary intake requests; it does not verify clinical correctness,
remove mandatory nurse review, or make the application production-ready.
Restore all providers to their mock/offline defaults afterward. Cleanup of
disposable Azure resources remains manual.

## Fixed-Corpus Application Evaluation

The one-case application smoke above validates a single guarded path. The
fixed-corpus evaluation is a separate, explicit manual command that runs three
committed fictional scenarios through the same verified Foundry Agent adapter
and application-level text-intake pipeline. It checks an urgent red-flag case,
a routine non-red-flag case, and an incomplete follow-up case in deterministic
order without printing their intake text.

Run its offline readiness check first:

```bash
set -o pipefail

python scripts/evaluate_foundry_agent_intake.py --check --json |
  python -m json.tool
```

Check mode validates the committed corpus, safe scenario IDs, required setting
names, safe mock application posture, and SDK availability. It performs no
Azure lookup, creates no verifier or invocation client, invokes no agent,
processes no intake, saves no case, records no notification, and changes no
application state. Missing optional local configuration may therefore produce
a sanitized nonzero readiness result without changing mock defaults.

After the standalone read-only immutable-version verification succeeds, an
operator may explicitly run:

```bash
set -o pipefail

python scripts/evaluate_foundry_agent_intake.py \
  --live \
  --json \
  --verify-agent-version \
  --env-file .env.foundry-agent.local |
  python -m json.tool
```

Live evaluation requires `--verify-agent-version`. It verifies the configured
immutable agent version, model deployment, and centralized
`foundry-agent-intake-v1` instructions exactly once before creating the
existing invocation adapter. Verification failure stops all scenario
execution. Each scenario then uses the existing application route,
deterministic urgency safeguards, notification suppression, pending nurse
review, safe fallback behavior, and observed pre/post state-restoration check.
Unconfirmed restoration stops later scenarios.

The aggregate and per-scenario JSON contains only stable IDs, safe enums,
booleans, counts, verification metadata, expected-field names, and static next
steps. It excludes corpus text, extracted patient values, case IDs, prompts,
raw agent output, exceptions, endpoints, agent/model identifiers, credentials,
and resource identifiers. A safe fallback may report
`application_safe=true`, but it remains an agent-quality failure, makes the
scenario and aggregate evaluation unsuccessful, and returns a nonzero exit.

This fixed fictional corpus is a narrow capstone validation aid, not a
production clinical evaluation system. Human nurse review remains mandatory,
notifications remain suppressed, and local providers must be restored to mock
manually after live use. Disposable Azure resources must also be deleted
manually after review. Passing the evaluation neither establishes clinical
correctness nor makes the application production-ready.

### Optional sanitized Foundry metric publication

Install the optional packages in `requirements-foundry-agent.txt`, including
`azure-ai-evaluation`, before requesting publication. Publication is a separate
operator opt-in on the guarded live fixed-corpus evaluation:

```bash
set -o pipefail

python scripts/evaluate_foundry_agent_intake.py \
  --live \
  --json \
  --verify-agent-version \
  --publish-foundry-evaluation \
  --env-file .env.foundry-agent.local |
  python -m json.tool
```

Do not run that command until disposable infrastructure and the intended
immutable prompt-agent version have been provisioned, manually configured, and
verified with the standalone read-only version verifier. The publication option
is invalid with `--check` and requires `--live`, `--json`, and
`--verify-agent-version`. Without the option, existing check and live JSON are
unchanged.

The evaluator verifies the immutable version, creates the existing agent client,
runs each eligible fictional scenario once, and confirms observed pre/post
application-state restoration before constructing a publication request. It
does not publish after missing configuration, SDK unavailability, verifier or
client failure, no completed scenarios, or unconfirmed restoration. A safely
restored fallback result may still publish its failed deterministic metrics,
while the CLI remains unsuccessful.

Publication uses `azure.ai.evaluation.evaluate` with an explicit Azure
subscription ID, Foundry resource-group name, and Foundry project name plus the
stable evaluation name `nurse-intake-fixed-corpus-v1`. These three non-secret
scope settings are required only when publication is requested; missing scope
fails before agent creation, and their values are never emitted in CLI JSON.
Its temporary
JSONL contains only the stable scenario ID and booleans for scenario success,
agent-contract validity, fallback use, application safety, urgency match, intake
status match, pending review, suppressed notifications, and restored state. Nine
local code-based evaluators use explicit sanitized column mappings and return a
single numeric 0/1 `value` metric. No model
configuration, AI judge, prompt, raw response, patient data, endpoint, credential,
or result-file path is emitted by the CLI. Temporary dataset and result artifacts
are removed after success or failure.

Inspect only the sanitized CLI result and the deterministic metric summary in
Foundry. This optional tracking does not add an agent/model invocation, establish
clinical correctness, remove mandatory nurse review, or make the application
production-ready. Restore `AGENT_PROVIDER=mock` and all other mock settings
manually, then manually delete disposable resources. No live publication was run
or claimed during implementation of this slice.

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
Endpoint values, agent IDs, agent names, and agent versions are not printed.

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
- `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT`
- `AZURE_AI_FOUNDRY_AGENT_NAME`
- `AZURE_AI_FOUNDRY_AGENT_VERSION`

`AZURE_AI_FOUNDRY_AGENT_ID` may remain in older local files for reference, but
it is not required by this hosted/prompt agent smoke path.

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
set -o pipefail

python scripts/smoke_foundry_agent.py --env-file .env.foundry-agent.local --live --json |
  python -m json.tool
```

Optional sanitized diagnostic command after live JSON fails:

```bash
python scripts/smoke_foundry_agent.py --env-file .env.foundry-agent.local --live --diagnose
```

`--live --json` is the primary live validation command. `--live` remains manual
and opt-in. It is the only mode intended to construct the Foundry Agent path
and may call Azure. It uses the minimal SDK-backed project-responses path:
`AIProjectClient`, an agent-scoped OpenAI Responses client, the configured
agent name/version reference, and `responses.create` with the script's
fictional medication-refill intake. It does not send notifications, does not
write to Cosmos, does not call FastAPI routes, and does not require the FastAPI
server to be running.
In plain terms: --live remains manual and opt-in.

`--live --json` prints a deterministic sanitized result with these fields:
`ok`, `mode`, `provider`, `category`, `message`, `agent_attempted`,
`agent_output_valid`, `fallback_used`, `fields_present`, and
`recommended_next_step`. It does not print raw exception messages, stack
traces, full endpoints, agent IDs, agent names, agent versions, bearer tokens,
prompts, instructions, raw model output, connection strings, real
patient/contact data, email addresses, phone numbers, or PHI.

Sanitized successful result example:

```json
{
  "ok": true,
  "mode": "live",
  "provider": "foundry-agent",
  "category": "success",
  "message": "Live Foundry Agent smoke validation completed successfully.",
  "agent_attempted": true,
  "agent_output_valid": true,
  "fallback_used": false,
  "fields_present": ["extraction", "urgency", "handoffNote"],
  "recommended_next_step": "No action needed for this manual smoke result."
}
```

This example is intentionally sanitized. It does not include the project
endpoint, agent name, agent version, agent ID, request ID, prompt text, raw
agent response, token, contact data, or PHI. It confirms only the manual smoke
result shape and does not make `/demo` call Azure.

`--live --diagnose` calls the same live path and prints only sanitized
troubleshooting metadata: provider, mode, category, whether the agent was
attempted, safe root-cause exception class name when detectable, safe status
code from the exception chain when available, safe client error category, safe
client error phase, and the recommended next step. Client error phase is
diagnostic-only and safe; expected values include labels such as `sdk_import`,
`credential_creation`, `client_creation`, `agent_reference_creation`,
`response_creation`, `response_extraction`, `response_parsing`, or `unknown`.
It does not print endpoint URLs, agent IDs, agent names, agent versions,
tokens, stack traces, raw exception messages, raw prompts, raw model responses,
request IDs, real contact values, or PHI.

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
`authentication_or_authorization_failed` usually means `az login`, tenant,
subscription, or RBAC needs investigation; local development may require
`az login` for `DefaultAzureCredential`. `azure_request_failed` usually means
project endpoint, agent name/version, SDK compatibility, agent availability,
or request shape needs investigation. It may also represent a non-auth request
category such as bad request, missing resource, conflict, rate limit, or
service error.
If diagnostic output reports `phase=client_creation`,
`phase=agent_reference_creation`, `phase=response_creation`, or
`phase=response_extraction`, investigate SDK compatibility, project endpoint,
agent reference, request shape, agent availability, and response extraction
before changing app defaults.
`missing_configuration` means required environment variable names are missing.
`sdk_unavailable` means the optional Foundry Agent SDK dependencies are not
importable. `unexpected_error` is a sanitized catch-all for failures outside
the known configuration, SDK, auth, request, parsing, and contract buckets.

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
