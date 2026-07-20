from fastapi import APIRouter, HTTPException

from src.app.services.application_artifact import read_application_artifact_digest

router = APIRouter()


@router.get("/health")
def health_check():
    return {"status": "ok", "service": "nurse-intake-assistant"}


@router.get("/version")
def version_check():
    artifact_digest = read_application_artifact_digest()
    if artifact_digest is None:
        raise HTTPException(
            status_code=503,
            detail="Application artifact marker unavailable.",
        )
    return {
        "service": "nurse-intake-assistant",
        "version": "0.1.0",
        "environment": "local",
        "artifactDigest": artifact_digest,
    }
