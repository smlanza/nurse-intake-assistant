"""Settings-driven selection for the application secret boundary."""

from collections.abc import Callable

from src.app.config.settings import AppSettings
from src.app.services.azure_key_vault_secret_provider import KeyVaultSecretProvider
from src.app.services.secret_provider import LocalSecretProvider, SecretProvider


def create_secret_provider(
    settings: AppSettings,
    *,
    key_vault_client_factory: Callable[[str], object] | None = None,
) -> SecretProvider:
    """Select a safe local provider or an explicitly enabled Key Vault provider."""

    provider = getattr(settings, "secret_provider_normalized", "local")
    if provider == "local":
        return LocalSecretProvider()
    if provider == "azure-key-vault":
        return KeyVaultSecretProvider(
            vault_uri=getattr(settings, "azure_key_vault_uri", None),
            client_factory=key_vault_client_factory,
        )

    configured = getattr(settings, "secret_provider", provider)
    raise ValueError(f"Unsupported SECRET_PROVIDER: {configured}")
