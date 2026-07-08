from pathlib import Path
from html import escape

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from src.app.dependencies import settings
from src.app.services.nurse_intake_agent_preflight import (
    build_agent_provider_status,
)


router = APIRouter(tags=["operations"])
ops_page_path = Path(__file__).resolve().parent.parent / "static" / "ops.html"
OPS_DYNAMIC_SECTION_MARKER = "      <section class=\"section-card\" aria-labelledby=\"safety-heading\">"


@router.get("/ops", response_class=HTMLResponse)
async def get_ops_page() -> HTMLResponse:
    html = ops_page_path.read_text()
    return HTMLResponse(_render_ops_page(html))


def _render_ops_page(html: str) -> str:
    agent_status = build_agent_provider_status(settings)
    dynamic_section = _foundry_agent_manual_validation_section(agent_status)
    if dynamic_section:
        return html.replace(
            OPS_DYNAMIC_SECTION_MARKER,
            f"{dynamic_section}\n\n{OPS_DYNAMIC_SECTION_MARKER}",
            1,
        )
    return html


def _foundry_agent_manual_validation_section(agent_status) -> str:
    if agent_status.manualValidationAvailable and agent_status.manualValidationCommand:
        missing_settings = ""
        if agent_status.missingSettings:
            safe_missing_settings = ", ".join(
                escape(setting, quote=True)
                for setting in agent_status.missingSettings
            )
            missing_settings = (
                "\n        <p class=\"muted\">Missing setting(s): "
                f"{safe_missing_settings}.</p>"
            )
        return (
            '      <section class="section-card" aria-labelledby="foundry-agent-manual-validation-heading">\n'
            '        <h2 id="foundry-agent-manual-validation-heading">Foundry Agent Manual Validation</h2>\n'
            '        <p class="muted">\n'
            "          Run this command manually from a configured developer shell to validate the Azure Foundry Agent path. "
            "This page only shows the command; it does not call Azure.\n"
            "        </p>\n"
            f"        <p><code>{escape(agent_status.manualValidationCommand, quote=True)}</code></p>"
            f"{missing_settings}\n"
            "      </section>"
        )

    if agent_status.warnings:
        safe_warnings = " ".join(
            escape(warning, quote=True)
            for warning in agent_status.warnings
        )
        return (
            '      <section class="section-card" aria-labelledby="agent-provider-readiness-heading">\n'
            '        <h2 id="agent-provider-readiness-heading">Agent Provider Readiness</h2>\n'
            f'        <p class="muted">{safe_warnings}</p>\n'
            "      </section>"
        )

    return ""
