from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from src.app.dependencies import (
    ai_service,
    case_repository,
    email_notification_sender,
    settings,
    sms_notification_sender,
)
from src.app.models.case import CaseDocument
from src.app.services.case_processing_service import CaseProcessingService


router = APIRouter(prefix="/intake", tags=["intake"])
TEXT_INTAKE_MIN_NON_WHITESPACE_CHARS = 10
case_processing_service = CaseProcessingService(
    ai_service=ai_service,
    case_repository=case_repository,
    email_notification_sender=email_notification_sender,
    sms_notification_sender=sms_notification_sender,
    suppress_notifications=settings.demo_suppress_notifications,
)


class TextIntakeRequest(BaseModel):
    text: str
    sourceSystem: str | None = "local"
    sourceCallId: str | None = None

    @field_validator("text")
    @classmethod
    def text_must_be_usable(cls, value: str) -> str:
        _validate_minimum_non_whitespace_text(value, "text")
        return value


class VoicemailTranscriptIntakeRequest(BaseModel):
    transcript: str
    sourceSystem: str | None = "voicemail-transcript"
    sourceCallId: str | None = None
    callerPhoneNumber: str | None = None
    sourceRecordingId: str | None = None
    audioBlobName: str | None = None
    idempotencyKey: str | None = None

    @field_validator("transcript")
    @classmethod
    def transcript_must_be_usable(cls, value: str) -> str:
        _validate_minimum_non_whitespace_text(value, "transcript")
        return value

    @field_validator(
        "sourceSystem",
        "sourceCallId",
        "callerPhoneNumber",
        "sourceRecordingId",
        "audioBlobName",
        "idempotencyKey",
    )
    @classmethod
    def optional_metadata_must_be_clean(cls, value: str | None) -> str | None:
        return _clean_optional_metadata(value)


@router.post("/text", response_model=CaseDocument)
async def create_text_intake(request: TextIntakeRequest) -> CaseDocument:
    case = await case_processing_service.process(request.text, "text-intake")
    case.sourceSystem = request.sourceSystem
    case.sourceCallId = request.sourceCallId
    await case_repository.save(case)
    return case


@router.post("/voicemail-transcript", response_model=CaseDocument)
async def create_voicemail_transcript_intake(
    request: VoicemailTranscriptIntakeRequest,
) -> CaseDocument:
    if request.idempotencyKey is not None:
        existing_case = await case_repository.get_by_idempotency_key(
            request.idempotencyKey
        )
        if existing_case is not None:
            return existing_case

    case = await case_processing_service.process(request.transcript, "phone-intake")
    case.sourceSystem = request.sourceSystem
    case.sourceCallId = request.sourceCallId
    case.sourceRecordingId = request.sourceRecordingId
    case.audioBlobName = request.audioBlobName
    case.idempotencyKey = request.idempotencyKey
    await case_repository.save(case)
    return case


def _clean_optional_metadata(value: str | None) -> str | None:
    if value is None:
        return None

    cleaned_value = value.strip()
    return cleaned_value or None


def _validate_minimum_non_whitespace_text(value: str, field_name: str) -> None:
    non_whitespace_count = sum(
        1 for character in value.strip() if not character.isspace()
    )
    if non_whitespace_count < TEXT_INTAKE_MIN_NON_WHITESPACE_CHARS:
        raise ValueError(
            f"{field_name} must contain at least 10 non-whitespace characters"
        )
