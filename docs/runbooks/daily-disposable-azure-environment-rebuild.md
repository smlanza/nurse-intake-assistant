# Daily Disposable Azure Environment Rebuild

## Normal Daily Guided Path

The repository-owned coordinator is the preferred path for a normal daily
rebuild. Follow this sequence without skipping a step:

1. Copy `.env.daily-azure.example` to the ignored `.env.daily-azure.local`,
   replace every placeholder with reviewed stable non-secret values, and keep
   that configuration untracked.
2. Run the coordinator's offline check:

```bash
set -o pipefail

.venv/bin/python scripts/rebuild_daily_azure_environment.py \
  --config .env.daily-azure.local \
  --check \
  --json |
  python -m json.tool
```

3. Start the guided live coordinator in an interactive terminal:

```bash
set -o pipefail

.venv/bin/python scripts/rebuild_daily_azure_environment.py \
  --config .env.daily-azure.local \
  --live \
  --json |
  python -m json.tool
```

4. Review each sanitized prompt and answer `y` only for the current stage. The
   default, EOF, malformed input, or noninteractive input stops without that
   mutation. The possible approvals are resource-group creation, Foundry
   infrastructure deployment, Web App infrastructure deployment, and current
   package deployment. Already verified stages are not prompted.
5. If that result reports `category=manual_rbac_action_required`, run the
   existing manual RBAC workflow in sections 13 and 14 exactly once under its
   own authorization.
6. Rerun the coordinator from step 3. The rerun rebuilds, approves, deploys, and verifies the
   current deterministic application package; it does not reuse an earlier
   package proof.
7. Require `daily_environment_ready=true` from the current run before recording
   the READY declaration below.

Begin the approved Azure-dependent Codex slice only when the current live
result reports `daily_environment_ready=true` and the operator records:

```text
DAILY AZURE ENVIRONMENT READY
```

The operator-approved coordinator verifies current state and reuses only an
owned resource group and conclusively valid resources. It prepares sanitized
Foundry and Web App previews, including whether nested deployment records are
present, and requires current-run approval before either deployment. It stops
on Delete, Modify, malformed, unknown, unrelated, incomplete, count-disagreeing,
or otherwise ambiguous evidence. Package deployment has its own current-run
approval and immutable transient handoff. Live mode reruns the
complete offline contract; the prior standalone check is not reused as proof.
When direct verification finds the Consumer assignment missing, the coordinator
always stops for the manual workflow regardless of whether a separate preview
is empty, Create, NoChange, Ignore, Unsupported, malformed, or unavailable. The
coordinator contains no live RBAC deployment path. It
does not trigger or read WebJob execution,
perform hosted managed-identity verification, invoke an agent, process intake,
send notifications, or delete the resource group. Use
`--skip-webjob-discovery` only when remote name-only discovery is not required.

The detailed manual stages below remain the troubleshooting, recovery, audit,
and individual-boundary reference. They are not the normal daily command path.

## 1. Purpose and lifecycle

This is the authoritative operator runbook for rebuilding the disposable Nurse
Intake Assistant Azure environment at the start of a live-validation session.
The default state is **NOT READY**. A session becomes **READY** only after the
guided path, or every required manual recovery stage below, succeeds in
order and its sanitized result is reviewed during the current session.

This file is the durable checked-in procedure. Command output is fresh
current-session evidence. Evidence expires when the resource group is deleted
and must not be treated as durable project state.

```text
resource group absent
-> rebuild
-> verify
-> perform approved Azure-dependent work
-> optionally delete resource group
-> all live evidence expires
```

A prior day's success never proves today's readiness.

This workflow is fictional-data-only, requires human nurse review, and does not
establish production or clinical readiness.

## 2. Required operator inputs

For normal coordinator use, retain the reviewed stable values in the ignored
`.env.daily-azure.local`; a deleted resource supplies no current evidence, even
when the same configured name is retained. Globally unique names may be reused
only when Azure permits reuse and the current resource passes ownership and
drift verification. During intentional manual recovery, the operator may
select alternate disposable names and keep them in an ignored local note or
shell session. Angle-bracket values below are placeholders, not architecture
defaults:

- subscription name, Azure region, and a new resource-group name;
- short project and environment names, App Service plan/SKU parameters, and a
  globally unique Linux Web App name;
- Foundry account name, project name, project endpoint, model deployment name,
  and model/version/SKU/capacity values available in the selected region;
- prompt-agent name, immutable version, and complete stable agent endpoint;
- the public HTTPS Web App base URL.

Never commit subscription IDs, tenant IDs, principal IDs, complete ARM resource
IDs, credentials, connection strings, identity headers, access tokens, bearer
tokens, secrets, endpoints containing sensitive values, or real patient or
contact data. Retain only sanitized pass/fail fields in a local ignored note,
the active terminal session, ignored artifact storage, or the Codex prompt that
consumes the proof.

## 3. Local preflight

Start from the repository root with the project virtual environment available.
Review local changes before doing anything live:

```bash
pwd
test -f pyproject.toml
git status --short
source .venv/bin/activate
python -m pytest -q
az version
az bicep version
```

These commands confirm the repository marker, preserve all existing work, and
check the expected Python, Azure CLI, and Bicep tooling. Do not clean, reset,
stash, discard, or rewrite unrelated changes.

Copy `infra/foundry-only.example.bicepparam` to the ignored
`infra/foundry-only.bicepparam` manually, then replace its fictional model and
session placeholders. Do not edit or commit the example as session evidence.
Confirm the local files remain ignored:

```bash
git check-ignore infra/foundry-only.bicepparam .env.foundry-agent.local
```

The `--check` commands in sections 6 through 15 are the relevant repository
script preflights. Each must pass before its matching live mode is considered.

Create an ignored `.env.foundry-agent.local` manually. Before prompt-agent
provisioning it must contain the current values for:

```text
AGENT_PROVIDER=foundry-agent
AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT=<project-endpoint>
AZURE_AI_FOUNDRY_AGENT_NAME=<agent-name>
AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME=<model-deployment-name>
```

After provisioning, add the returned operator-inspected immutable version and
stable endpoint as described in section 7. Keep application, AI, notification,
and Speech providers at their mock-safe defaults.

## 4. Authentication and subscription

The operator signs in and confirms the intended enabled subscription:

```bash
az login
az account show \
  --query "{subscription:name,state:state,isDefault:isDefault}" \
  --output table
```

Stop if the account, subscription, or state is wrong. Do not paste IDs from the
full account response into documentation or a prompt.

## 5. Resource group creation or explicit adoption

Guided mode inspects the configured group first. If it is absent, the
coordinator displays the create summary and waits for approval before issuing
one tagged creation request. If an existing group lacks the exact
`purpose=fictional-daily-validation` tag, it stops with
`resource_group_ownership_approval_required` and never adopts or retags it.

For intentional adoption, first inspect the group and its contents outside the
coordinator:

```bash
az group show \
  --name <resource-group> \
  --query "{location:location,state:properties.provisioningState,purpose:tags.purpose}" \
  --output table

az resource list \
  --resource-group <resource-group> \
  --query "[].{type:type,name:name}" \
  --output table
```

Only after the operator establishes that this is the intended disposable group
may the operator explicitly adopt it:

```bash
az group update \
  --name <resource-group> \
  --set tags.purpose=fictional-daily-validation \
  --query "{location:location,state:properties.provisioningState,purpose:tags.purpose}" \
  --output json
```

Review the projected response, then rerun the guided coordinator. Adoption is
never an automatic continuation within the run that detected missing or
different ownership.

The equivalent manual recovery command for creating a new group is:

```bash
az group create \
  --name <resource-group> \
  --location <location> \
  --tags purpose=fictional-daily-validation \
  --output json
```

Confirm the response reports the intended name, region, and successful
provisioning state. Creation alone does not make the environment READY.

## 6. Foundry infrastructure

Use `infra/foundry-only.bicep` through the repository-owned deployment boundary.
Run the offline check, review one what-if, deploy once, then perform separate
read-only verification:

```bash
set -o pipefail

.venv/bin/python scripts/deploy_foundry_infra.py \
  --mode foundry-only \
  --parameters infra/foundry-only.bicepparam \
  --resource-group <resource-group> \
  --location <location> \
  --check

.venv/bin/python scripts/deploy_foundry_infra.py \
  --mode foundry-only \
  --parameters infra/foundry-only.bicepparam \
  --resource-group <resource-group> \
  --location <location> \
  --what-if \
  --json |
  python -m json.tool

.venv/bin/python scripts/deploy_foundry_infra.py \
  --mode foundry-only \
  --parameters infra/foundry-only.bicepparam \
  --resource-group <resource-group> \
  --location <location> \
  --live \
  --json |
  python -m json.tool

.venv/bin/python scripts/verify_foundry_infra.py \
  --resource-group <resource-group> \
  --project-endpoint <project-endpoint> \
  --model-deployment-name <model-deployment-name> \
  --json |
  python -m json.tool
```

Stop unless what-if matches the intended template and both live results are
successful. Record only sanitized success fields. Infrastructure deployment and
read-only verification are separate evidence. Require fresh proof of the
AIServices account, child project, model deployment, successful provisioning
states, and the expected project-endpoint contract. Infrastructure deployment
must not create the prompt agent as a side effect.

## 7. Prompt-agent provisioning and immutable-version proof

Provisioning reads the ignored env file, may create/reuse/update one immutable
version, and never invokes the agent. Verification is a later read-only stage:

```bash
set -o pipefail

.venv/bin/python scripts/deploy_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --check \
  --json |
  python -m json.tool

.venv/bin/python scripts/deploy_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --live \
  --json |
  python -m json.tool
```

Require sanitized provisioning success and `agent_invoked=false`. The operator
then inspects the resulting Foundry agent and manually adds these current values
to the ignored file:

```text
AZURE_AI_FOUNDRY_AGENT_ENDPOINT=<stable-agent-endpoint>
AZURE_AI_FOUNDRY_AGENT_VERSION=<immutable-agent-version>
```

Prove that exact configured version without invoking it:

```bash
set -o pipefail

.venv/bin/python scripts/configure_foundry_agent_endpoint_routing.py \
  --env-file .env.foundry-agent.local \
  --check \
  --json |
  python -m json.tool

.venv/bin/python scripts/configure_foundry_agent_endpoint_routing.py \
  --env-file .env.foundry-agent.local \
  --live \
  --json |
  python -m json.tool

.venv/bin/python scripts/verify_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --check \
  --json |
  python -m json.tool

.venv/bin/python scripts/verify_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --live \
  --json |
  python -m json.tool
```

The routing check is offline and proves only local readiness. Explicit live mode
reads the current endpoint, reuses an already-exclusive route without mutation,
or submits at most one fixed 100% `FixedRatio` update for the configured
immutable version. It preserves Responses, other supported protocol settings,
and endpoint authorization settings; it never provisions or invokes an agent.
The separate read-only verifier remains the proof boundary after any routing
result.

Require verifier `ok=true`, the expected definition/version checks,
`responses_protocol_present=true`, `immutable_version_verified=true`,
`configured_version_traffic_percentage=100`, `agent_invoked=false`, and
`azure_mutation_made=false`. Agent provisioning, endpoint routing configuration,
metadata verification, and invocation remain different authorization boundaries.

## 8. Web App infrastructure

Deploy the Web App with the complete hosted-verifier configuration. The five
hosted values are required exactly once when the feature is enabled:

This repository boundary uses `infra/main.bicep` with `deployApp=true` and
`deployFoundry=false`. It preserves the system-assigned managed identity, Linux
Python runtime, remote build, mock providers, notification suppression, and
non-production-clinical-use posture.

```bash
set -o pipefail

.venv/bin/python scripts/deploy_web_app_infra.py \
  --check \
  --resource-group <resource-group> \
  --location <location> \
  --environment-name <environment-name> \
  --project-name <project-name> \
  --web-app-name <web-app-name> \
  --enable-hosted-foundry-verifier \
  --hosted-verifier-project-endpoint <project-endpoint> \
  --hosted-verifier-stable-agent-endpoint <stable-agent-endpoint> \
  --hosted-verifier-agent-name <agent-name> \
  --hosted-verifier-agent-version <immutable-agent-version> \
  --hosted-verifier-model-deployment-name <model-deployment-name> \
  --json |
  python -m json.tool

.venv/bin/python scripts/deploy_web_app_infra.py \
  --what-if \
  --resource-group <resource-group> \
  --location <location> \
  --environment-name <environment-name> \
  --project-name <project-name> \
  --web-app-name <web-app-name> \
  --enable-hosted-foundry-verifier \
  --hosted-verifier-project-endpoint <project-endpoint> \
  --hosted-verifier-stable-agent-endpoint <stable-agent-endpoint> \
  --hosted-verifier-agent-name <agent-name> \
  --hosted-verifier-agent-version <immutable-agent-version> \
  --hosted-verifier-model-deployment-name <model-deployment-name> \
  --json |
  python -m json.tool

.venv/bin/python scripts/deploy_web_app_infra.py \
  --live \
  --resource-group <resource-group> \
  --location <location> \
  --environment-name <environment-name> \
  --project-name <project-name> \
  --web-app-name <web-app-name> \
  --enable-hosted-foundry-verifier \
  --hosted-verifier-project-endpoint <project-endpoint> \
  --hosted-verifier-stable-agent-endpoint <stable-agent-endpoint> \
  --hosted-verifier-agent-name <agent-name> \
  --hosted-verifier-agent-version <immutable-agent-version> \
  --hosted-verifier-model-deployment-name <model-deployment-name> \
  --json |
  python -m json.tool
```

Review the what-if before running live. Do not combine modes. Stop unless each
result succeeds and the deployment is limited to the intended Web App stack.

## 9. Web App configuration verification

Read and compare the Bicep-owned settings without printing their values:

```bash
set -o pipefail

.venv/bin/python scripts/verify_web_app_configuration.py --check --json |
  python -m json.tool

.venv/bin/python scripts/verify_web_app_configuration.py \
  --live \
  --json \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --verify-hosted-foundry-verifier \
  --hosted-verifier-project-endpoint <project-endpoint> \
  --hosted-verifier-stable-agent-endpoint <stable-agent-endpoint> \
  --hosted-verifier-agent-name <agent-name> \
  --hosted-verifier-agent-version <immutable-agent-version> \
  --hosted-verifier-model-deployment-name <model-deployment-name> |
  python -m json.tool
```

Stop unless the sanitized result proves the full baseline and all five hosted
verifier settings. Do not repair settings with ad hoc CLI or portal mutations.
The required baseline is Linux Python runtime, startup command, remote build,
HTTPS-only, disabled FTPS, minimum TLS, health path, system-assigned identity,
mock application/AI/agent/Speech/email/SMS providers, and notification
suppression. Configuration verification does not prove deployed code.

## 10. Package creation

Create the deterministic source package locally as its own stage:

```bash
set -o pipefail

.venv/bin/python scripts/package_web_app.py --check --json |
  python -m json.tool
.venv/bin/python scripts/package_web_app.py --package --json |
  python -m json.tool
```

Require a successful, sanitized package result. Packaging proves neither code
deployment nor hosted readiness. Review the deterministic manifest/exclusion
evidence and confirm the fixed triggered WebJob is included when hosted
verification is planned; local env files, caches, credentials, and artifacts
must remain excluded.

## 11. Web App code deployment

Check the deployment boundary, then explicitly upload to the existing Web App:

```bash
set -o pipefail

.venv/bin/python scripts/deploy_web_app_code.py --check --json |
  python -m json.tool
.venv/bin/python scripts/deploy_web_app_code.py \
  --live \
  --resource-group <resource-group> \
  --web-app <web-app-name> \
  --json |
  python -m json.tool
```

Deployment acceptance is not readiness. Continue only after a successful
sanitized result; do not introduce polling or another deployment request.

## 12. Hosted readiness verification

Validate the URL locally, then make one explicit read-only readiness request:

```bash
set -o pipefail

.venv/bin/python scripts/verify_web_app_readiness.py \
  --check \
  --base-url https://<web-app-hostname> \
  --json |
  python -m json.tool

.venv/bin/python scripts/verify_web_app_readiness.py \
  --live \
  --base-url https://<web-app-hostname> \
  --json |
  python -m json.tool
```

Require the repository contract for `/health`, `/version`, and `/demo/status`
to pass, including mock providers and notification suppression. The result
proves hosted readiness, not Foundry access or invocation.

## 13. Consumer RBAC deployment

Use the separate `infra/foundry-agent-consumer-rbac.bicep` boundary. Run check,
review what-if, then deploy the project-scoped assignment once:

```bash
set -o pipefail

.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json |
  python -m json.tool

.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --what-if \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json |
  python -m json.tool

.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --live \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json |
  python -m json.tool
```

Manually review the what-if and exact project scope before running live. Do not
use a manual role assignment or retry a failed deployment without correcting
its cause.

## 14. Consumer RBAC verification

Prove the exact direct assignment separately from deployment:

```bash
set -o pipefail

.venv/bin/python scripts/verify_foundry_agent_consumer_rbac.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json |
  python -m json.tool

.venv/bin/python scripts/verify_foundry_agent_consumer_rbac.py \
  --live \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json |
  python -m json.tool
```

Require exactly one matching direct Foundry Agent Consumer assignment at the
approved project scope. Historical, inherited, broader, duplicate, or inferred
assignments do not pass. This does not prove managed-identity token acquisition.

## 15. Optional WebJob discovery

Run this only when the next narrow slice requires the fixed hosted verifier.
The check is offline; discovery performs exactly one read:

```bash
set -o pipefail

.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --json |
  python -m json.tool

.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --live-discover \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --json |
  python -m json.tool
```

Discovery does not authorize a trigger, status read, managed-identity access,
metadata verification, or agent invocation. Those remain separately scoped,
explicitly approved future operations.

## 16. Daily environment-ready declaration

Declare **READY** only after the operator has reviewed current-session success
for every required stage: authentication, resource group, Foundry deployment
and verification, exact prompt-agent version, Web App deployment/configuration,
package/code, readiness, RBAC deployment and verification, plus WebJob discovery
when the next slice needs it.

The declaration must name the next narrow Azure-dependent slice and list which
fresh sanitized prerequisites satisfy it. READY authorizes only that slice; it
does not authorize unrelated live operations or establish production readiness.
If any prerequisite is absent, stale, ambiguous, or failed, declare **NOT READY**.

End the operator review with exactly one decision:

```text
DAILY AZURE ENVIRONMENT READY
```

or:

```text
DAILY AZURE ENVIRONMENT NOT READY
```

## 17. End-of-session cleanup and evidence expiry

After the session, the operator explicitly deletes only the exact disposable
resource group and reviews completion:

```bash
az group delete \
  --name <resource-group> \
  --yes \
  --no-wait
```

Deletion immediately returns the environment to NOT READY. It expires every
prior claim about the resource group, Foundry account/project/model, agent and
immutable version, Web App, system identity, settings, package/code, readiness,
RBAC, WebJob, managed-identity access, metadata verification, and invocation.
The checked-in procedure remains valid; the deleted environment's evidence does
not. A later session must restart at section 2.

```text
DAILY AZURE ENVIRONMENT NOT READY
```

## 18. Fail-fast rules

- Stop at the first failed, missing, mismatched, or ambiguous prerequisite.
- Unknown or malformed command output fails closed.
- Do not infer names from history, screenshots, truncated portal labels, or a
  previous conversation.
- Do not substitute portal-only creation, ad hoc Azure provisioning, manual App
  Service settings, manual RBAC, SSH/Kudu changes, or improvised HTTP endpoints.
- Do not retry live mutations, use general-purpose polling loops, repeat sleeps,
  or turn one failed rebuild into a broad debugging slice.
- Keep deployment, read-only verification, WebJob discovery, trigger, status,
  managed-identity proof, metadata verification, and invocation separate.
- When NOT READY, return to this runbook. Do not start an Azure-dependent Codex
  prompt or repeatedly rewrite progress with the same blocked result.

## 19. Cost control

Use one short-lived, fictional, resource-group-scoped environment. Select the
smallest approved development capacity, create no resources beyond the checked-in
templates, avoid duplicate deployments, and delete the exact resource group at
the end of the session. Cleanup is an operator action and must never be inferred
from elapsed time or delegated to an unbounded automation loop.

Daily resource-group deletion is an intentional operator cost-control choice,
not a repository defect. Its consequence is a required rebuild and fresh
verification before every later Azure-dependent session. This runbook makes no
cost estimate or claim about current Azure pricing.
