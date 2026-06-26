import re

from src.app.models.ai_outputs import (
    ExtractionSummaryResult,
    PatientInfo,
    UrgencyClassificationResult,
)


class MockAiService:
    """Provide deterministic local behavior in place of a future Azure AI/LLM."""

    _REQUIRED_FIELD_VALUES: tuple[tuple[str, str], ...] = (
        ("patient.name", "name"),
        ("patient.date_of_birth", "date_of_birth"),
        ("patient.callback_number", "callback_number"),
    )

    _SYMPTOM_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("chest pain", ("chest pain", "chest pressure", "tightness in chest")),
        (
            "shortness of breath",
            (
                "shortness of breath",
                "trouble breathing",
                "can't breathe",
                "cannot breathe",
            ),
        ),
        ("slurred speech", ("slurred speech",)),
        ("arm weakness", ("arm weakness",)),
        ("severe bleeding", ("severe bleeding", "bleeding won't stop")),
        ("fever", ("fever", "feverish")),
        ("cough", ("cough", "coughing")),
        ("headache", ("headache",)),
        ("nausea", ("nausea", "nauseous")),
        ("vomiting", ("vomiting", "throwing up")),
        ("dizziness", ("dizziness", "dizzy")),
        ("rash", ("rash",)),
    )

    _URGENT_TERMS: tuple[str, ...] = (
        "chest pain",
        "chest pressure",
        "tightness in chest",
        "shortness of breath",
        "trouble breathing",
        "can't breathe",
        "cannot breathe",
        "face drooping",
        "slurred speech",
        "arm weakness",
        "sudden confusion",
        "severe bleeding",
        "bleeding won't stop",
        "bleeding will not stop",
    )

    _ADVISORY_DISCLAIMER = (
        "Advisory urgency only; nurse review and clinical judgment are required."
    )

    async def extract_and_summarize(self, raw_text: str) -> ExtractionSummaryResult:
        text = raw_text.strip()
        patient = PatientInfo(
            name=self._extract_name(text),
            date_of_birth=self._extract_date_of_birth(text),
            callback_number=self._extract_callback_number(text),
        )
        symptoms = self._extract_symptoms(text)
        reason = self._extract_reason(text, symptoms)
        missing_fields = self._missing_required_fields(patient, reason)

        if symptoms:
            summary = f"Patient reports {', '.join(symptoms)}."
        elif reason:
            summary = f"Patient is calling about {reason}."
        else:
            summary = "No reason for calling or symptoms were provided."

        return ExtractionSummaryResult(
            patient=patient,
            reason_for_calling=reason,
            symptoms=symptoms,
            summary=summary,
            missing_fields=missing_fields,
            uncertain_fields=[],
            extraction_notes=(
                "Deterministic mock extraction for local development; no AI service "
                "was called."
            ),
        )

    async def classify_urgency(self, raw_text: str) -> UrgencyClassificationResult:
        normalized_text = raw_text.casefold()
        matched_term = next(
            (term for term in self._URGENT_TERMS if term in normalized_text),
            None,
        )

        if matched_term is not None:
            return UrgencyClassificationResult(
                urgency="Urgent",
                urgency_rationale=(
                    f'Deterministic mock urgency keyword matched: "{matched_term}".'
                ),
                advisory_disclaimer=self._ADVISORY_DISCLAIMER,
            )

        return UrgencyClassificationResult(
            urgency="Routine",
            urgency_rationale="No urgent mock keywords were detected.",
            advisory_disclaimer=self._ADVISORY_DISCLAIMER,
        )

    @classmethod
    def _extract_symptoms(cls, text: str) -> list[str]:
        normalized_text = text.casefold()
        return [
            symptom
            for symptom, terms in cls._SYMPTOM_TERMS
            if any(term in normalized_text for term in terms)
        ]

    @staticmethod
    def _extract_name(text: str) -> str | None:
        match = re.search(
            r"\b(?:my name is|name\s*:)\s*"
            r"([a-z][a-z' -]*?)"
            r"(?=\s+(?:and|dob|date of birth|callback|phone)\b|[,.\n]|$)",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip().title() if match else None

    @staticmethod
    def _extract_date_of_birth(text: str) -> str | None:
        match = re.search(
            r"\b(?:date of birth|dob)\s*(?::|is)?\s*"
            r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1) if match else None

    @staticmethod
    def _extract_callback_number(text: str) -> str | None:
        match = re.search(
            r"\b(?:callback(?: number)?|phone(?: number)?|reach me at)"
            r"\s*(?::|is)?\s*([+]?[\d(). -]{7,}\d)",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(1).strip() if match else None

    @staticmethod
    def _extract_reason(text: str, symptoms: list[str]) -> str | None:
        if symptoms:
            return symptoms[0]

        normalized_text = text.casefold()
        reason_phrases = (
            ("medication refill", "medication refill"),
            ("refill", "medication refill"),
            ("routine checkup", "routine checkup"),
            ("annual checkup", "annual checkup"),
            ("appointment", "appointment"),
        )
        for phrase, reason in reason_phrases:
            if phrase in normalized_text:
                return reason

        return None

    @classmethod
    def _missing_required_fields(
        cls,
        patient: PatientInfo,
        reason_for_calling: str | None,
    ) -> list[str]:
        patient_values = patient.model_dump()
        missing_fields = [
            field_path
            for field_path, patient_key in cls._REQUIRED_FIELD_VALUES
            if patient_values[patient_key] is None
        ]

        if reason_for_calling is None:
            missing_fields.append("reason_for_calling")

        return missing_fields
