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
        non_whitespace_count = sum(
            1 for character in value.strip() if not character.isspace()
        )
        if non_whitespace_count < TEXT_INTAKE_MIN_NON_WHITESPACE_CHARS:
            raise ValueError(
                "text must contain at least 10 non-whitespace characters"
            )
        return value


@router.post("/text", response_model=CaseDocument)
async def create_text_intake(request: TextIntakeRequest) -> CaseDocument:
    case = await case_processing_service.process(request.text, "text-intake")
    case.sourceSystem = request.sourceSystem
    case.sourceCallId = request.sourceCallId
    await case_repository.save(case)
    return case
