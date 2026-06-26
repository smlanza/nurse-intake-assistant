from pydantic import BaseModel, field_validator


class CaseReviewRequest(BaseModel):
    reviewedBy: str
    reviewNotes: str | None = None

    @field_validator("reviewedBy")
    @classmethod
    def reviewed_by_must_not_be_blank(cls, value: str) -> str:
        reviewer = value.strip()
        if not reviewer:
            raise ValueError("reviewedBy is required.")
        return reviewer

    @field_validator("reviewNotes")
    @classmethod
    def blank_review_notes_become_none(cls, value: str | None) -> str | None:
        if value is None:
            return None

        notes = value.strip()
        return notes or None
