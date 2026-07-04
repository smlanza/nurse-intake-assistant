from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "nurse-intake-assistant"}


@router.get("/version")
def version_check():
    return {
        "service": "nurse-intake-assistant",
        "version": "0.1.0",
        "environment": "local",
    }
