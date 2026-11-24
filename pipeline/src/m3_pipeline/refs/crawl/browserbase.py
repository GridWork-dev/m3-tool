import re
from dataclasses import dataclass, field
from typing import Any

import httpx
from pydantic import BaseModel, Field

_API = "https://api.browserbase.com/v1/sessions"


def browserbase_session_payload(project_id: str, *, timeout_s: int = 900) -> dict[str, Any]:
    return {
        "projectId": project_id,
        "proxies": False,
        "timeout": timeout_s,
        "browserSettings": {
            "solveCaptchas": False,
            "advancedStealth": False,
            "verified": False,
        },
    }


@dataclass(frozen=True)
class BrowserbaseSession:
    id: str
    connect_url: str = field(repr=False)


class _SessionResponse(BaseModel):
    id: str
    connect_url: str = Field(alias="connectUrl", repr=False)


def create_session(http: httpx.Client, api_key: str, project_id: str) -> BrowserbaseSession:
    response = http.post(
        _API,
        headers={"X-BB-API-Key": api_key},
        json=browserbase_session_payload(project_id),
    )
    response.raise_for_status()
    session = _SessionResponse.model_validate_json(response.content)
    return BrowserbaseSession(session.id, session.connect_url)


def release_session(http: httpx.Client, api_key: str, project_id: str, session_id: str) -> None:
    response = http.post(
        f"{_API}/{session_id}",
        headers={"X-BB-API-Key": api_key},
        json={"projectId": project_id, "status": "REQUEST_RELEASE"},
    )
    response.raise_for_status()


def redact(text: str) -> str:
    return re.sub(r"(?i)(apiKey=)[^&\s\"'<>]+", r"\1***", text)
