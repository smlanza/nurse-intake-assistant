from typing import Any

from src.app.config.settings import AppSettings
from src.app.services.case_repository import CaseRepository, InMemoryCaseRepository
from src.app.services.cosmos_case_repository import CosmosCaseRepository


def create_case_repository(
    settings: AppSettings,
    cosmos_container: Any = None,
) -> CaseRepository:
    app_mode = settings.app_mode.strip().lower()

    if app_mode == "mock":
        return InMemoryCaseRepository()

    if app_mode == "cosmos":
        if cosmos_container is None:
            raise ValueError("A Cosmos container is required for cosmos APP_MODE")
        return CosmosCaseRepository(container=cosmos_container)

    raise ValueError(f"Unsupported APP_MODE: {settings.app_mode}")
