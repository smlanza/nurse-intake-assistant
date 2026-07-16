# Nurse Intake Assistant Infrastructure

This folder contains the application infrastructure plus reusable Microsoft
Foundry and Azure Web App modules. `main.bicep` remains the backward-compatible
full-stack entry point; Foundry and application hosting are disabled there by
default. `foundry-only.bicep` is the recommended lightweight entry point for
disposable daily agent validation.

## Resources

`main.bicep` creates:

- Azure Cosmos DB account in serverless capacity mode
- Cosmos SQL database
- Cosmos SQL container named `cases` by default
- `/createdDate` partition key for the cases container
- Azure Storage account for future artifacts or logs
- Log Analytics workspace
- Application Insights resource connected to the workspace
- Optional Linux App Service plan and Linux Web App when `deployApp=true`

The full template creates no Foundry resources unless `deployFoundry=true` and
no App Service resources unless `deployApp=true`. Neither entry point creates
Speech, ACS, Key Vault, private networking, or production clinical
infrastructure.

## Optional Web App Hosting

`modules/web-app.bicep` defines a reusable Linux App Service plan and Web App.
The Web App uses a system-assigned managed identity, HTTPS-only access, disabled
FTPS, TLS 1.2 minimums, and `/health` for its health check. The configurable
defaults are the low-cost `B1` plan and `PYTHON|3.12` runtime. Its startup
command follows the repository entry point and installed server dependency:

```text
python -m uvicorn src.app.main:app --host 0.0.0.0 --port 8000
```

The hosted configuration remains deliberately inert and notification-safe:

```text
APP_MODE=mock
AI_PROVIDER=mock
AGENT_PROVIDER=mock
SPEECH_PROVIDER=mock
EMAIL_PROVIDER=mock
SMS_PROVIDER=mock
DEMO_SUPPRESS_NOTIFICATIONS=true
```

This module provisions only hosting and a system-assigned identity. It does not
deploy application code, grant an RBAC role, configure live Foundry access, or
store endpoints, identity IDs, connection strings, credentials, or secrets.
The module exposes its principal ID only to its parent template for a future
conditional RBAC boundary; `main.bicep` does not publish that identifier.

## Explicit Web App Infrastructure Deployment

`scripts/deploy_web_app_infra.py` is the operator boundary for the existing
`main.bicep`; it does not introduce another template or duplicate the Web App
module. Local check mode verifies required safe arguments, template presence,
`deployApp=true`, `deployFoundry=false`, and the mock-safe hosted posture. It
does not construct an Azure CLI runner or make an Azure call:

```bash
.venv/bin/python scripts/deploy_web_app_infra.py \
  --check \
  --resource-group fictional-webapp-rg \
  --location eastus2 \
  --environment-name demo \
  --project-name nurse-intake \
  --web-app-name fictional-nurse-intake-web-app \
  --json
```

Local validation reads only the active Web App resource's
`siteConfig.appSettings` declaration and compares its seven provider and
notification-suppression entries with the same authoritative contract used by
the configuration verifier. Missing, extra, duplicate, conflicting,
commented-only, or later overriding settings fail validation. The separate
`SCM_DO_BUILD_DURING_DEPLOYMENT=true` entry must also remain present and exact.

After reviewing the offline result, an operator may explicitly choose
`--what-if` to issue exactly one `az deployment group what-if` command against
an existing resource group. Only a separately selected `--live` issues exactly
one `az deployment group create` command with a deterministic deployment name.
Both Azure modes use `infra/main.bicep`, forward the reviewed Cosmos names and
Web App name, and always pass `deployApp=true` and `deployFoundry=false`.

What-if requests machine-readable JSON, then discards resource names, IDs, and
raw Azure content after reducing the change collection to sanitized counts for
create, modify, delete, no-change, ignore, deploy, and unsupported changes.
Malformed or structurally invalid output fails safely. Proposed deletes are
surfaced with an explicit manual-review warning, but the application never
blocks, approves, or runs live deployment automatically. What-if remains
preview-only, and live deployment remains a separate explicit choice. A zero
exit code in live mode means Azure accepted the deployment request; it does not
prove configuration, code deployment, startup, readiness, identity access, or
Foundry access.

The CLI never creates or deletes a resource group, deploys application code,
runs configuration or hosted-readiness verification, changes app settings,
assigns RBAC, or invokes Foundry. Resource-group creation and cleanup remain
manual and explicit. Infrastructure deployment, configuration verification,
code deployment, hosted readiness, RBAC, and Foundry invocation remain separate
operator stages. RBAC deployment and Foundry invocation remain separate future
operator stages. Mock providers, suppressed hosted notifications, and mandatory
human nurse review remain unchanged; this is not production clinical
infrastructure.

Manual Azure resource-group validation of `infra/main.bicep` with
`deployApp=true`, `deployFoundry=false`, B1, and `PYTHON|3.12` succeeded on July
15, 2026. Validation created no Azure resources. The new CLI is offline-tested
only; no `--what-if` or `--live` operation has been run for this slice, and no
claim is made that the Web App is hosted or running.

## Explicit Foundry Agent Consumer RBAC

`foundry-agent-consumer-rbac.bicep` is a separate, explicit operator boundary
for granting an existing Web App identity access to an existing Foundry
project. It requires only the existing Web App, Foundry account, and Foundry
project names. The template reads the Web App's system-assigned identity
principal ID from `Microsoft.Web/sites`; operators do not supply or receive the
identity identifier as a deployment output.

The reusable `modules/foundry-agent-consumer-rbac.bicep` module assigns only the
built-in **Foundry Agent Consumer** role, definition GUID
`eed3b665-ab3a-47b6-8f48-c9382fb1dad6`, at the Foundry project scope. That role
permits endpoint interaction within the project without agent creation or
modification. Foundry User, project-management, owner, Contributor, and
Cognitive Services roles are deliberately not granted.

This deployment is separate from `main.bicep` so provisioning a Web App or
Foundry project never grants application access automatically. Project scope is
the current least-privilege boundary available without coupling RBAC to prompt
agent lifecycle ownership. Agent-specific scope is a possible future hardening
step after that lifecycle has an appropriate infrastructure owner.

The offline-tested operator boundary is
`scripts/deploy_foundry_agent_consumer_rbac.py`. It exposes no template or role
override and preserves this staged workflow:

```text
offline check
-> explicit Azure what-if
-> separately authorized live deployment request
-> separate read-only assignment verification
```

Check mode validates safe input, the exact expected entry point and parameter
names, its existing Web App identity lookup and module reference, and the
module's project-scoped Consumer role contract. It builds the inert command
plan without constructing a runner or executing `az`:

```bash
.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --check \
  --resource-group fictional-resource-group \
  --web-app-name fictional-nurse-intake-web-app \
  --foundry-account-name fictional-foundry-account \
  --foundry-project-name fictional-foundry-project \
  --json
```

After reviewing that result, `--what-if` is the only preview mode. It issues one
`az deployment group what-if` against the named existing resource group,
requests JSON, accepts only the expected change collection, discards raw Azure
output, and returns separate counts for all seven documented resource change
types: Create, Delete, Ignore, Deploy, NoChange, Modify, and Unsupported. Ignore
remains distinct from NoChange. Delete sets `delete_review_required=true`;
Delete, Deploy, or Unsupported sets `manual_review_required=true`. Truly unknown
types fail closed, and the CLI never advances to live deployment automatically.

Only a separately chosen `--live` issues one `az deployment group create`.
Success means Azure CLI accepted the deployment request; it does not mean the
assignment exists, authorization works, a managed-identity token can be
obtained, or a Foundry agent can be verified or invoked. The command never
creates or deletes a resource group, changes the Consumer role, retries, cleans
up, deploys app code, modifies or restarts the Web App, or calls Foundry.

Build all RBAC templates offline:

```bash
az bicep build --file infra/modules/foundry-agent-consumer-rbac.bicep --stdout > /dev/null
az bicep build --file infra/foundry-agent-consumer-rbac.bicep --stdout > /dev/null
az bicep build --file infra/main.bicep --stdout > /dev/null
```

The following CLI modes are future manual operator actions and were not run in
this slice. Use only fictional, reviewed resource names and data.

Preview the independent assignment:

```bash
.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --what-if \
  --resource-group fictional-resource-group \
  --web-app-name fictional-nurse-intake-web-app \
  --foundry-account-name fictional-foundry-account \
  --foundry-project-name fictional-foundry-project \
  --json
```

Deploy it explicitly after review:

```bash
.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --live \
  --resource-group fictional-resource-group \
  --web-app-name fictional-nurse-intake-web-app \
  --foundry-account-name fictional-foundry-account \
  --foundry-project-name fictional-foundry-project \
  --json
```

Verify the assignment read-only:

```bash
.venv/bin/python scripts/verify_foundry_agent_consumer_rbac.py \
  --check \
  --resource-group <existing-resource-group> \
  --web-app-name <existing-web-app> \
  --foundry-account-name <existing-foundry-account> \
  --foundry-project-name <existing-foundry-project> \
  --json

.venv/bin/python scripts/verify_foundry_agent_consumer_rbac.py \
  --live \
  --resource-group <existing-resource-group> \
  --web-app-name <existing-web-app> \
  --foundry-account-name <existing-foundry-account> \
  --foundry-project-name <existing-foundry-project> \
  --json
```

Run the verifier only after reviewing and explicitly authorizing the deployment.
Its check mode validates names and the fixed local role contract without Azure;
live mode performs only projected identity, project, and assignment reads. It
accepts one exact project-scoped Consumer assignment, rejects broader inherited
scope, and treats duplicate exact records as sanitized parse ambiguity. It never
deploys, repairs, removes, acquires a token, or invokes Foundry.

Cleanup is never automatic. To remove only this role assignment, manually
resolve the same reviewed principal and project scope, then run:

```bash
az role assignment delete \
  --assignee-object-id "$WEB_APP_PRINCIPAL_ID" \
  --role eed3b665-ab3a-47b6-8f48-c9382fb1dad6 \
  --scope "$PROJECT_SCOPE"
```

Deleting the assignment does not delete the Web App, Foundry project, agents,
or resource group. Resource-group deletion also remains a separate, explicit
manual action.

This repository implements and offline-tests separate deployment and read-only
assignment-verification boundaries. This slice ran no live Azure operation, did
not read a deployed assignment, obtained no managed-identity token, and performed
no hosted readiness, Foundry verification, or agent invocation. Infrastructure deployment, RBAC deployment, RBAC verification,
hosted readiness, Foundry verification, and invocation remain separate stages.
Mock providers remain the safe default, hosted notifications remain suppressed,
only fictional data may be used in future live validation, human nurse review
remains mandatory, and this is not production clinical software.

## Existing Web App Configuration Verification

`scripts/verify_web_app_configuration.py` is a read-only boundary for checking
an already-existing Web App before code deployment. Offline check mode validates
the application-owned contract without creating an Azure CLI runner, requiring
credentials, or making an Azure call:

```bash
.venv/bin/python scripts/verify_web_app_configuration.py --check
```

Only explicit live JSON mode performs Azure reads:

```bash
.venv/bin/python scripts/verify_web_app_configuration.py \
  --live \
  --json \
  --resource-group <existing-resource-group> \
  --web-app-name <existing-web-app>
```

Live mode uses three sequential read-only Azure CLI commands with explicit JSON
output projections. JMESPath `--query` shapes the JSON emitted to the Python
verifier; it does not limit what Azure reads. The app-settings command emits only
the eight Bicep-owned settings to the verifier. The application never returns,
logs, or serializes raw unfiltered Azure CLI output. It does not deploy, update
settings, restart, upload code, retrieve credentials, assign RBAC, call Foundry,
retry, or poll. Sanitized results expose only contract booleans, categories,
messages, and next steps; identifiers, hostnames, raw settings, stdout, stderr,
exceptions, and secrets are excluded.

Automated tests use injected fake runners, and no live configuration verification
was run in this slice. Configuration verification does not prove code deployment;
code-deployment request acceptance does not prove startup; hosted readiness,
RBAC, managed-identity Foundry verification, and fictional-data invocation remain
separate operator stages. Mock providers, suppressed notifications, mandatory
nurse review, and the non-production-clinical boundary remain unchanged. Review
the sanitized result before explicitly choosing any next operator action.

## Deterministic Web App Package And Code Deployment

Application packaging and code deployment are separate from infrastructure,
RBAC, prompt-agent provisioning, startup verification, and invocation.
`src/app/services/web_app_package.py` creates a deterministic source deployment
ZIP from an explicit allowlist: `requirements.txt`, Python files under `src`,
YAML configuration under `src/app/config`, and static HTML/CSS/JavaScript under
`src/app/static`. Stable ordering, normalized timestamps, fixed file modes, and
fixed compression make identical inputs byte-for-byte repeatable. Dependencies
are not vendored into this package.

The builder rejects incomplete inputs, unsafe output locations, symlinks, path
escapes, and high-risk source markers. Repository metadata, environments,
tests, docs, Bicep parameters, caches, credentials, local Azure state, and old
artifacts are never selected. Packages are written only beneath the ignored
`.artifacts/web-app/` directory.

Check or build locally without Azure access:

```bash
.venv/bin/python scripts/package_web_app.py --check --json
.venv/bin/python scripts/package_web_app.py --package --json
.venv/bin/python scripts/deploy_web_app_code.py --check --json
```

`scripts/deploy_web_app_code.py` uses one injected command-runner seam. Only
the explicit `--live --json` mode can construct `az webapp deploy`; check and
package modes never create a runner or invoke Azure CLI. Newly provisioned
optional Web Apps receive `SCM_DO_BUILD_DURING_DEPLOYMENT=true` through the
existing Bicep module, allowing App Service remote build automation to install
dependencies from the packaged `requirements.txt`. Code deployment remains the
following separate, explicit command for an existing Web App:

```bash
.venv/bin/python scripts/deploy_web_app_code.py \
  --live \
  --json \
  --resource-group <existing-resource-group> \
  --web-app <existing-web-app>
```

No live code deployment was run in this slice. An accepted CLI request is not
evidence of application startup, health, managed-identity authentication,
Foundry access, or agent invocation. Python ZIP deployment also requires App
Service build automation to install `requirements.txt`; the Bicep-declared
setting is compiled and tested offline only. No live Web App infrastructure or
code deployment, startup, health verification, managed-identity
authentication, Foundry verification, or agent invocation occurred in this
slice.

## Existing Web App Hosted Readiness Verification

`scripts/verify_web_app_readiness.py` is a separate boundary for an
already-existing, already-deployed Web App. Check mode validates and normalizes
an explicit HTTPS origin without constructing an HTTP transport or making a
request:

```bash
.venv/bin/python scripts/verify_web_app_readiness.py \
  --base-url "https://example.azurewebsites.net" \
  --check \
  --json
```

Only explicit live mode creates the standard-library transport. It performs
one read-only GET each to `/health`, `/version`, and `/demo/status`, with a
short timeout and no credentials, body, retries, polling, Azure CLI call, or
mutation:

```bash
.venv/bin/python scripts/verify_web_app_readiness.py \
  --base-url "https://example.azurewebsites.net" \
  --live \
  --json
```

The verifier and CLI are offline-tested with fake transports. No live hosted
verification was run in this slice. Code-deployment request acceptance does not
prove startup, and hosted readiness does not prove RBAC, managed-identity
authentication, Foundry access, or agent invocation. Review the sanitized
result before making any separate operator decision about the next stage.

## Disposable Foundry Workflow

Copy `foundry-only.example.bicepparam` to the ignored
`foundry-only.bicepparam` and replace every placeholder with a model name,
version, publisher format, SKU, capacity, region, and quota combination valid
for the subscription. No model or SKU is selected automatically.

```bash
python scripts/deploy_foundry_infra.py --mode foundry-only --parameters infra/foundry-only.bicepparam --resource-group <resource-group> --location <location> --check
python scripts/deploy_foundry_infra.py --mode foundry-only --parameters infra/foundry-only.bicepparam --resource-group <existing-resource-group> --location <location> --what-if --json
python scripts/deploy_foundry_infra.py --mode foundry-only --parameters infra/foundry-only.bicepparam --resource-group <resource-group> --location <location> --live --json
```

`--check` runs local CLI/version/Bicep build checks only. `--what-if` makes no
changes and requires an existing resource group. Only `--live` creates or
reuses the group and deploys Foundry. Both templates reuse
`modules/foundry.bicep`. Live returns only the safe project endpoint and model
deployment name; it does not edit an environment file or create the Nurse
Intake Agent. Update `.env.foundry-agent.local` manually before running the
separate agent deployment CLI.

Cleanup is manual and explicit:

```bash
az group delete \
  --name <resource-group-name> \
  --yes \
  --no-wait
```

Pytest uses fake runners and never calls Azure. No secrets are stored in Bicep
or examples. Mandatory nurse review remains unchanged, and this is not
production clinical infrastructure.

## Parameters

- `environmentName`: short environment label, such as `dev` or `demo`
- `location`: Azure region; defaults to the resource group's location
- `projectName`: short project name used in resource names
- `cosmosDatabaseName`: Cosmos SQL database name
- `cosmosContainerName`: Cosmos SQL container name
- `deployApp`: optionally create the Web App runtime; defaults to `false`
- `appServicePlanName`: optional explicit plan name
- `webAppName`: optional explicit globally unique Web App name
- `appServicePlanSkuName`: configurable plan SKU; defaults to `B1`
- `pythonLinuxFxVersion`: configurable Linux Python stack; defaults to
  `PYTHON|3.12`

## Offline Build And Validation

These checks compile and inspect local files only. They do not contact an Azure
deployment endpoint or create resources:

```bash
az bicep build --file infra/main.bicep --stdout > /dev/null
.venv/bin/python -m pytest tests/test_web_app_bicep.py tests/test_foundry_bicep.py
```

Because `deployApp=false` and `deployFoundry=false` are the defaults, compiling
or deploying the unchanged full template remains backward-compatible.

## Future Manual Deployment Flow

The following is a future, manual, operator-controlled flow. It is not run by
tests and does not deploy application code or grant Foundry access.

Set a resource group name and region:

```bash
RESOURCE_GROUP=nurse-intake-demo-rg
LOCATION=eastus
```

Create the resource group:

```bash
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"
```

Build the Bicep file:

```bash
az bicep build \
  --file infra/main.bicep
```

Validate the deployment:

```bash
az deployment group validate \
  --resource-group "$RESOURCE_GROUP" \
  --template-file infra/main.bicep \
  --parameters environmentName=demo location="$LOCATION" projectName=nurse-intake cosmosDatabaseName=nurse-intake cosmosContainerName=cases deployApp=true webAppName=<globally-unique-web-app-name>
```

Create the deployment:

```bash
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --name main \
  --template-file infra/main.bicep \
  --parameters environmentName=demo location="$LOCATION" projectName=nurse-intake cosmosDatabaseName=nurse-intake cosmosContainerName=cases deployApp=true webAppName=<globally-unique-web-app-name>
```

## Run App Against Deployed Cosmos DB

`APP_MODE=mock` remains the default local mode. Only set `APP_MODE=cosmos` when
you intentionally want the app to use a deployed Cosmos DB account.

Get the Cosmos endpoint from the latest deployment output:

```bash
COSMOS_ENDPOINT=$(az deployment group show \
  --resource-group "$RESOURCE_GROUP" \
  --name main \
  --query properties.outputs.cosmosEndpoint.value \
  --output tsv)
```

Or get the endpoint directly from the Cosmos account:

```bash
COSMOS_ACCOUNT_NAME=$(az cosmosdb list \
  --resource-group "$RESOURCE_GROUP" \
  --query "[0].name" \
  --output tsv)

COSMOS_ENDPOINT=$(az cosmosdb show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$COSMOS_ACCOUNT_NAME" \
  --query documentEndpoint \
  --output tsv)
```

Get a Cosmos key:

```bash
COSMOS_KEY=$(az cosmosdb keys list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$COSMOS_ACCOUNT_NAME" \
  --query primaryMasterKey \
  --output tsv)
```

Example local environment values:

```bash
APP_MODE=cosmos
COSMOS_ENDPOINT=https://your-account.documents.azure.com:443/
COSMOS_KEY=your-local-development-key
COSMOS_DATABASE_NAME=nurse-intake
COSMOS_CONTAINER_NAME=cases
```

Do not commit `.env` or real Cosmos keys. Keep real secrets local for this MVP
slice.

For the full local-to-Cosmos verification checklist, see
[`docs/manual-cosmos-smoke-test.md`](../docs/manual-cosmos-smoke-test.md).

## Delete Resources

Cleanup is manual and explicit; no script or template automatically deletes a
resource group. After reviewing the resource names carefully, delete the whole
group when the demo is finished to avoid ongoing charges:

```bash
az group delete \
  --name "$RESOURCE_GROUP" \
  --yes
```

## Notes

The Bicep template does not include secrets. Application configuration values such as the Cosmos endpoint can come from deployment outputs, and keys should be handled separately.
