"""Shared lazy Azure credential construction for Foundry Agent operations."""

from collections.abc import Callable
from dataclasses import dataclass


FOUNDRY_CREDENTIAL_UNAVAILABLE_MESSAGE = (
    "Azure credential support is unavailable for this explicit Foundry operation."
)


@dataclass(frozen=True)
class FoundryCredentialConfiguration:
    managed_identity_client_id: str | None = None

    def __post_init__(self) -> None:
        value = self.managed_identity_client_id
        normalized = value.strip() or None if value is not None else None
        object.__setattr__(self, "managed_identity_client_id", normalized)


class FoundryCredentialFactoryError(RuntimeError):
    """Sanitized failure from explicit Foundry credential construction."""

    def __init__(self, *, category: str) -> None:
        super().__init__(FOUNDRY_CREDENTIAL_UNAVAILABLE_MESSAGE)
        self.category = category


class FoundryCredentialFactory:
    """Create one DefaultAzureCredential without requesting a token."""

    def __init__(
        self,
        *,
        credential_constructor: Callable[..., object] | None = None,
    ) -> None:
        self._credential_constructor = credential_constructor

    def create(
        self,
        configuration: FoundryCredentialConfiguration,
    ) -> object:
        constructor = self._credential_constructor
        if constructor is None:
            try:
                from azure.identity import DefaultAzureCredential
            except Exception as exc:
                raise FoundryCredentialFactoryError(
                    category="sdk_unavailable"
                ) from exc
            constructor = DefaultAzureCredential

        kwargs: dict[str, object] = {}
        if configuration.managed_identity_client_id is not None:
            kwargs["managed_identity_client_id"] = (
                configuration.managed_identity_client_id
            )
        try:
            return constructor(**kwargs)
        except Exception as exc:
            raise FoundryCredentialFactoryError(
                category="credential_creation_failed"
            ) from exc
