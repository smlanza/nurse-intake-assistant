from typing import Any

from src.app.config.settings import AppSettings
from src.app.services.case_repository import CaseRepository, InMemoryCaseRepository
from src.app.services.cosmos_case_repository import CosmosCaseRepository
from src.app.services.cosmos_container_factory import create_cosmos_container


def create_case_repository(
    settings: AppSettings,
    cosmos_container: Any = None,
) -> CaseRepository:
    """Select the MVP repository implementation for the configured app mode."""

    app_mode = settings.app_mode.strip().lower()

    if app_mode == "mock":
        return InMemoryCaseRepository()

    if app_mode == "cosmos":
        if cosmos_container is None:
            cosmos_container = create_cosmos_container(settings)
        return CosmosCaseRepository(container=cosmos_container)

    raise ValueError(f"Unsupported APP_MODE: {settings.app_mode}")
