from datetime import datetime

from src.app.models.case import CaseDocument


SAFETY_HEADER = (
    "DEMO ONLY - Not for production clinical use. AI-assisted output requires "
    "nurse review."
)


class NurseHandoffNoteFormatter:
    """Format saved cases into deterministic plain-text nurse handoff notes."""

    def format(self, case: CaseDocument) -> str:
        return "\n".join(
            [
                SAFETY_HEADER,
                "",
                "Case metadata",
                f"- Case ID: {_value_or_missing(case.id)}",
                f"- Created date: {_value_or_missing(case.createdDate)}",
                f"- Created time: {_format_datetime(case.createdUtc)}",
                f"- Source/channel: {_format_source(case)}",
                f"- Intake status: {_value_or_missing(case.intakeStatus)}",
                f"- Review status: {_value_or_missing(case.reviewStatus)}",
                "",
                "Patient summary",
                f"- Patient name: {_value_or_default(case.patient.name, 'Unknown')}",
                f"- Callback number: {_value_or_default(case.patient.callback_number, 'Missing')}",
                f"- Main concern: {_value_or_missing(case.reasonForCalling)}",
                f"- Summary: {_value_or_missing(case.summary)}",
                f"- Symptoms: {_format_list(case.symptoms)}",
                "- Duration/onset: Missing",
                "",
                "Urgency",
                f"- Urgency level: {_value_or_missing(case.urgency)}",
                f"- Urgency source: {_value_or_missing(case.urgencySource)}",
                f"- Red flags / rationale: {_value_or_default(case.urgencyRationale, 'None recorded')}",
                "",
                "Missing information / follow-up",
                f"- Missing required fields: {_format_list(case.missingFields)}",
                f"- Uncertain fields: {_format_list(case.uncertainFields)}",
                f"- Intake complete: {_format_bool(case.intakeComplete)}",
                f"- Intake completion status: {_value_or_missing(case.intakeStatus)}",
                "",
                "Notification status",
                f"- Email status: {_value_or_missing(case.notificationEmailStatus)}",
                f"- SMS status: {_value_or_missing(case.notificationSmsStatus)}",
                (
                    "- SMS delivery confirmed: "
                    f"{_format_bool(case.notificationSmsDeliveryConfirmed)}"
                ),
                "",
                "Nurse review",
                *_format_review_lines(case),
            ]
        )


def _format_review_lines(case: CaseDocument) -> list[str]:
    if case.reviewStatus != "Reviewed":
        return ["- Not yet reviewed"]

    return [
        f"- Reviewed by: {_value_or_default(case.reviewedBy, 'Unknown')}",
        f"- Reviewed at: {_format_datetime(case.reviewedAt)}",
        f"- Review notes: {_value_or_default(case.reviewNotes, 'None recorded')}",
    ]


def _format_source(case: CaseDocument) -> str:
    source_parts = [
        _clean(case.sourceSystem),
        _clean(case.caseType),
    ]
    values = [source_part for source_part in source_parts if source_part is not None]
    return " / ".join(values) if values else "Missing"


def _format_list(values: list[str]) -> str:
    cleaned_values = [_clean(value) for value in values]
    visible_values = [value for value in cleaned_values if value is not None]
    return ", ".join(visible_values) if visible_values else "None recorded"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "Missing"
    return value.isoformat()


def _format_bool(value: bool) -> str:
    return "true" if value else "false"


def _value_or_missing(value: object) -> str:
    return _value_or_default(value, "Missing")


def _value_or_default(value: object, default: str) -> str:
    cleaned_value = _clean(value)
    return cleaned_value if cleaned_value is not None else default


def _clean(value: object) -> str | None:
    if value is None:
        return None
    cleaned_value = str(value).strip()
    return cleaned_value or None
