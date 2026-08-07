"""Lazy Azure Key Vault Secrets adapter for exact-name retrieval."""

from collections.abc import Callable
from typing import Protocol
from urllib.parse import urlparse

from src.app.services.secret_provider import (
    SecretProviderError,
    SecretProviderFailureCategory,
    SecretRetrievalDiagnostic,
    _valid_secret_name,
)


class _SecretClient(Protocol):
    def get_secret(self, name: str) -> object:
        ...


class KeyVaultSecretProvider:
    """Retrieve one known secret through a lazily constructed Key Vault client."""

    def __init__(
        self,
        *,
        vault_uri: str | None,
        client: _SecretClient | None = None,
        client_factory: Callable[[str], _SecretClient] | None = None,
    ) -> None:
        if not _valid_vault_uri(vault_uri):
            diagnostic = SecretRetrievalDiagnostic(
                provider="azure-key-vault",
                configuration_valid=False,
                client_constructed=False,
                retrieval_attempted=False,
                retrieval_succeeded=False,
                failure_category="configuration_invalid",
            )
            raise SecretProviderError("configuration_invalid", diagnostic)

        self._vault_uri = vault_uri
        self._client = client
        self._client_factory = client_factory or _create_key_vault_secret_client
        self._diagnostic = SecretRetrievalDiagnostic(
            provider="azure-key-vault",
            configuration_valid=True,
            client_constructed=client is not None,
            retrieval_attempted=False,
            retrieval_succeeded=False,
        )

    @property
    def diagnostic(self) -> SecretRetrievalDiagnostic:
        return self._diagnostic

    def get_secret(self, name: str) -> str:
        if not _valid_secret_name(name):
            self._fail(
                "request_invalid",
                client_constructed=self._client is not None,
                retrieval_attempted=False,
            )

        client = self._client
        if client is None:
            construction_failed = False
            try:
                client = self._client_factory(self._vault_uri)
            except Exception:
                construction_failed = True
            if construction_failed:
                self._fail(
                    "dependency_unavailable",
                    client_constructed=False,
                    retrieval_attempted=False,
                )
            self._client = client

        self._diagnostic = SecretRetrievalDiagnostic(
            provider="azure-key-vault",
            configuration_valid=True,
            client_constructed=True,
            retrieval_attempted=True,
            retrieval_succeeded=False,
        )
        failure_category: SecretProviderFailureCategory | None = None
        response: object | None = None
        try:
            response = client.get_secret(name)
        except Exception as error:
            failure_category = _retrieval_failure_category(error)

        if failure_category is not None:
            self._fail(
                failure_category,
                client_constructed=True,
                retrieval_attempted=True,
            )

        value = getattr(response, "value", None)
        if not isinstance(value, str) or not value:
            self._fail(
                "provider_response_invalid",
                client_constructed=True,
                retrieval_attempted=True,
            )

        self._diagnostic = SecretRetrievalDiagnostic(
            provider="azure-key-vault",
            configuration_valid=True,
            client_constructed=True,
            retrieval_attempted=True,
            retrieval_succeeded=True,
        )
        return value

    def _fail(
        self,
        category: SecretProviderFailureCategory,
        *,
        client_constructed: bool,
        retrieval_attempted: bool,
    ) -> None:
        self._diagnostic = SecretRetrievalDiagnostic(
            provider="azure-key-vault",
            configuration_valid=category != "configuration_invalid",
            client_constructed=client_constructed,
            retrieval_attempted=retrieval_attempted,
            retrieval_succeeded=False,
            failure_category=category,
        )
        raise SecretProviderError(category, self._diagnostic)


def _valid_vault_uri(vault_uri: object) -> bool:
    if not isinstance(vault_uri, str) or not vault_uri or vault_uri != vault_uri.strip():
        return False
    parsed = urlparse(vault_uri)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.username is None
        and parsed.password is None
        and parsed.path in {"", "/"}
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
    )


def _retrieval_failure_category(error: Exception) -> SecretProviderFailureCategory:
    status_code = getattr(error, "status_code", None)
    if not isinstance(status_code, int):
        status_code = getattr(getattr(error, "response", None), "status_code", None)
    if status_code == 401:
        return "authentication_failed"
    if status_code == 403:
        return "authorization_failed"
    if status_code == 404:
        return "secret_not_found"
    return "retrieval_failed"


def _create_key_vault_secret_client(vault_uri: str) -> _SecretClient:
    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    credential = DefaultAzureCredential()
    return SecretClient(vault_url=vault_uri, credential=credential)
