import asyncio
from datetime import datetime, timezone

from src.app.models.case import CaseDocument


def build_case() -> CaseDocument:
    now = datetime.now(timezone.utc)
    return CaseDocument(
        id="case-123",
        createdDate=now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
    )


def test_in_memory_repository_saves_case() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    case = build_case()

    asyncio.run(repository.save(case))

    assert asyncio.run(repository.get_by_id(case.id)) == case


def test_in_memory_repository_retrieves_saved_case_by_id() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    case = build_case()
    asyncio.run(repository.save(case))

    saved_case = asyncio.run(repository.get_by_id("case-123"))

    assert saved_case == case


def test_in_memory_repository_returns_none_for_missing_case_id() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()

    assert asyncio.run(repository.get_by_id("missing-case")) is None
