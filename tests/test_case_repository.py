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


def build_case_with_queue_fields(
    case_id: str,
    review_status: str = "PendingReview",
    urgency: str = "Routine",
) -> CaseDocument:
    now = datetime.now(timezone.utc)
    return CaseDocument(
        id=case_id,
        createdDate=now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
        reviewStatus=review_status,
        urgency=urgency,
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


def test_in_memory_repository_lists_saved_cases_in_save_order() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    first_case = build_case_with_queue_fields("case-1")
    second_case = build_case_with_queue_fields("case-2")
    asyncio.run(repository.save(first_case))
    asyncio.run(repository.save(second_case))

    cases = asyncio.run(repository.list_cases())

    assert [case.id for case in cases] == ["case-1", "case-2"]


def test_in_memory_repository_filters_listed_cases() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "routine-pending",
                review_status="PendingReview",
                urgency="Routine",
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "urgent-pending",
                review_status="PendingReview",
                urgency="Urgent",
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "urgent-reviewed",
                review_status="Reviewed",
                urgency="Urgent",
            )
        )
    )

    cases = asyncio.run(
        repository.list_cases(
            review_status="PendingReview",
            urgency="Urgent",
        )
    )

    assert [case.id for case in cases] == ["urgent-pending"]
