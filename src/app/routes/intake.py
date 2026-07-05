from typing import Annotated

from fastapi import APIRouter, Body
from pydantic import BaseModel, field_validator

from src.app.dependencies import (
    ai_service,
    case_repository,
    email_notification_sender,
    nurse_intake_agent,
    settings,
    sms_notification_sender,
)
from src.app.models.case import CaseDocument
from src.app.services.case_processing_service import CaseProcessingService


router = APIRouter(prefix="/intake", tags=["intake"])
TEXT_INTAKE_MIN_NON_WHITESPACE_CHARS = 10
TEXT_INTAKE_OPENAPI_EXAMPLES = {
    "complete_routine_text_intake": {
        "summary": "Complete routine text intake",
        "description": (
            "Demo-safe routine text intake with required patient fields and a "
            "non-urgent reason for calling."
        ),
        "value": {
            "text": (
                "My name is Jane Doe. DOB: 1980-04-15. "
                "My callback number is +1 (555) 555-0123. "
                "I need a medication refill."
            ),
            "sourceSystem": "local-demo",
            "sourceCallId": "text-demo-001",
        },
    },
    "urgent_text_intake": {
        "summary": "Urgent text intake",
        "description": (
            "Demo-safe text intake that includes a red-flag symptom for urgency "
            "rule evaluation."
        ),
        "value": {
            "text": (
                "My name is Jordan Smith. DOB: 1970-09-09. "
                "My callback number is +1 (555) 555-0134. "
                "I have chest pain and shortness of breath."
            ),
            "sourceSystem": "local-demo",
            "sourceCallId": "text-demo-urgent-001",
        },
    },
    "incomplete_text_intake": {
        "summary": "Incomplete text intake",
        "description": (
            "Demo-safe text intake missing patient identifiers so the case needs "
            "nurse follow-up."
        ),
        "value": {
            "text": "I have a cough and fever.",
            "sourceSystem": "local-demo",
            "sourceCallId": "text-demo-incomplete-001",
        },
    },
}
VOICEMAIL_TRANSCRIPT_OPENAPI_EXAMPLES = {
    "complete_routine_voicemail_transcript": {
        "summary": "Complete routine voicemail transcript",
        "description": (
            "Already-transcribed voicemail with idempotency and recording "
            "metadata for a routine demo case."
        ),
        "value": {
            "transcript": (
                "My name is Alex Lee. DOB: 1975-03-20. "
                "My callback number is +1 (555) 555-0199. "
                "I need a medication refill."
            ),
            "sourceSystem": "voicemail-transcript",
            "sourceCallId": "call-demo-001",
            "callerPhoneNumber": "+1 (555) 555-0199",
            "sourceRecordingId": "recording-demo-001",
            "audioBlobName": "demo/recording-demo-001.wav",
            "idempotencyKey": "voicemail-demo-001",
        },
    },
    "urgent_voicemail_transcript": {
        "summary": "Urgent voicemail transcript",
        "description": (
            "Already-transcribed voicemail with a red-flag symptom and an "
            "idempotency key."
        ),
        "value": {
            "transcript": (
                "My name is Casey Morgan. DOB: 1965-11-11. "
                "My callback number is +1 (555) 555-0188. "
                "I have chest pain and trouble breathing."
            ),
            "sourceSystem": "voicemail-transcript",
            "sourceCallId": "call-demo-urgent-001",
            "callerPhoneNumber": "+1 (555) 555-0188",
            "sourceRecordingId": "recording-demo-urgent-001",
            "audioBlobName": "demo/recording-demo-urgent-001.wav",
            "idempotencyKey": "voicemail-demo-urgent-001",
        },
    },
    "incomplete_voicemail_transcript": {
        "summary": "Incomplete voicemail transcript",
        "description": (
            "Already-transcribed voicemail missing patient identifiers so the "
            "case needs nurse follow-up."
        ),
        "value": {
            "transcript": "I have a cough and fever.",
            "sourceSystem": "voicemail-transcript",
            "sourceCallId": "call-demo-incomplete-001",
            "sourceRecordingId": "recording-demo-incomplete-001",
            "audioBlobName": "demo/recording-demo-incomplete-001.wav",
            "idempotencyKey": "voicemail-demo-incomplete-001",
        },
    },
    "idempotent_repeat_voicemail_transcript": {
        "summary": "Repeated idempotent voicemail submission",
        "description": (
            "Submit this same payload again to return the existing case instead "
            "of creating duplicate cases or mock notifications."
        ),
        "value": {
            "transcript": (
                "My name is Alex Lee. DOB: 1975-03-20. "
                "My callback number is +1 (555) 555-0199. "
                "I need a medication refill."
            ),
            "sourceSystem": "voicemail-transcript",
            "sourceCallId": "call-demo-001",
            "callerPhoneNumber": "+1 (555) 555-0199",
            "sourceRecordingId": "recording-demo-001",
            "audioBlobName": "demo/recording-demo-001.wav",
            "idempotencyKey": "voicemail-demo-001",
        },
    },
}
case_processing_service = CaseProcessingService(
    ai_service=ai_service,
    case_repository=case_repository,
    email_notification_sender=email_notification_sender,
    sms_notification_sender=sms_notification_sender,
    nurse_intake_agent=nurse_intake_agent,
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
async def create_text_intake(
    request: Annotated[
        TextIntakeRequest,
        Body(openapi_examples=TEXT_INTAKE_OPENAPI_EXAMPLES),
    ],
) -> CaseDocument:
    case = await case_processing_service.process(request.text, "text-intake")
    case.sourceSystem = request.sourceSystem
    case.sourceCallId = request.sourceCallId
    await case_repository.save(case)
    return case


@router.post("/voicemail-transcript", response_model=CaseDocument)
async def create_voicemail_transcript_intake(
    request: Annotated[
        VoicemailTranscriptIntakeRequest,
        Body(openapi_examples=VOICEMAIL_TRANSCRIPT_OPENAPI_EXAMPLES),
    ],
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
