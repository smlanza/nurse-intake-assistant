from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, Field, StringConstraints


NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
RuleUrgency = Literal["Routine", "Urgent"]


class RedFlagRule(BaseModel):
    id: NonEmptyString
    label: NonEmptyString
    terms: list[NonEmptyString] = Field(min_length=1)
    urgency: Literal["Urgent"]


class RedFlagConfig(BaseModel):
    red_flags: list[RedFlagRule] = Field(default_factory=list)


class MatchedRedFlag(BaseModel):
    rule_id: str
    label: str
    matched_term: str


class RuleEvaluationResult(BaseModel):
    urgency: RuleUrgency
    matched_red_flags: list[MatchedRedFlag] = Field(default_factory=list)


class UrgencyRulesService:
    def __init__(self, config_path: str | Path):
        self.config_path = Path(config_path)
        self.config = self._load_config()

    def _load_config(self) -> RedFlagConfig:
        if not self.config_path.exists():
            raise FileNotFoundError(f"Red flag config not found: {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as file:
            raw_config = yaml.safe_load(file) or {}

        return RedFlagConfig.model_validate(raw_config)

    def evaluate(self, text: str | None) -> RuleEvaluationResult:
        normalized_text = (text or "").casefold()
        matches: list[MatchedRedFlag] = []

        for rule in self.config.red_flags:
            for term in rule.terms:
                normalized_term = term.casefold()

                if normalized_term in normalized_text:
                    matches.append(
                        MatchedRedFlag(
                            rule_id=rule.id,
                            label=rule.label,
                            matched_term=term,
                        )
                    )

        if matches:
            return RuleEvaluationResult(
                urgency="Urgent",
                matched_red_flags=matches,
            )

        return RuleEvaluationResult(
            urgency="Routine",
            matched_red_flags=[],
        )
