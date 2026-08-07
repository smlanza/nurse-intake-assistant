"""Application-owned secret retrieval contract and sanitized diagnostics."""

from dataclasses import asdict, dataclass
from typing import Literal, Protocol


SecretProviderName = Literal["local", "azure-key-vault"]
SecretProviderFailureCategory = Literal[
    "configuration_invalid",
    "request_invalid",
    "dependency_unavailable",
    "authentication_failed",
    "authorization_failed",
    "secret_not_found",
    "provider_response_invalid",
    "retrieval_failed",
]

SECRET_PROVIDER_MESSAGES: dict[SecretProviderFailureCategory, str] = {
    "configuration_invalid": "Secret provider configuration is invalid.",
    "request_invalid": "The secret retrieval request is invalid.",
    "dependency_unavailable": "Secret provider dependencies are unavailable.",
    "authentication_failed": "Secret provider authentication failed.",
    "authorization_failed": "Secret provider authorization failed.",
    "secret_not_found": "The requested secret was not found.",
    "provider_response_invalid": "The secret provider response is invalid.",
    "retrieval_failed": "Secret retrieval failed.",
}


@dataclass(frozen=True)
class SecretRetrievalDiagnostic:
    """Bounded retrieval state that can never contain secret identities or values."""

    provider: SecretProviderName
    configuration_valid: bool
    client_constructed: bool
    retrieval_attempted: bool
    retrieval_succeeded: bool
    failure_category: SecretProviderFailureCategory | None = None

    def __post_init__(self) -> None:
        if self.retrieval_succeeded and not self.retrieval_attempted:
            raise ValueError("Successful retrieval requires an attempt")
        if self.retrieval_succeeded and self.failure_category is not None:
            raise ValueError("Successful retrieval cannot have a failure category")
        if self.failure_category is not None and self.retrieval_succeeded:
            raise ValueError("Failed retrieval cannot be successful")

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


class SecretProviderError(RuntimeError):
    """Deterministic failure that excludes provider exception details."""

    def __init__(
        self,
        category: SecretProviderFailureCategory,
        diagnostic: SecretRetrievalDiagnostic,
    ) -> None:
        super().__init__(SECRET_PROVIDER_MESSAGES[category])
        self.category = category
        self.diagnostic = diagnostic


class SecretProvider(Protocol):
    """Retrieve one caller-specified secret by its exact name."""

    @property
    def diagnostic(self) -> SecretRetrievalDiagnostic:
        ...

    def get_secret(self, name: str) -> str:
        ...


class LocalSecretProvider:
    """Safe default with no backing store and no Azure dependencies."""

    def __init__(self) -> None:
        self._diagnostic = SecretRetrievalDiagnostic(
            provider="local",
            configuration_valid=True,
            client_constructed=False,
            retrieval_attempted=False,
            retrieval_succeeded=False,
        )

    @property
    def diagnostic(self) -> SecretRetrievalDiagnostic:
        return self._diagnostic

    def get_secret(self, name: str) -> str:
        if not _valid_secret_name(name):
            category: SecretProviderFailureCategory = "request_invalid"
            attempted = False
        else:
            category = "secret_not_found"
            attempted = True
        self._diagnostic = SecretRetrievalDiagnostic(
            provider="local",
            configuration_valid=True,
            client_constructed=False,
            retrieval_attempted=attempted,
            retrieval_succeeded=False,
            failure_category=category,
        )
        raise SecretProviderError(category, self._diagnostic)


def _valid_secret_name(name: object) -> bool:
    return isinstance(name, str) and bool(name) and name == name.strip()
