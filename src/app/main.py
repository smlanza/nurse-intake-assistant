from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.app.routes.cases import router as cases_router
from src.app.routes.demo import router as demo_router
from src.app.routes.health import router as health_router
from src.app.routes.intake import router as intake_router
from src.app.routes.notifications import router as notifications_router

app = FastAPI(title="Nurse Intake Assistant")

app.include_router(health_router)
app.include_router(intake_router)
app.include_router(cases_router)
app.include_router(notifications_router)
app.include_router(demo_router)

static_directory = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_directory), name="static")
