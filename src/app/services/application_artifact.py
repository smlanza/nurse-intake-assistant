from __future__ import annotations

import json
import os
from pathlib import Path
import re


ARTIFACT_MARKER_FILENAME = "application-artifact.json"
ARTIFACT_MARKER_PATH = Path(__file__).resolve().parents[1] / ARTIFACT_MARKER_FILENAME
UNPACKAGED_ARTIFACT = "unpackaged"
_DIGEST = re.compile(r"[0-9a-f]{64}")


def build_application_artifact_marker(digest: str) -> bytes:
    if _DIGEST.fullmatch(digest) is None:
        raise ValueError("Invalid application artifact digest.")
    return (
        json.dumps(
            {"artifactDigest": digest, "schemaVersion": 1},
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode()


def read_application_artifact_digest() -> str | None:
    try:
        payload = json.loads(ARTIFACT_MARKER_PATH.read_text())
    except FileNotFoundError:
        return None if os.getenv("WEBSITE_INSTANCE_ID") else UNPACKAGED_ARTIFACT
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or set(payload) != {"artifactDigest", "schemaVersion"}
        or payload.get("schemaVersion") != 1
    ):
        return None
    digest = payload.get("artifactDigest")
    return digest if isinstance(digest, str) and _DIGEST.fullmatch(digest) else None
