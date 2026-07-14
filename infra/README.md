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
