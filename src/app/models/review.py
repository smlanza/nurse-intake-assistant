from pydantic import BaseModel


class CaseReviewRequest(BaseModel):
    reviewedBy: str
    reviewNotes: str | None = None
