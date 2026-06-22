from fastapi import FastAPI

from src.app.routes.health import router as health_router
from src.app.routes.intake import router as intake_router

app = FastAPI(title="Nurse Intake Assistant")

app.include_router(health_router)
app.include_router(intake_router)
