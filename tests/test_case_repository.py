import asyncio
from datetime import date, datetime, timezone

from src.app.models.case import CaseDocument, IntakeStatus


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
    created_utc: datetime | None = None,
    intake_status: IntakeStatus = "Complete",
    intake_complete: bool = True,
) -> CaseDocument:
    if created_utc is not None:
        now = created_utc
    elif created_date is not None:
        now = datetime.fromisoformat(f"{created_date}T00:00:00+00:00")
    else:
        now = datetime.now(timezone.utc)
    return CaseDocument(
        id=case_id,
        createdDate=created_date or now.date().isoformat(),
        createdUtc=now,
        lastStatusUpdatedUtc=now,
        caseType="text-intake",
        reviewStatus=review_status,
        urgency=urgency,
        intakeStatus=intake_status,
        intakeComplete=intake_complete,
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


def test_in_memory_repository_retrieves_case_by_idempotency_key() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    case = build_case()
    case.idempotencyKey = "voicemail-key-123"
    asyncio.run(repository.save(case))

    saved_case = asyncio.run(
        repository.get_by_idempotency_key("voicemail-key-123")
    )

    assert saved_case == case


def test_in_memory_repository_returns_none_for_missing_idempotency_key() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    case = build_case()
    case.idempotencyKey = "voicemail-key-123"
    asyncio.run(repository.save(case))

    assert asyncio.run(repository.get_by_idempotency_key("missing-key")) is None


def test_in_memory_repository_lists_saved_cases_newest_first() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    oldest_case = build_case_with_queue_fields(
        "oldest",
        created_utc=datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc),
    )
    newest_case = build_case_with_queue_fields(
        "newest",
        created_utc=datetime(2026, 6, 26, 11, 0, tzinfo=timezone.utc),
    )
    middle_case = build_case_with_queue_fields(
        "middle",
        created_utc=datetime(2026, 6, 26, 10, 0, tzinfo=timezone.utc),
    )
    asyncio.run(repository.save(oldest_case))
    asyncio.run(repository.save(newest_case))
    asyncio.run(repository.save(middle_case))

    cases = asyncio.run(repository.list_cases())

    assert [case.id for case in cases] == ["newest", "middle", "oldest"]


def test_in_memory_repository_uses_case_id_as_deterministic_order_tiebreaker() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    created_utc = datetime(2026, 6, 26, 9, 0, tzinfo=timezone.utc)
    first_case = build_case_with_queue_fields("case-b", created_utc=created_utc)
    second_case = build_case_with_queue_fields("case-a", created_utc=created_utc)
    asyncio.run(repository.save(first_case))
    asyncio.run(repository.save(second_case))

    cases = asyncio.run(repository.list_cases())

    assert [case.id for case in cases] == ["case-a", "case-b"]


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

    assert [case.id for case in cases] == ["newer", "start"]


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

    assert [case.id for case in cases] == ["end", "older"]


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

    assert [case.id for case in cases] == ["end", "start"]


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


def test_in_memory_repository_filters_cases_by_intake_status() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "complete",
                intake_status="Complete",
                intake_complete=True,
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "needs-follow-up",
                intake_status="NeedsFollowUp",
                intake_complete=False,
            )
        )
    )

    cases = asyncio.run(repository.list_cases(intake_status="NeedsFollowUp"))

    assert [case.id for case in cases] == ["needs-follow-up"]


def test_in_memory_repository_filters_cases_by_intake_complete() -> None:
    from src.app.services.case_repository import InMemoryCaseRepository

    repository = InMemoryCaseRepository()
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "complete",
                intake_status="Complete",
                intake_complete=True,
            )
        )
    )
    asyncio.run(
        repository.save(
            build_case_with_queue_fields(
                "needs-follow-up",
                intake_status="NeedsFollowUp",
                intake_complete=False,
            )
        )
    )

    cases = asyncio.run(repository.list_cases(intake_complete=False))

    assert [case.id for case in cases] == ["needs-follow-up"]
