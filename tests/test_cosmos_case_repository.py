import asyncio
from datetime import date, datetime, timezone
from typing import Any

from src.app.models.case import CaseDocument


class FakeNotFoundError(Exception):
    pass


class FakeCosmosContainer:
    def __init__(self) -> None:
        self.upserted_items: list[dict[str, Any]] = []
        self.read_calls: list[dict[str, str]] = []
        self.read_result: dict[str, Any] | None = None
        self.read_error: Exception | None = None

    async def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.upserted_items.append(body)
        return body

    async def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        self.read_calls.append({"item": item, "partition_key": partition_key})
        if self.read_error is not None:
            raise self.read_error
        assert self.read_result is not None
        return self.read_result


class SyncFakeCosmosContainer:
    def __init__(self) -> None:
        self.upserted_items: list[dict[str, Any]] = []
        self.read_calls: list[dict[str, str]] = []
        self.read_result: dict[str, Any] | None = None

    def upsert_item(self, body: dict[str, Any]) -> dict[str, Any]:
        self.upserted_items.append(body)
        return body

    def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        self.read_calls.append({"item": item, "partition_key": partition_key})
        assert self.read_result is not None
        return self.read_result


class FakeQueryCosmosContainer:
    def __init__(self, query_results: list[dict[str, Any]]) -> None:
        self.query_results = query_results
        self.query_calls: list[dict[str, Any]] = []

    def query_items(
        self,
        query: str,
        parameters: list[dict[str, Any]],
        enable_cross_partition_query: bool,
    ) -> list[dict[str, Any]]:
        self.query_calls.append(
            {
                "query": query,
                "parameters": parameters,
                "enable_cross_partition_query": enable_cross_partition_query,
            }
        )
        return self.query_results


def build_case(case_id: str = "case-123") -> CaseDocument:
    now = datetime.now(timezone.utc)
    return CaseDocument(
        id=case_id,
        createdDate=now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
        summary="Patient is calling about medication refill.",
        processingStatus="Completed",
    )


def test_cosmos_repository_upserts_serialized_case_and_returns_original() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = FakeCosmosContainer()
    repository = CosmosCaseRepository(
        container=container,
        not_found_exceptions=(FakeNotFoundError,),
    )
    case = build_case()

    saved_case = asyncio.run(repository.save(case))

    assert container.upserted_items == [case.model_dump(mode="json")]
    assert container.upserted_items[0]["createdDate"] == case.createdDate
    assert saved_case is case


def test_cosmos_repository_supports_sync_container_upsert() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = SyncFakeCosmosContainer()
    repository = CosmosCaseRepository(container=container)
    case = build_case()

    saved_case = asyncio.run(repository.save(case))

    assert container.upserted_items == [case.model_dump(mode="json")]
    assert saved_case is case


def test_cosmos_repository_reads_case_by_id_and_created_date_partition_key() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = FakeCosmosContainer()
    case = build_case()
    container.read_result = case.model_dump(mode="json")
    repository = CosmosCaseRepository(
        container=container,
        not_found_exceptions=(FakeNotFoundError,),
    )

    asyncio.run(repository.get_by_id(case.id, created_date=case.createdDate))

    assert container.read_calls == [
        {"item": case.id, "partition_key": case.createdDate},
    ]


def test_cosmos_repository_supports_sync_container_read() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = SyncFakeCosmosContainer()
    case = build_case()
    container.read_result = case.model_dump(mode="json")
    repository = CosmosCaseRepository(container=container)

    retrieved_case = asyncio.run(
        repository.get_by_id(case.id, created_date=case.createdDate)
    )

    assert container.read_calls == [
        {"item": case.id, "partition_key": case.createdDate},
    ]
    assert retrieved_case == case


def test_cosmos_repository_returns_case_document_from_stored_dictionary() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = FakeCosmosContainer()
    case = build_case()
    container.read_result = case.model_dump(mode="json")
    repository = CosmosCaseRepository(
        container=container,
        not_found_exceptions=(FakeNotFoundError,),
    )

    retrieved_case = asyncio.run(
        repository.get_by_id(case.id, created_date=case.createdDate)
    )

    assert isinstance(retrieved_case, CaseDocument)
    assert retrieved_case == case


def test_cosmos_repository_requires_created_date_for_case_lookup() -> None:
    from src.app.services.cosmos_case_repository import (
        CosmosCaseRepository,
        MissingCasePartitionKeyError,
    )

    repository = CosmosCaseRepository(
        container=FakeCosmosContainer(),
        not_found_exceptions=(FakeNotFoundError,),
    )

    try:
        asyncio.run(repository.get_by_id("case-123"))
    except MissingCasePartitionKeyError as error:
        assert "created_date is required" in str(error)
        assert "/createdDate" in str(error)
    else:
        raise AssertionError(
            "Expected created_date requirement to raise "
            "MissingCasePartitionKeyError"
        )


def test_cosmos_repository_returns_none_when_case_is_missing() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = FakeCosmosContainer()
    container.read_error = FakeNotFoundError()
    repository = CosmosCaseRepository(
        container=container,
        not_found_exceptions=(FakeNotFoundError,),
    )

    retrieved_case = asyncio.run(
        repository.get_by_id("missing-case", created_date="2026-06-23")
    )

    assert retrieved_case is None


def test_cosmos_repository_idempotency_lookup_is_not_implemented() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    repository = CosmosCaseRepository(container=FakeCosmosContainer())

    try:
        asyncio.run(repository.get_by_idempotency_key("voicemail-key-123"))
    except NotImplementedError as error:
        assert "idempotencyKey" in str(error)
        assert "cross-partition" in str(error)
    else:
        raise AssertionError("Expected Cosmos idempotency lookup to be explicit")


def test_cosmos_repository_lists_cross_partition_cases_newest_first() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    newest = build_case("newest")
    oldest = build_case("oldest")
    container = FakeQueryCosmosContainer(
        [newest.model_dump(mode="json"), oldest.model_dump(mode="json")]
    )
    repository = CosmosCaseRepository(container=container)

    cases = asyncio.run(repository.list_cases())

    assert cases == [newest, oldest]
    assert len(container.query_calls) == 1
    query_call = container.query_calls[0]
    assert "ORDER BY c.createdUtc DESC" in query_call["query"]
    assert query_call["parameters"] == []
    assert query_call["enable_cross_partition_query"] is True


def test_cosmos_repository_parameterizes_supported_queue_filters() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = FakeQueryCosmosContainer([])
    repository = CosmosCaseRepository(container=container)

    cases = asyncio.run(
        repository.list_cases(review_status="PendingReview", urgency="Urgent")
    )

    assert cases == []
    query_call = container.query_calls[0]
    assert "c.reviewStatus = @reviewStatus" in query_call["query"]
    assert "c.urgency = @urgency" in query_call["query"]
    assert "PendingReview" not in query_call["query"]
    assert "Urgent" not in query_call["query"]
    assert query_call["parameters"] == [
        {"name": "@reviewStatus", "value": "PendingReview"},
        {"name": "@urgency", "value": "Urgent"},
    ]


def test_cosmos_repository_parameterizes_date_filters() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = FakeQueryCosmosContainer([])
    repository = CosmosCaseRepository(container=container)

    cases = asyncio.run(
        repository.list_cases(
            from_date=date(2026, 6, 24),
            to_date=date(2026, 6, 26),
        )
    )

    assert cases == []
    query_call = container.query_calls[0]
    assert "c.createdDate >= @fromDate" in query_call["query"]
    assert "c.createdDate <= @toDate" in query_call["query"]
    assert "ORDER BY c.createdUtc DESC" in query_call["query"]
    assert "2026-06-24" not in query_call["query"]
    assert "2026-06-26" not in query_call["query"]
    assert query_call["parameters"] == [
        {"name": "@fromDate", "value": "2026-06-24"},
        {"name": "@toDate", "value": "2026-06-26"},
    ]
    assert query_call["enable_cross_partition_query"] is True


def test_cosmos_repository_combines_supported_queue_and_date_filters() -> None:
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    container = FakeQueryCosmosContainer([])
    repository = CosmosCaseRepository(container=container)

    cases = asyncio.run(
        repository.list_cases(
            review_status="PendingReview",
            urgency="Urgent",
            from_date=date(2026, 6, 24),
            to_date=date(2026, 6, 26),
        )
    )

    assert cases == []
    query_call = container.query_calls[0]
    assert "c.reviewStatus = @reviewStatus" in query_call["query"]
    assert "c.urgency = @urgency" in query_call["query"]
    assert "c.createdDate >= @fromDate" in query_call["query"]
    assert "c.createdDate <= @toDate" in query_call["query"]
    assert query_call["parameters"] == [
        {"name": "@reviewStatus", "value": "PendingReview"},
        {"name": "@urgency", "value": "Urgent"},
        {"name": "@fromDate", "value": "2026-06-24"},
        {"name": "@toDate", "value": "2026-06-26"},
    ]


def test_cosmos_repository_rejects_filters_outside_initial_list_subset() -> None:
    from src.app.services.cosmos_case_repository import (
        CaseListNotSupportedError,
        CosmosCaseRepository,
    )

    container = FakeQueryCosmosContainer([])
    repository = CosmosCaseRepository(container=container)

    try:
        asyncio.run(repository.list_cases(source_system="local-demo"))
    except CaseListNotSupportedError as error:
        assert "source_system" in str(error)
    else:
        raise AssertionError("Expected unsupported Cosmos filters to be explicit")

    assert container.query_calls == []


def test_cosmos_repository_satisfies_case_repository_protocol() -> None:
    from src.app.services.case_repository import CaseRepository
    from src.app.services.cosmos_case_repository import CosmosCaseRepository

    repository = CosmosCaseRepository(
        container=FakeCosmosContainer(),
        not_found_exceptions=(FakeNotFoundError,),
    )

    assert isinstance(repository, CaseRepository)
