import importlib
import sys
from types import ModuleType
from typing import Any

import pytest

from src.app.services.case_repository import InMemoryCaseRepository


APP_SETUP_MODULES = (
    "src.app.main",
    "src.app.routes.intake",
    "src.app.routes.cases",
    "src.app.routes.notifications",
    "src.app.dependencies",
)


def test_fastapi_app_setup_creates_case_repository_through_factory_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.app.services.repository_factory as repository_factory

    calls: list[tuple[str, Any | None]] = []
    repository = InMemoryCaseRepository()

    def fake_create_case_repository(
        settings: Any,
        cosmos_container: Any | None = None,
    ) -> InMemoryCaseRepository:
        calls.append((settings.app_mode, cosmos_container))
        return repository

    original_factory = repository_factory.create_case_repository
    original_modules: dict[str, ModuleType | None] = {
        module_name: sys.modules.get(module_name)
        for module_name in APP_SETUP_MODULES
    }

    monkeypatch.setenv("APP_MODE", "mock")
    monkeypatch.setattr(
        repository_factory,
        "create_case_repository",
        fake_create_case_repository,
    )

    try:
        for module_name in APP_SETUP_MODULES:
            sys.modules.pop(module_name, None)

        main = importlib.import_module("src.app.main")
        dependencies = sys.modules["src.app.dependencies"]

        assert calls == [("mock", None)]
        assert dependencies.case_repository is repository
        assert main.app is not None
    finally:
        repository_factory.create_case_repository = original_factory
        for module_name in reversed(APP_SETUP_MODULES):
            original_module = original_modules[module_name]
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module
