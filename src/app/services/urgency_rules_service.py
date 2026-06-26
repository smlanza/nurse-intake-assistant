import re
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
    """Apply deterministic red-flag rules alongside advisory AI urgency."""

    _hard_boundary_pattern = re.compile(r"[.!?;]")
    _contrast_pattern = re.compile(
        r"\b(?:but|however|though|although|yet|except)\b"
    )
    _negated_context_pattern = re.compile(
        r"(?:^|\b)(?:no|denies|denied|without|negative\s+for)\b"
        r"(?:[\s,:]+[\w']+){0,6}[\s,:]*$"
    )

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

                if self._has_non_negated_term_match(
                    normalized_text,
                    normalized_term,
                ):
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

    def _has_non_negated_term_match(
        self,
        normalized_text: str,
        normalized_term: str,
    ) -> bool:
        for match in re.finditer(re.escape(normalized_term), normalized_text):
            if not self._is_negated_match(normalized_text, match.start()):
                return True

        return False

    def _is_negated_match(self, normalized_text: str, match_start: int) -> bool:
        context = normalized_text[max(0, match_start - 80) : match_start]

        hard_boundary = self._last_match_end(self._hard_boundary_pattern, context)
        if hard_boundary is not None:
            context = context[hard_boundary:]

        contrast = self._last_match_end(self._contrast_pattern, context)
        if contrast is not None:
            context = context[contrast:]

        return bool(self._negated_context_pattern.search(context))

    @staticmethod
    def _last_match_end(pattern: re.Pattern[str], text: str) -> int | None:
        last_match = None
        for match in pattern.finditer(text):
            last_match = match

        if last_match is None:
            return None

        return last_match.end()
