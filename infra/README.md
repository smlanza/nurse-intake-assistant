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

Build all RBAC templates offline:

```bash
az bicep build --file infra/modules/foundry-agent-consumer-rbac.bicep --stdout > /dev/null
az bicep build --file infra/foundry-agent-consumer-rbac.bicep --stdout > /dev/null
az bicep build --file infra/main.bicep --stdout > /dev/null
```

The following commands are future manual operator actions and were not run in
this slice. Use only fictional or carefully reviewed resource names.

Preview the independent assignment:

```bash
az deployment group what-if \
  --resource-group <existing-resource-group> \
  --template-file infra/foundry-agent-consumer-rbac.bicep \
  --parameters webAppName=<existing-web-app> foundryAccountName=<existing-foundry-account> foundryProjectName=<existing-foundry-project>
```

Deploy it explicitly after review:

```bash
az deployment group create \
  --resource-group <existing-resource-group> \
  --name foundry-agent-consumer-rbac \
  --template-file infra/foundry-agent-consumer-rbac.bicep \
  --parameters webAppName=<existing-web-app> foundryAccountName=<existing-foundry-account> foundryProjectName=<existing-foundry-project>
```

Verify the assignment read-only:

```bash
PROJECT_SCOPE=$(az resource show \
  --resource-group <existing-resource-group> \
  --resource-type Microsoft.CognitiveServices/accounts/projects \
  --name <existing-foundry-account>/<existing-foundry-project> \
  --api-version 2025-06-01 \
  --query id --output tsv)

WEB_APP_PRINCIPAL_ID=$(az webapp identity show \
  --resource-group <existing-resource-group> \
  --name <existing-web-app> \
  --query principalId --output tsv)

az role assignment list \
  --assignee-object-id "$WEB_APP_PRINCIPAL_ID" \
  --scope "$PROJECT_SCOPE" \
  --role eed3b665-ab3a-47b6-8f48-c9382fb1dad6 \
  --fill-principal-name false \
  --fill-role-definition-name false \
  --query "[].{RoleDefinitionId:roleDefinitionId,Scope:scope}" \
  --output table
```

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
package modes never create a runner or invoke Azure CLI. After the build
prerequisite below is added and reviewed, this future command can upload code
only to an existing Web App:

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
Service build automation such as `SCM_DO_BUILD_DURING_DEPLOYMENT=true` to
install `requirements.txt`. The current infrastructure has not added or proven
that prerequisite. This slice does not alter app settings, and no live code
deployment should occur until the setting is added and reviewed.

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
