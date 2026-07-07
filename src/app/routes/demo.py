from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.app.dependencies import (
    case_repository,
    email_notification_sender,
    settings,
    sms_notification_sender,
)
from src.app.models.ai_outputs import PatientInfo
from src.app.models.case import CaseDocument
from src.app.services.nurse_intake_agent_preflight import (
    NurseIntakeAgentStatus,
    build_nurse_intake_agent_status,
)


router = APIRouter(prefix="/demo", tags=["demo"])
demo_page_path = Path(__file__).resolve().parent.parent / "static" / "demo.html"
DEMO_SEED_CASE_IDS = [
    "demo-seed-urgent-text",
    "demo-seed-routine-voicemail",
    "demo-seed-reviewed-text",
    "demo-seed-follow-up-voicemail",
]


class DemoResetCleared(BaseModel):
    cases: bool
    emailNotifications: bool
    smsNotifications: bool


class DemoResetResponse(BaseModel):
    reset: bool
    cleared: DemoResetCleared


class DemoSeedResponse(BaseModel):
    success: bool
    seededCaseCount: int
    caseIds: list[str]


class DemoStatusResponse(BaseModel):
    demoModeReady: bool
    appMode: str
    aiProvider: str
    speechProvider: str
    emailProvider: str
    smsProvider: str
    agentProvider: str
    agentStatus: NurseIntakeAgentStatus
    notificationsSuppressed: bool
    safeForLocalDemo: bool
    safetyBoundary: str
    warnings: list[str]


@router.get("", response_class=HTMLResponse)
async def get_demo_page() -> HTMLResponse:
    html = demo_page_path.read_text()
    replacements = {
        "{{ APP_MODE }}": settings.app_mode,
        "{{ AI_PROVIDER }}": settings.ai_provider,
        "{{ SPEECH_PROVIDER }}": settings.speech_provider,
        "{{ EMAIL_PROVIDER }}": settings.email_provider,
        "{{ SMS_PROVIDER }}": settings.sms_provider,
    }
    for placeholder, value in replacements.items():
        html = html.replace(placeholder, escape(value, quote=True))
    return HTMLResponse(html)


@router.get("/status", response_model=DemoStatusResponse)
async def get_demo_status() -> DemoStatusResponse:
    return _build_demo_status()


@router.post("/seed", response_model=DemoSeedResponse)
async def seed_demo_state() -> DemoSeedResponse:
    if settings.app_mode.strip().lower() != "mock":
        raise HTTPException(
            status_code=400,
            detail="Demo seed data is only available in mock mode.",
        )

    save = getattr(case_repository, "save", None)
    if not callable(save):
        raise HTTPException(
            status_code=500,
            detail="Mock case repository does not support demo seed data.",
        )

    for case in _build_demo_seed_cases():
        await save(case)

    return DemoSeedResponse(
        success=True,
        seededCaseCount=len(DEMO_SEED_CASE_IDS),
        caseIds=DEMO_SEED_CASE_IDS,
    )


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


def _build_demo_status() -> DemoStatusResponse:
    app_mode = _status_value(settings.app_mode)
    ai_provider = _status_value(settings.ai_provider)
    speech_provider = _status_value(settings.speech_provider)
    email_provider = _status_value(settings.email_provider)
    sms_provider = _status_value(settings.sms_provider)
    agent_provider = _status_value(settings.agent_provider)
    agent_status = build_nurse_intake_agent_status(settings)

    warnings = _demo_status_warnings(
        app_mode=app_mode,
        ai_provider=ai_provider,
        speech_provider=speech_provider,
        email_provider=email_provider,
        sms_provider=sms_provider,
        agent_provider=agent_provider,
    )

    return DemoStatusResponse(
        demoModeReady=not warnings,
        appMode=app_mode,
        aiProvider=ai_provider,
        speechProvider=speech_provider,
        emailProvider=email_provider,
        smsProvider=sms_provider,
        agentProvider=agent_provider,
        agentStatus=agent_status,
        notificationsSuppressed=settings.demo_suppress_notifications,
        safeForLocalDemo=True,
        safetyBoundary=(
            "Local mock/demo only. Not for production clinical use. "
            "AI output requires human nurse review."
        ),
        warnings=warnings,
    )


def _status_value(value: str) -> str:
    return value.strip().lower() or "mock"


def _demo_status_warnings(
    *,
    app_mode: str,
    ai_provider: str,
    speech_provider: str,
    email_provider: str,
    sms_provider: str,
    agent_provider: str,
) -> list[str]:
    warnings: list[str] = []
    if app_mode != "mock":
        warnings.append(
            "APP_MODE is not mock; repository behavior must be validated separately."
        )
    if ai_provider != "mock":
        warnings.append(
            "AI_PROVIDER is not mock; live AI integration should not be claimed "
            "unless manually verified."
        )
    if speech_provider != "mock":
        warnings.append(
            "SPEECH_PROVIDER is not mock; live speech behavior must be validated separately."
        )
    if email_provider != "mock":
        warnings.append(
            "EMAIL_PROVIDER is not mock; real email behavior must be validated separately."
        )
    if sms_provider != "mock":
        warnings.append(
            "SMS_PROVIDER is not mock; real SMS behavior must be validated separately."
        )
    if agent_provider in {"foundry", "foundry-agent"}:
        warnings.append(
            f"AGENT_PROVIDER is {agent_provider}; Foundry Agent intake routing "
            "uses the NurseIntakeAgent boundary, but live Azure AI Agent "
            "behavior should not be claimed unless manually verified."
        )
    elif agent_provider != "mock":
        warnings.append(
            "AGENT_PROVIDER is not mock; unsupported agent providers must not be "
            "claimed for local demo readiness."
        )
    return warnings


def _clear(target: Any, name: str) -> None:
    clear = getattr(target, "clear", None)
    if not callable(clear):
        raise HTTPException(
            status_code=500,
            detail=f"Mock {name} does not support demo reset.",
        )
    clear()


def _build_demo_seed_cases() -> list[CaseDocument]:
    created_at = datetime(2026, 6, 28, 14, 0, 0, tzinfo=timezone.utc)
    reviewed_at = datetime(2026, 6, 28, 14, 18, 0, tzinfo=timezone.utc)

    return [
        CaseDocument(
            id="demo-seed-urgent-text",
            caseNumber="DEMO-001",
            createdDate="2026-06-28",
            createdUtc=created_at,
            lastStatusUpdatedUtc=created_at,
            caseType="text-intake",
            sourceSystem="demo-seed",
            idempotencyKey="demo-seed-urgent-text",
            patient=PatientInfo(
                name="Demo Patient A",
                date_of_birth="1980-04-15",
                callback_number="demo-callback-001",
            ),
            reasonForCalling="Chest tightness and shortness of breath",
            symptoms=["chest tightness", "shortness of breath"],
            transcript=(
                "Demo Patient A reports chest tightness and shortness of breath "
                "and requests a nurse callback."
            ),
            summary=(
                "Demo patient reports chest tightness and shortness of breath; "
                "nurse review is pending."
            ),
            urgency="Urgent",
            urgencySource="RulesAndAI",
            ruleUrgency="Urgent",
            aiUrgency="Urgent",
            urgencyRationale="Demo urgent symptoms matched local red-flag rules.",
            intakeComplete=True,
            processingStatus="Completed",
            intakeStatus="Complete",
            reviewStatus="PendingReview",
            notificationEmailSent=True,
            notificationEmailStatus="MockRecorded",
            notificationSmsSent=True,
            notificationSmsStatus="MockRecorded",
        ),
        CaseDocument(
            id="demo-seed-routine-voicemail",
            caseNumber="DEMO-002",
            createdDate="2026-06-28",
            createdUtc=created_at.replace(hour=13, minute=45),
            lastStatusUpdatedUtc=created_at.replace(hour=13, minute=45),
            caseType="phone-intake",
            sourceSystem="voicemail-transcript",
            sourceCallId="demo-call-002",
            sourceRecordingId="demo-recording-002",
            idempotencyKey="demo-seed-routine-voicemail",
            patient=PatientInfo(
                name="Demo Patient B",
                date_of_birth="1975-03-20",
                callback_number="demo-callback-002",
            ),
            reasonForCalling="Medication refill question",
            symptoms=[],
            transcript=(
                "Demo Patient B left a voicemail asking about a medication refill "
                "and routine callback."
            ),
            summary="Demo voicemail asks about a routine medication refill question.",
            urgency="Routine",
            urgencySource="RulesAndAI",
            ruleUrgency="Routine",
            aiUrgency="Routine",
            urgencyRationale="No urgent demo symptoms were present.",
            intakeComplete=True,
            processingStatus="Completed",
            intakeStatus="Complete",
            reviewStatus="PendingReview",
            audioBlobName="demo/seed-routine-voicemail.wav",
            notificationEmailStatus="NotAttempted",
            notificationSmsStatus="NotAttempted",
        ),
        CaseDocument(
            id="demo-seed-reviewed-text",
            caseNumber="DEMO-003",
            createdDate="2026-06-28",
            createdUtc=created_at.replace(hour=13, minute=30),
            lastStatusUpdatedUtc=reviewed_at,
            caseType="text-intake",
            sourceSystem="demo-seed",
            idempotencyKey="demo-seed-reviewed-text",
            patient=PatientInfo(
                name="Demo Patient C",
                date_of_birth="1992-11-02",
                callback_number="demo-callback-003",
            ),
            reasonForCalling="Follow-up about lab results",
            symptoms=["mild fatigue"],
            transcript=(
                "Demo Patient C asks about lab results and mentions mild fatigue."
            ),
            summary="Demo text intake about lab results has already been reviewed.",
            urgency="Routine",
            urgencySource="RulesAndAI",
            ruleUrgency="Routine",
            aiUrgency="Routine",
            urgencyRationale="Routine follow-up request in demo seed data.",
            intakeComplete=True,
            processingStatus="Completed",
            intakeStatus="Complete",
            reviewStatus="Reviewed",
            reviewedBy="Demo Nurse",
            reviewNotes="Reviewed during seeded demo setup.",
            reviewedAt=reviewed_at,
            notificationEmailStatus="Suppressed",
            notificationSmsStatus="Suppressed",
        ),
        CaseDocument(
            id="demo-seed-follow-up-voicemail",
            caseNumber="DEMO-004",
            createdDate="2026-06-28",
            createdUtc=created_at.replace(hour=13, minute=15),
            lastStatusUpdatedUtc=created_at.replace(hour=13, minute=15),
            caseType="phone-intake",
            sourceSystem="voicemail-transcript",
            sourceCallId="demo-call-004",
            sourceRecordingId="demo-recording-004",
            idempotencyKey="demo-seed-follow-up-voicemail",
            patient=PatientInfo(
                name=None,
                date_of_birth=None,
                callback_number="demo-callback-004",
            ),
            reasonForCalling="Caller reports dizziness but did not leave a name",
            symptoms=["dizziness"],
            transcript=(
                "Caller reports dizziness and asks for help but does not provide "
                "a full name or date of birth."
            ),
            summary=(
                "Demo voicemail needs follow-up because identifying patient "
                "details are incomplete."
            ),
            urgency="Urgent",
            urgencySource="RulesAndAI",
            ruleUrgency="Urgent",
            aiUrgency="Urgent",
            urgencyRationale="Dizziness is treated as urgent in demo seed data.",
            missingFields=["patient.name", "patient.date_of_birth"],
            intakeComplete=False,
            processingStatus="Completed",
            intakeStatus="NeedsFollowUp",
            reviewStatus="PendingReview",
            audioBlobName="demo/seed-follow-up-voicemail.wav",
            notificationEmailStatus="Failed",
            notificationSmsStatus="Failed",
        ),
    ]
