from types import SimpleNamespace

import pytest

from src.app.config.settings import AppSettings
from src.app.services.azure_key_vault_secret_provider import KeyVaultSecretProvider
from src.app.services.secret_provider import LocalSecretProvider, SecretProviderError
from src.app.services.secret_provider_factory import create_secret_provider


def test_secret_provider_defaults_to_safe_local_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SECRET_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_KEY_VAULT_URI", raising=False)

    settings = AppSettings()
    provider = create_secret_provider(
        settings,
        key_vault_client_factory=lambda vault_uri: pytest.fail(
            "local selection must not construct Azure dependencies"
        ),
    )

    assert settings.secret_provider == "local"
    assert settings.secret_provider_normalized == "local"
    assert settings.azure_key_vault_uri is None
    assert isinstance(provider, LocalSecretProvider)
    assert provider.diagnostic.to_json_dict() == {
        "provider": "local",
        "configuration_valid": True,
        "client_constructed": False,
        "retrieval_attempted": False,
        "retrieval_succeeded": False,
        "failure_category": None,
    }


def test_key_vault_mode_is_explicit_and_factory_remains_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SECRET_PROVIDER", "  AZURE-KEY-VAULT  ")
    monkeypatch.setenv(
        "AZURE_KEY_VAULT_URI",
        "  https://fictional-vault.vault.azure.net/  ",
    )
    client_factory_calls: list[str] = []

    provider = create_secret_provider(
        AppSettings(),
        key_vault_client_factory=lambda vault_uri: (
            client_factory_calls.append(vault_uri) or object()
        ),
    )

    assert isinstance(provider, KeyVaultSecretProvider)
    assert provider.diagnostic.configuration_valid is True
    assert provider.diagnostic.client_constructed is False
    assert client_factory_calls == []


@pytest.mark.parametrize("vault_uri", [None, "", "   "])
def test_key_vault_mode_rejects_missing_or_blank_uri_before_construction(
    monkeypatch: pytest.MonkeyPatch,
    vault_uri: str | None,
) -> None:
    monkeypatch.setenv("SECRET_PROVIDER", "azure-key-vault")
    if vault_uri is None:
        monkeypatch.delenv("AZURE_KEY_VAULT_URI", raising=False)
    else:
        monkeypatch.setenv("AZURE_KEY_VAULT_URI", vault_uri)

    with pytest.raises(SecretProviderError) as exc_info:
        create_secret_provider(
            AppSettings(),
            key_vault_client_factory=lambda configured_uri: pytest.fail(
                "invalid configuration must fail before dependency construction"
            ),
        )

    assert exc_info.value.category == "configuration_invalid"
    assert exc_info.value.diagnostic.configuration_valid is False
    assert exc_info.value.diagnostic.client_constructed is False


@pytest.mark.parametrize(
    "vault_uri",
    [
        "http://fictional-vault.vault.azure.net/",
        "https://",
        "https://user:password@fictional-vault.vault.azure.net/",
        "https://fictional-vault.vault.azure.net/secrets/name",
        "https://fictional-vault.vault.azure.net/?token=private",
    ],
)
def test_key_vault_mode_rejects_invalid_vault_uri(
    vault_uri: str,
) -> None:
    settings = SimpleNamespace(
        secret_provider="azure-key-vault",
        secret_provider_normalized="azure-key-vault",
        azure_key_vault_uri=vault_uri,
    )

    with pytest.raises(SecretProviderError) as exc_info:
        create_secret_provider(settings)

    assert exc_info.value.category == "configuration_invalid"
    assert vault_uri not in str(exc_info.value)


def test_unsupported_secret_provider_fails_clearly() -> None:
    settings = SimpleNamespace(
        secret_provider="arbitrary",
        secret_provider_normalized="arbitrary",
        azure_key_vault_uri=None,
    )

    with pytest.raises(ValueError, match="Unsupported SECRET_PROVIDER"):
        create_secret_provider(settings)
