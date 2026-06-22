from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from src.app.models.case import CaseDocument
from src.app.services.case_processing_service import CaseProcessingService


router = APIRouter(prefix="/intake", tags=["intake"])
case_processing_service = CaseProcessingService()


class TextIntakeRequest(BaseModel):
    text: str
    sourceSystem: str | None = "local"
    sourceCallId: str | None = None

    @field_validator("text")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty")
        return value


@router.post("/text", response_model=CaseDocument)
async def create_text_intake(request: TextIntakeRequest) -> CaseDocument:
    case = await case_processing_service.process(request.text, "text-intake")
    case.sourceSystem = request.sourceSystem
    case.sourceCallId = request.sourceCallId
    return case
