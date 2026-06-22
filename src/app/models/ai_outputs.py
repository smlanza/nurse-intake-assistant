from pydantic import BaseModel, Field
from typing import Literal

class PatientInfo(BaseModel):
    name: str | None = None
    date_of_birth: str | None = None
    callback_number: str | None = None

class ExtractionSummaryResult(BaseModel):
    patient: PatientInfo
    reason_for_calling: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    summary: str
    missing_fields: list[str] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)
    extraction_notes: str | None = None

class UrgencyClassificationResult(BaseModel):
    urgency: Literal["Routine", "Urgent"]
    urgency_rationale: str
    advisory_disclaimer: str