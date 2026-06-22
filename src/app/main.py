from fastapi import FastAPI

from src.app.routes.health import router as health_router

app = FastAPI(title="Nurse Intake Assistant")

app.include_router(health_router)