from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from src.app.dependencies import (
    case_repository,
    email_notification_sender,
    settings,
    sms_notification_sender,
)


router = APIRouter(prefix="/demo", tags=["demo"])
demo_page_path = Path(__file__).resolve().parent.parent / "static" / "demo.html"


class DemoResetCleared(BaseModel):
    cases: bool
    emailNotifications: bool
    smsNotifications: bool


class DemoResetResponse(BaseModel):
    reset: bool
    cleared: DemoResetCleared


@router.get("", response_class=FileResponse)
async def get_demo_page() -> FileResponse:
    return FileResponse(demo_page_path, media_type="text/html")


@router.post("/reset", response_model=DemoResetResponse)
async def reset_demo_state() -> DemoResetResponse:
    if settings.app_mode.strip().lower() != "mock":
        raise HTTPException(
            status_code=400,
            detail="Demo reset is only available in mock mode.",
        )

    _clear(case_repository, "case repository")
    _clear(email_notification_sender, "email notification sender")
    _clear(sms_notification_sender, "SMS notification sender")

    return DemoResetResponse(
        reset=True,
        cleared=DemoResetCleared(
            cases=True,
            emailNotifications=True,
            smsNotifications=True,
        ),
    )


def _clear(target: Any, name: str) -> None:
    clear = getattr(target, "clear", None)
    if not callable(clear):
        raise HTTPException(
            status_code=500,
            detail=f"Mock {name} does not support demo reset.",
        )
    clear()
