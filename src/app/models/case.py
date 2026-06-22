from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from src.app.models.ai_outputs import PatientInfo


ProcessingStatus = Literal[
    "Received",
    "Transcribing",
    "AiProcessing",
    "Completed",
    "RetryPending",
    "ProcessingFailed",
]

IntakeStatus = Literal["Complete", "NeedsFollowUp", "ProcessingFailed"]
ReviewStatus = Literal["New", "Reviewed"]
Urgency = Literal["Routine", "Urgent", "Unknown"]

CaseType = Literal["phone-intake", "text-intake", "audio-upload"]
UrgencySource = Literal["AI", "Rules", "RulesAndAI", "Unknown"]


class CaseDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    caseNumber: str | None = None

    createdDate: str
    createdUtc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lastStatusUpdatedUtc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    caseType: CaseType

    sourceSystem: str | None = None
    sourceCallId: str | None = None
    sourceRecordingId: str | None = None
    idempotencyKey: str | None = None

    patient: PatientInfo = Field(default_factory=PatientInfo)

    reasonForCalling: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    transcript: str | None = None
    summary: str | None = None

    urgency: Urgency = "Unknown"
    urgencySource: UrgencySource = "Unknown"
    ruleUrgency: Urgency = "Unknown"
    aiUrgency: Urgency = "Unknown"
    urgencyRationale: str | None = None

    missingFields: list[str] = Field(default_factory=list)
    uncertainFields: list[str] = Field(default_factory=list)

    processingStatus: ProcessingStatus = "Received"
    intakeStatus: IntakeStatus | None = None
    reviewStatus: ReviewStatus = "New"

    nurseReviewedUtc: datetime | None = None
    nurseReviewer: str | None = None
    nurseNotes: str | None = None

    notificationEmailSent: bool = False
    notificationSmsSent: bool = False

    audioBlobName: str | None = None
    audioDeleted: bool = False