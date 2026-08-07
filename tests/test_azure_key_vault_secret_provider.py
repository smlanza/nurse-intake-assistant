import json
from types import SimpleNamespace

import pytest

from src.app.services.azure_key_vault_secret_provider import KeyVaultSecretProvider
from src.app.services.secret_provider import SecretProviderError


SECRET_VALUE = "private-value-must-never-be-serialized"
VAULT_URI = "https://fictional-vault.vault.azure.net/"
SECRET_NAME = "fictional-secret-name"


class FakeSecretClient:
    def __init__(
        self,
        *,
        response: object = SimpleNamespace(value=SECRET_VALUE),
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.get_secret_calls: list[str] = []

    def get_secret(self, name: str) -> object:
        self.get_secret_calls.append(name)
        if self.error is not None:
            raise self.error
        return self.response


class FakeHttpError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_provider_constructs_dependencies_only_for_first_retrieval() -> None:
    client = FakeSecretClient()
    factory_calls: list[str] = []
    provider = KeyVaultSecretProvider(
        vault_uri=VAULT_URI,
        client_factory=lambda vault_uri: factory_calls.append(vault_uri) or client,
    )

    assert factory_calls == []
    assert provider.diagnostic.client_constructed is False

    assert provider.get_secret(SECRET_NAME) == SECRET_VALUE

    assert factory_calls == [VAULT_URI]
    assert client.get_secret_calls == [SECRET_NAME]


def test_exact_name_retrieval_returns_private_value_but_diagnostic_omits_it() -> None:
    client = FakeSecretClient()
    provider = KeyVaultSecretProvider(vault_uri=VAULT_URI, client=client)

    value = provider.get_secret(SECRET_NAME)
    serialized = json.dumps(provider.diagnostic.to_json_dict())

    assert value == SECRET_VALUE
    assert client.get_secret_calls == [SECRET_NAME]
    assert provider.diagnostic.retrieval_succeeded is True
    assert SECRET_VALUE not in serialized
    assert SECRET_NAME not in serialized
    assert VAULT_URI not in serialized


@pytest.mark.parametrize(
    ("status_code", "expected_category"),
    [
        (401, "authentication_failed"),
        (403, "authorization_failed"),
        (404, "secret_not_found"),
    ],
)
def test_known_provider_failures_map_to_sanitized_categories(
    status_code: int,
    expected_category: str,
) -> None:
    raw_detail = f"Bearer token {SECRET_VALUE} {VAULT_URI} {SECRET_NAME}"
    provider = KeyVaultSecretProvider(
        vault_uri=VAULT_URI,
        client=FakeSecretClient(error=FakeHttpError(status_code, raw_detail)),
    )

    with pytest.raises(SecretProviderError) as exc_info:
        provider.get_secret(SECRET_NAME)

    serialized = json.dumps(exc_info.value.diagnostic.to_json_dict())
    assert exc_info.value.category == expected_category
    assert exc_info.value.__cause__ is None
    assert raw_detail not in str(exc_info.value)
    assert SECRET_VALUE not in serialized
    assert VAULT_URI not in serialized
    assert SECRET_NAME not in serialized


def test_unknown_provider_failure_collapses_to_sanitized_generic_category() -> None:
    provider = KeyVaultSecretProvider(
        vault_uri=VAULT_URI,
        client=FakeSecretClient(
            error=RuntimeError(f"raw SDK response {SECRET_VALUE} {VAULT_URI}")
        ),
    )

    with pytest.raises(SecretProviderError) as exc_info:
        provider.get_secret(SECRET_NAME)

    assert exc_info.value.category == "retrieval_failed"
    assert SECRET_VALUE not in str(exc_info.value)
    assert VAULT_URI not in str(exc_info.value)


@pytest.mark.parametrize(
    "response",
    [None, object(), SimpleNamespace(), SimpleNamespace(value=None), SimpleNamespace(value="")],
)
def test_malformed_provider_response_fails_closed(response: object) -> None:
    provider = KeyVaultSecretProvider(
        vault_uri=VAULT_URI,
        client=FakeSecretClient(response=response),
    )

    with pytest.raises(SecretProviderError) as exc_info:
        provider.get_secret(SECRET_NAME)

    assert exc_info.value.category == "provider_response_invalid"
    assert exc_info.value.diagnostic.retrieval_succeeded is False


def test_dependency_construction_failure_is_sanitized() -> None:
    raw_detail = f"missing SDK credential {SECRET_VALUE} {VAULT_URI}"

    def failing_factory(vault_uri: str) -> object:
        raise RuntimeError(raw_detail)

    provider = KeyVaultSecretProvider(
        vault_uri=VAULT_URI,
        client_factory=failing_factory,
    )

    with pytest.raises(SecretProviderError) as exc_info:
        provider.get_secret(SECRET_NAME)

    assert exc_info.value.category == "dependency_unavailable"
    assert exc_info.value.diagnostic.client_constructed is False
    assert exc_info.value.diagnostic.retrieval_attempted is False
    assert raw_detail not in str(exc_info.value)


@pytest.mark.parametrize("name", ["", "   ", " name-with-surrounding-space "])
def test_invalid_secret_name_fails_before_client_construction(name: str) -> None:
    provider = KeyVaultSecretProvider(
        vault_uri=VAULT_URI,
        client_factory=lambda vault_uri: pytest.fail(
            "invalid request must fail before dependency construction"
        ),
    )

    with pytest.raises(SecretProviderError) as exc_info:
        provider.get_secret(name)

    assert exc_info.value.category == "request_invalid"
    assert exc_info.value.diagnostic.client_constructed is False
    assert exc_info.value.diagnostic.retrieval_attempted is False


def test_boundary_exposes_no_discovery_or_mutation_operations() -> None:
    public_names = {
        name
        for name in dir(KeyVaultSecretProvider)
        if not name.startswith("_")
    }

    assert public_names == {"diagnostic", "get_secret"}
