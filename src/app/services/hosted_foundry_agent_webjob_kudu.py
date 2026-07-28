from dataclasses import dataclass
import json
import re
from typing import Literal, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from src.app.services.hosted_foundry_agent_webjob_package import (
    WEBJOB_ARCHIVE_MEMBER,
    WEBJOB_NAME,
)


KUDU_BEARER_TOKEN_COMMAND = (
    "az",
    "account",
    "get-access-token",
    "--resource",
    "https://management.azure.com/",
    "--query",
    "accessToken",
    "--output",
    "tsv",
    "--only-show-errors",
)
MAX_DISCOVERY_RESPONSE_SIZE = 64 * 1024
DiscoveryCategory = Literal[
    "success",
    "authentication_or_authorization_failed",
    "remote_webjob_missing",
    "discovery_throttled",
    "discovery_service_failed",
    "discovery_failed",
    "discovery_ambiguous",
    "discovery_response_invalid",
]
class CommandRunner(Protocol):
    def run(self, args: list[str]): ...


class KuduWebJobDiscoverer(Protocol):
    def discover(
        self,
        web_app_name: str,
        webjob_name: str,
    ) -> "KuduWebJobDiscoveryResult": ...


@dataclass(frozen=True)
class KuduWebJobDiscoveryResult:
    category: DiscoveryCategory
    discovery_attempted: bool
    remote_webjob_discovered: bool

    @classmethod
    def success(cls) -> "KuduWebJobDiscoveryResult":
        return cls("success", True, True)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "category": self.category,
            "discovery_attempted": self.discovery_attempted,
            "remote_webjob_discovered": self.remote_webjob_discovered,
        }


def acquire_kudu_bearer_token(runner: CommandRunner) -> str | None:
    try:
        outcome = runner.run(list(KUDU_BEARER_TOKEN_COMMAND))
    except Exception:
        return None
    if (
        type(getattr(outcome, "return_code", None)) is not int
        or outcome.return_code != 0
        or not isinstance(getattr(outcome, "stdout", None), str)
    ):
        return None
    token = outcome.stdout.rstrip("\r\n")
    return (
        token
        if (
            1 <= len(token) <= 16384
            and token == token.strip()
            and re.fullmatch(r"[A-Za-z0-9._~+/=\-]+", token)
        )
        else None
    )


def _safe_web_app_name(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and 1 <= len(value) <= 60
        and re.fullmatch(r"[A-Za-z0-9\-]+", value)
    )


def kudu_triggered_webjob_url(
    web_app_name: str,
    webjob_name: str,
) -> str | None:
    if (
        not _safe_web_app_name(web_app_name)
        or webjob_name != WEBJOB_NAME
    ):
        return None
    return (
        f"https://{web_app_name}.scm.azurewebsites.net/"
        f"api/triggeredwebjobs/{quote(webjob_name, safe='')}"
    )


@dataclass(frozen=True)
class _JsonObject:
    pairs: tuple[tuple[str, object], ...]


def _json_object(pairs: list[tuple[str, object]]) -> _JsonObject:
    return _JsonObject(tuple(pairs))


def _latest_run_valid(value: object) -> bool:
    return value is None or isinstance(value, _JsonObject)


def _discovery_payload_valid(payload: object) -> bool:
    if not isinstance(payload, _JsonObject):
        return False
    names = tuple(name for name, _value in payload.pairs)
    if len(names) != len(set(names)):
        return False
    values = dict(payload.pairs)
    if (
        values.get("name") != WEBJOB_NAME
        or values.get("run_command") != WEBJOB_ARCHIVE_MEMBER
    ):
        return False
    return "latest_run" not in values or _latest_run_valid(
        values["latest_run"]
    )


class KuduTriggeredWebJobDiscoverer:
    def __init__(
        self,
        *,
        token_runner: CommandRunner,
        opener=None,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._token_runner = token_runner
        self._opener = opener or build_opener()
        self._timeout_seconds = timeout_seconds

    @staticmethod
    def _http_failure(status: object) -> DiscoveryCategory:
        if status in {401, 403}:
            return "authentication_or_authorization_failed"
        if status == 404:
            return "remote_webjob_missing"
        if status == 429:
            return "discovery_throttled"
        if isinstance(status, int) and 500 <= status <= 599:
            return "discovery_service_failed"
        return "discovery_failed"

    def discover(
        self,
        web_app_name: str,
        webjob_name: str,
    ) -> KuduWebJobDiscoveryResult:
        url = kudu_triggered_webjob_url(web_app_name, webjob_name)
        if url is None:
            return KuduWebJobDiscoveryResult(
                "discovery_response_invalid",
                False,
                False,
            )
        token = acquire_kudu_bearer_token(self._token_runner)
        if token is None:
            return KuduWebJobDiscoveryResult(
                "authentication_or_authorization_failed",
                False,
                False,
            )
        request = Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with self._opener.open(
                request,
                timeout=self._timeout_seconds,
            ) as response:
                status = getattr(response, "status", None)
                if status != 200:
                    if not isinstance(status, int):
                        category: DiscoveryCategory = (
                            "discovery_ambiguous"
                        )
                    else:
                        category = self._http_failure(status)
                    return KuduWebJobDiscoveryResult(
                        category,
                        True,
                        False,
                    )
                body = response.read(MAX_DISCOVERY_RESPONSE_SIZE + 1)
        except HTTPError as error:
            return KuduWebJobDiscoveryResult(
                self._http_failure(error.code),
                True,
                False,
            )
        except (URLError, TimeoutError, OSError):
            return KuduWebJobDiscoveryResult(
                "discovery_ambiguous",
                True,
                False,
            )
        except Exception:
            return KuduWebJobDiscoveryResult(
                "discovery_ambiguous",
                True,
                False,
            )
        if (
            not isinstance(body, bytes)
            or not body
            or len(body) > MAX_DISCOVERY_RESPONSE_SIZE
        ):
            return KuduWebJobDiscoveryResult(
                "discovery_response_invalid",
                True,
                False,
            )
        try:
            payload = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_json_object,
            )
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError):
            return KuduWebJobDiscoveryResult(
                "discovery_response_invalid",
                True,
                False,
            )
        if not _discovery_payload_valid(payload):
            return KuduWebJobDiscoveryResult(
                "discovery_response_invalid",
                True,
                False,
            )
        return KuduWebJobDiscoveryResult.success()
