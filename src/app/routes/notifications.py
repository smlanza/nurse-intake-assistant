from dataclasses import asdict

from fastapi import APIRouter

from src.app.dependencies import email_notification_sender, sms_notification_sender


router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/email")
async def get_email_notifications() -> list[dict[str, str]]:
    return [
        asdict(notification)
        for notification in email_notification_sender.sent_notifications
    ]


@router.get("/sms")
async def get_sms_notifications() -> list[dict[str, str]]:
    return [
        asdict(notification)
        for notification in sms_notification_sender.sent_notifications
    ]
