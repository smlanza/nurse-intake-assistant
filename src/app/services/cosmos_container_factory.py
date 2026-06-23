from typing import Any

from src.app.config.settings import AppSettings


def create_cosmos_container(
    settings: AppSettings,
    cosmos_client_class: type[Any] | None = None,
) -> Any:
    """Create the configured Azure Cosmos DB container client."""

    if settings.cosmos_endpoint is None:
        raise ValueError("COSMOS_ENDPOINT is required for cosmos APP_MODE")
    if settings.cosmos_key is None:
        raise ValueError("COSMOS_KEY is required for cosmos APP_MODE")

    client_class = cosmos_client_class or _get_cosmos_client_class()
    client = client_class(settings.cosmos_endpoint, credential=settings.cosmos_key)
    database = client.get_database_client(settings.cosmos_database_name)
    return database.get_container_client(settings.cosmos_container_name)


def _get_cosmos_client_class() -> type[Any]:
    from azure.cosmos import CosmosClient

    return CosmosClient
