# Manual Cosmos DB Smoke Test

Use this checklist to verify the local FastAPI app can write to and read from a
deployed Azure Cosmos DB account. This is a manual verification path only; do
not add automated tests that depend on live Azure resources.

`APP_MODE=mock` remains the default local mode. Switch to `APP_MODE=cosmos` only
for this smoke test, then switch back when finished.

## Safety

Do not commit `.env` or real Cosmos keys. Keep the dev resource group disposable,
and delete it when the smoke test is done to avoid ongoing charges.

## 1. Confirm Dev Infrastructure Exists

Set the resource group and region used for the dev deployment:

```bash
RESOURCE_GROUP=rg-nurse-intake-dev
LOCATION=eastus
```

Confirm the resource group exists:

```bash
az group exists \
  --name "$RESOURCE_GROUP"
```

If it returns `false`, deploy the baseline infrastructure:

```bash
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION"

az deployment group create \
  --resource-group "$RESOURCE_GROUP" \
  --name main \
  --template-file infra/main.bicep \
  --parameters environmentName=dev location="$LOCATION" projectName=nurse-intake cosmosDatabaseName=nurse-intake cosmosContainerName=cases
```

## 2. Retrieve Cosmos Settings

Get the Cosmos account name and endpoint from the deployed resource group:

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

Get a local development key:

```bash
COSMOS_KEY=$(az cosmosdb keys list \
  --resource-group "$RESOURCE_GROUP" \
  --name "$COSMOS_ACCOUNT_NAME" \
  --query primaryMasterKey \
  --output tsv)
```

## 3. Update Local `.env`

Create or update `.env` with the deployed Cosmos values:

```bash
APP_MODE=cosmos
COSMOS_ENDPOINT=https://your-account.documents.azure.com:443/
COSMOS_KEY=your-real-local-development-key
COSMOS_DATABASE_NAME=nurse-intake
COSMOS_CONTAINER_NAME=cases
DEMO_SUPPRESS_NOTIFICATIONS=true
```

Replace `COSMOS_ENDPOINT` and `COSMOS_KEY` with the values retrieved above. Do
not commit this file.

## 4. Start The App Locally

Start FastAPI with the local `.env` file:

```bash
.venv/bin/uvicorn src.app.main:app \
  --reload \
  --env-file .env
```

In a second terminal, confirm the app is running:

```bash
curl http://127.0.0.1:8000/health
```

## 5. Submit A Text Intake

Send a simple text intake request:

```bash
curl -s -X POST http://127.0.0.1:8000/intake/text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "My name is Jane Doe. DOB: 1980-04-15. My callback number is +1 (555) 555-0123. I need a medication refill.",
    "sourceSystem": "manual-cosmos-smoke-test",
    "sourceCallId": "manual-smoke-001"
  }'
```

Confirm the JSON response includes:

- `id`
- `createdDate`
- `processingStatus` set to `Completed`
- `caseType` set to `text-intake`

Save the returned `id` and `createdDate` values:

```bash
CASE_ID=returned-case-id
CREATED_DATE=YYYY-MM-DD
```

## 6. Retrieve The Saved Case

Use the `createdDate` query parameter so Cosmos can perform the point read with
the `/createdDate` partition key:

```bash
curl -s "http://127.0.0.1:8000/cases/$CASE_ID?createdDate=$CREATED_DATE"
```

Confirm the returned document has the same `id` and `createdDate` as the intake
response.

## 7. Verify The Document In Azure

Use the Azure Portal:

1. Open the dev resource group.
2. Open the Cosmos DB account.
3. Go to Data Explorer.
4. Open the `nurse-intake` database and `cases` container.
5. Query for the case:

```sql
SELECT * FROM c WHERE c.id = "returned-case-id"
```

Confirm the document exists and its `createdDate` matches the value returned by
the app.

## 8. Restore Safe Local Defaults

After the smoke test, switch local mode back to mock:

```bash
APP_MODE=mock
```

Remove real Cosmos keys from `.env` if they are no longer needed locally.

## 9. Delete Dev Resources

When testing is complete, delete the disposable dev resource group for cost
control:

```bash
az group delete \
  --name "$RESOURCE_GROUP" \
  --yes
```

Confirm deletion:

```bash
az group exists \
  --name "$RESOURCE_GROUP"
```

The command should return `false`.
