from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse


router = APIRouter(tags=["operations"])
ops_page_path = Path(__file__).resolve().parent.parent / "static" / "ops.html"


@router.get("/ops", response_class=HTMLResponse)
async def get_ops_page() -> HTMLResponse:
    return HTMLResponse(ops_page_path.read_text())
