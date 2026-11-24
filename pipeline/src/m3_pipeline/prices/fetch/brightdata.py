import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from m3_pipeline.config import load_settings
from m3_pipeline.refs.crawl.blocked import is_blocked
from m3_pipeline.stages.lib.spend import SpendDenied, authorize

_authorize = authorize


class MissingCredentials(Exception):
    pass


def credential(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise MissingCredentials(f"missing variable: {name}")
    return value


@dataclass(frozen=True)
class UnlockResult:
    success: bool
    html: str = field(repr=False)
    status: int
    transferred_bytes: int = 0


def redact(text: str) -> str:
    text = re.sub(r'(?i)(apiKey=)[^&\s"\'<>]+', r"\1***", text)
    text = re.sub(r'(?i)(Bearer\s+)[^\s"\'<>]+', r"\1***", text)
    text = re.sub(r"(https?://)[^/@\s]+@", r"\1***@", text)
    for name, value in os.environ.items():
        if (
            value
            and name.startswith("M3_")
            and any(t in name for t in ("KEY", "TOKEN", "PROXY_URL"))
        ):
            text = text.replace(value, "***")
    return text


def authorize_fetch(service: str, url: str) -> None:
    # The existing guard accepts spike:<tag> rows only and requires a positive estimate.
    name = f"M3_PRICES_{service.upper()}_COST_USD"
    try:
        estimate = Decimal(os.environ.get(name, "0"))
    except InvalidOperation:
        raise SpendDenied(f"{name} must be a positive USD estimate") from None
    if not estimate.is_finite() or estimate <= 0:
        raise SpendDenied(f"{name} must be a positive USD estimate")
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    tag = f"prices-{service}-{date.today().isoformat()}-{digest}"
    _authorize(tag, estimate, ledger=load_settings().repo_root / "docs/spend-ledger.md")


def brightdata_unlock(http: httpx.Client, url: str, *, token: str) -> UnlockResult:
    zone = credential("M3_BRIGHTDATA_UNLOCKER_ZONE")
    authorize_fetch("brightdata", url)
    try:
        response = http.post(
            "https://api.brightdata.com/request",
            headers={"Authorization": f"Bearer {token}"},
            json={"zone": zone, "url": url, "format": "raw"},
            timeout=120,
        )
    except httpx.HTTPError:
        raise RuntimeError("Bright Data request failed") from None
    return UnlockResult(
        200 <= response.status_code < 300
        and not is_blocked(response.status_code, "", response.text[:4096]),
        response.text,
        response.status_code,
    )
