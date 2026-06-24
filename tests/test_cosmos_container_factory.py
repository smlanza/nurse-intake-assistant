import pytest


class FakeContainer:
    pass


class FakeDatabase:
    def __init__(self) -> None:
        self.requested_container_name: str | None = None
        self.container = FakeContainer()

    def get_container_client(self, container_name: str) -> FakeContainer:
        self.requested_container_name = container_name
        return self.container


class FakeCosmosClient:
    endpoint: str | None = None
    credential: str | None = None
    instance: "FakeCosmosClient | None" = None

    def __init__(self, endpoint: str, credential: str) -> None:
        self.endpoint = endpoint
        self.credential = credential
        self.requested_database_name: str | None = None
        self.database = FakeDatabase()
        FakeCosmosClient.instance = self

    def get_database_client(self, database_name: str) -> FakeDatabase:
        self.requested_database_name = database_name
        return self.database


def cosmos_settings(monkeypatch: pytest.MonkeyPatch):
    from src.app.config.settings import AppSettings

    monkeypatch.setenv("APP_MODE", "cosmos")
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://account.documents.azure.com")
    monkeypatch.setenv("COSMOS_KEY", "secret-key")
    monkeypatch.setenv("COSMOS_DATABASE_NAME", "intake-db")
    monkeypatch.setenv("COSMOS_CONTAINER_NAME", "cases")
    return AppSettings()


def test_create_cosmos_container_requires_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.cosmos_container_factory import create_cosmos_container

    settings = cosmos_settings(monkeypatch)
    settings.cosmos_endpoint = None

    with pytest.raises(
        ValueError,
        match="COSMOS_ENDPOINT is required for cosmos APP_MODE",
    ):
        create_cosmos_container(settings, cosmos_client_class=FakeCosmosClient)


def test_create_cosmos_container_requires_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.cosmos_container_factory import create_cosmos_container

    settings = cosmos_settings(monkeypatch)
    settings.cosmos_key = None

    with pytest.raises(
        ValueError,
        match="COSMOS_KEY is required for cosmos APP_MODE",
    ):
        create_cosmos_container(settings, cosmos_client_class=FakeCosmosClient)


def test_blank_endpoint_and_key_are_treated_as_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings
    from src.app.services.cosmos_container_factory import create_cosmos_container

    monkeypatch.setenv("APP_MODE", "cosmos")
    monkeypatch.setenv("COSMOS_ENDPOINT", "   ")
    monkeypatch.setenv("COSMOS_KEY", "   ")

    settings = AppSettings()

    with pytest.raises(ValueError, match="COSMOS_ENDPOINT"):
        create_cosmos_container(settings, cosmos_client_class=FakeCosmosClient)


def test_create_cosmos_container_returns_configured_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.services.cosmos_container_factory import create_cosmos_container

    settings = cosmos_settings(monkeypatch)

    container = create_cosmos_container(
        settings,
        cosmos_client_class=FakeCosmosClient,
    )

    client = FakeCosmosClient.instance
    assert client is not None
    assert client.endpoint == "https://account.documents.azure.com"
    assert client.credential == "secret-key"
    assert client.requested_database_name == "intake-db"
    assert client.database.requested_container_name == "cases"
    assert container is client.database.container


def test_create_cosmos_container_accepts_trimmed_endpoint_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.app.config.settings import AppSettings
    from src.app.services.cosmos_container_factory import create_cosmos_container

    monkeypatch.setenv("APP_MODE", "cosmos")
    monkeypatch.setenv("COSMOS_ENDPOINT", "  https://trimmed.documents.azure.com  ")
    monkeypatch.setenv("COSMOS_KEY", "  trimmed-key  ")
    monkeypatch.setenv("COSMOS_DATABASE_NAME", "nurse-intake")
    monkeypatch.setenv("COSMOS_CONTAINER_NAME", "cases")

    create_cosmos_container(AppSettings(), cosmos_client_class=FakeCosmosClient)

    client = FakeCosmosClient.instance
    assert client is not None
    assert client.endpoint == "https://trimmed.documents.azure.com"
    assert client.credential == "trimmed-key"
