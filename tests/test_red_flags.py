from pathlib import Path

import pytest

from src.app.services.urgency_rules_service import UrgencyRulesService


@pytest.fixture
def rules_service() -> UrgencyRulesService:
    config_path = (
        Path(__file__).parents[1] / "src" / "app" / "config" / "red_flags.yaml"
    )
    return UrgencyRulesService(config_path)


def test_returns_urgent_with_matching_rule_details(
    rules_service: UrgencyRulesService,
) -> None:
    result = rules_service.evaluate("I have CHEST PRESSURE that started this morning.")

    assert result.urgency == "Urgent"
    assert len(result.matched_red_flags) == 1
    assert result.matched_red_flags[0].rule_id == "chest_pain"
    assert result.matched_red_flags[0].label == "Chest pain"
    assert result.matched_red_flags[0].matched_term == "chest pressure"


def test_returns_all_matching_red_flags(rules_service: UrgencyRulesService) -> None:
    result = rules_service.evaluate(
        "The patient has slurred speech and says they cannot breathe."
    )

    assert result.urgency == "Urgent"
    assert [match.rule_id for match in result.matched_red_flags] == [
        "shortness_of_breath",
        "stroke_symptoms",
    ]
    assert [match.matched_term for match in result.matched_red_flags] == [
        "cannot breathe",
        "slurred speech",
    ]


@pytest.mark.parametrize("text", ["Calling to schedule a routine checkup.", "", None])
def test_returns_routine_when_no_rules_match(
    rules_service: UrgencyRulesService,
    text: str | None,
) -> None:
    result = rules_service.evaluate(text)

    assert result.urgency == "Routine"
    assert result.matched_red_flags == []


@pytest.mark.parametrize(
    "text",
    [
        "No chest pain.",
        "Patient denies shortness of breath.",
        "No severe bleeding.",
        "No stroke symptoms.",
    ],
)
def test_returns_routine_for_negated_red_flags(
    rules_service: UrgencyRulesService,
    text: str,
) -> None:
    result = rules_service.evaluate(text)

    assert result.urgency == "Routine"
    assert result.matched_red_flags == []


@pytest.mark.parametrize(
    "text,expected_rule_ids",
    [
        ("I have chest pain.", ["chest_pain"]),
        (
            "Chest pain and shortness of breath.",
            ["chest_pain", "shortness_of_breath"],
        ),
        (
            "No chest pain, but I am having trouble breathing.",
            ["shortness_of_breath"],
        ),
        (
            "Patient denies chest pain but reports severe bleeding.",
            ["severe_bleeding"],
        ),
    ],
)
def test_returns_urgent_for_non_negated_red_flags(
    rules_service: UrgencyRulesService,
    text: str,
    expected_rule_ids: list[str],
) -> None:
    result = rules_service.evaluate(text)

    assert result.urgency == "Urgent"
    assert [match.rule_id for match in result.matched_red_flags] == expected_rule_ids
