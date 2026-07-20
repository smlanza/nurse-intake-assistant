# Daily Disposable Azure Environment Rebuild

## 1. Purpose and lifecycle

This is the single authoritative operator runbook for rebuilding the disposable
Nurse Intake Assistant Azure environment at the start of a live-validation
session. The default state is **NOT READY**. A session becomes **READY** only
after every required stage below succeeds in order and its sanitized result is
reviewed during the current session.

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

Choose new disposable values for each session and keep them in an ignored local
note or shell session. Angle-bracket values below are placeholders, not
permanent names:

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

## 5. Resource group creation

Create exactly one disposable resource group for this session:

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
  --json

.venv/bin/python scripts/deploy_foundry_infra.py \
  --mode foundry-only \
  --parameters infra/foundry-only.bicepparam \
  --resource-group <resource-group> \
  --location <location> \
  --live \
  --json

.venv/bin/python scripts/verify_foundry_infra.py \
  --resource-group <resource-group> \
  --project-endpoint <project-endpoint> \
  --model-deployment-name <model-deployment-name> \
  --json
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
.venv/bin/python scripts/deploy_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --check \
  --json

.venv/bin/python scripts/deploy_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --live \
  --json
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
.venv/bin/python scripts/verify_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --check \
  --json

.venv/bin/python scripts/verify_foundry_agent.py \
  --env-file .env.foundry-agent.local \
  --live \
  --json
```

Require `ok=true`, the expected definition/version checks, `agent_invoked=false`,
and `azure_mutation_made=false`. Agent provisioning, metadata verification, and
invocation remain different authorization boundaries.

## 8. Web App infrastructure

Deploy the Web App with the complete hosted-verifier configuration. The five
hosted values are required exactly once when the feature is enabled:

This repository boundary uses `infra/main.bicep` with `deployApp=true` and
`deployFoundry=false`. It preserves the system-assigned managed identity, Linux
Python runtime, remote build, mock providers, notification suppression, and
non-production-clinical-use posture.

```bash
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
  --json

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
  --json

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
  --json
```

Review the what-if before running live. Do not combine modes. Stop unless each
result succeeds and the deployment is limited to the intended Web App stack.

## 9. Web App configuration verification

Read and compare the Bicep-owned settings without printing their values:

```bash
.venv/bin/python scripts/verify_web_app_configuration.py --check --json

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
  --hosted-verifier-model-deployment-name <model-deployment-name>
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
.venv/bin/python scripts/package_web_app.py --check --json
.venv/bin/python scripts/package_web_app.py --package --json
```

Require a successful, sanitized package result. Packaging proves neither code
deployment nor hosted readiness. Review the deterministic manifest/exclusion
evidence and confirm the fixed triggered WebJob is included when hosted
verification is planned; local env files, caches, credentials, and artifacts
must remain excluded.

## 11. Web App code deployment

Check the deployment boundary, then explicitly upload to the existing Web App:

```bash
.venv/bin/python scripts/deploy_web_app_code.py --check --json
.venv/bin/python scripts/deploy_web_app_code.py \
  --live \
  --resource-group <resource-group> \
  --web-app <web-app-name> \
  --json
```

Deployment acceptance is not readiness. Continue only after a successful
sanitized result; do not introduce polling or another deployment request.

## 12. Hosted readiness verification

Validate the URL locally, then make one explicit read-only readiness request:

```bash
.venv/bin/python scripts/verify_web_app_readiness.py \
  --check \
  --base-url https://<web-app-hostname> \
  --json

.venv/bin/python scripts/verify_web_app_readiness.py \
  --live \
  --base-url https://<web-app-hostname> \
  --json
```

Require the repository contract for `/health`, `/version`, and `/demo/status`
to pass, including mock providers and notification suppression. The result
proves hosted readiness, not Foundry access or invocation.

## 13. Consumer RBAC deployment

Use the separate `infra/foundry-agent-consumer-rbac.bicep` boundary. Run check,
review what-if, then deploy the project-scoped assignment once:

```bash
.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json

.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --what-if \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json

.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --live \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json
```

Manually review the what-if and exact project scope before running live. Do not
use a manual role assignment or retry a failed deployment without correcting
its cause.

## 14. Consumer RBAC verification

Prove the exact direct assignment separately from deployment:

```bash
.venv/bin/python scripts/verify_foundry_agent_consumer_rbac.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json

.venv/bin/python scripts/verify_foundry_agent_consumer_rbac.py \
  --live \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --foundry-account-name <foundry-account-name> \
  --foundry-project-name <foundry-project-name> \
  --json
```

Require exactly one matching direct Foundry Agent Consumer assignment at the
approved project scope. Historical, inherited, broader, duplicate, or inferred
assignments do not pass. This does not prove managed-identity token acquisition.

## 15. Optional WebJob discovery

Run this only when the next narrow slice requires the fixed hosted verifier.
The check is offline; discovery performs exactly one read:

```bash
.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --check \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --json

.venv/bin/python scripts/run_hosted_foundry_agent_verification.py \
  --live-discover \
  --resource-group <resource-group> \
  --web-app-name <web-app-name> \
  --json
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
