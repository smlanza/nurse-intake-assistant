import asyncio
from datetime import date, datetime, timezone

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
    created_date: str | None = None,
) -> CaseDocument:
    now = datetime.now(timezone.utc)
    return CaseDocument(
        id=case_id,
        createdDate=created_date or now.date().isoformat(),
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


def test_in_memory_repository_filters_cases_from_date_inclusive() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("older", created_date="2026-06-23")
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("start", created_date="2026-06-24")
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("newer", created_date="2026-06-25")
        )
    )

    cases = asyncio.run(repository.list_cases(from_date=date(2026, 6, 24)))

    assert [case.id for case in cases] == ["start", "newer"]


def test_in_memory_repository_filters_cases_to_date_inclusive() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("older", created_date="2026-06-23")
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("end", created_date="2026-06-24")
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("newer", created_date="2026-06-25")
        )
    )

    cases = asyncio.run(repository.list_cases(to_date=date(2026, 6, 24)))

    assert [case.id for case in cases] == ["older", "end"]


def test_in_memory_repository_filters_cases_by_inclusive_date_range() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("older", created_date="2026-06-22")
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("start", created_date="2026-06-23")
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("end", created_date="2026-06-25")
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields("newer", created_date="2026-06-26")
        )
    )

    cases = asyncio.run(
        repository.list_cases(
            from_date=date(2026, 6, 23),
            to_date=date(2026, 6, 25),
        )
    )

    assert [case.id for case in cases] == ["start", "end"]


def test_in_memory_repository_combines_date_and_review_status_filters() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "pending-in-range",
                review_status="PendingReview",
                created_date="2026-06-24",
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "reviewed-in-range",
                review_status="Reviewed",
                created_date="2026-06-24",
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "pending-out-of-range",
                review_status="PendingReview",
                created_date="2026-06-26",
            )
        )
    )

    cases = asyncio.run(
        repository.list_cases(
            review_status="PendingReview",
            from_date=date(2026, 6, 23),
            to_date=date(2026, 6, 25),
        )
    )

    assert [case.id for case in cases] == ["pending-in-range"]


def test_in_memory_repository_combines_date_and_urgency_filters() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "urgent-in-range",
                urgency="Urgent",
                created_date="2026-06-24",
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "routine-in-range",
                urgency="Routine",
                created_date="2026-06-24",
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "urgent-out-of-range",
                urgency="Urgent",
                created_date="2026-06-26",
            )
        )
    )

    cases = asyncio.run(
        repository.list_cases(
            urgency="Urgent",
            from_date=date(2026, 6, 23),
            to_date=date(2026, 6, 25),
        )
    )

    assert [case.id for case in cases] == ["urgent-in-range"]
