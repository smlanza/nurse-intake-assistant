# Nurse Intake Assistant Infrastructure

This folder contains the minimal Bicep baseline for a Phase 1 MVP demo deployment.

## Resources

`main.bicep` creates:

- Azure Cosmos DB account in serverless capacity mode
- Cosmos SQL database
- Cosmos SQL container named `cases` by default
- `/createdDate` partition key for the cases container
- Azure Storage account for future artifacts or logs
- Log Analytics workspace
- Application Insights resource connected to the workspace

The template does not create Azure AI Foundry, Speech, ACS Email, ACS SMS, Key Vault, App Service, private networking, managed identities, or CI/CD resources yet.

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

## Delete Resources

Delete the whole resource group when the demo is finished to avoid ongoing charges:

```bash
az group delete \
  --name "$RESOURCE_GROUP" \
  --yes
```

## Notes

The Bicep template does not include secrets. Application configuration values such as the Cosmos endpoint can come from deployment outputs, and keys should be handled separately.
