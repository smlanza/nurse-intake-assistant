# Nurse Intake Assistant Infrastructure

This folder contains the application infrastructure and a reusable Microsoft
Foundry module. `main.bicep` remains the backward-compatible full-stack entry
point; Foundry is disabled there by default. `foundry-only.bicep` is the
recommended lightweight entry point for disposable daily agent validation.

## Resources

`main.bicep` creates:

- Azure Cosmos DB account in serverless capacity mode
- Cosmos SQL database
- Cosmos SQL container named `cases` by default
- `/createdDate` partition key for the cases container
- Azure Storage account for future artifacts or logs
- Log Analytics workspace
- Application Insights resource connected to the workspace

The full template creates no Foundry resources unless `deployFoundry=true`.
Neither entry point creates Speech, ACS, Key Vault, App Service, private
networking, or production clinical infrastructure.

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

## Validate And Deploy

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
  --parameters environmentName=demo location="$LOCATION" projectName=nurse-intake cosmosDatabaseName=nurse-intake cosmosContainerName=cases
```

Create the deployment:

```bash
az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --name main \
  --template-file infra/main.bicep \
  --parameters environmentName=demo location="$LOCATION" projectName=nurse-intake cosmosDatabaseName=nurse-intake cosmosContainerName=cases
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

Delete the whole resource group when the demo is finished to avoid ongoing charges:

```bash
az group delete \
  --name "$RESOURCE_GROUP" \
  --yes
```

## Notes

The Bicep template does not include secrets. Application configuration values such as the Cosmos endpoint can come from deployment outputs, and keys should be handled separately.
