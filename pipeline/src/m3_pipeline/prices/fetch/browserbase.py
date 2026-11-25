from typing import Any

import httpx
from pydantic import BaseModel, Field

from m3_pipeline.prices.fetch.brightdata import UnlockResult, authorize_fetch, credential
from m3_pipeline.refs.crawl.blocked import is_blocked


def prices_session_payload(project_id: str, *, timeout_s: int = 900) -> dict[str, Any]:
    return {
        "projectId": project_id,
        "proxies": False,
        "timeout": timeout_s,
        "browserSettings": {"solveCaptchas": True, "advancedStealth": True, "verified": False},
    }


class _Session(BaseModel):
    id: str
    connect_url: str = Field(alias="connectUrl", repr=False)


def browserbase_unlock(http: httpx.Client, url: str) -> UnlockResult:
    from playwright.sync_api import sync_playwright

    key = credential("M3_BROWSERBASE_API_KEY")
    project = credential("M3_BROWSERBASE_PROJECT_ID")
    authorize_fetch("browserbase", url)
    endpoint = "https://api.browserbase.com/v1/sessions"
    headers = {"X-BB-API-Key": key}
    try:
        response = http.post(endpoint, headers=headers, json=prices_session_payload(project))
        response.raise_for_status()
        session = _Session.model_validate_json(response.content)
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.connect_over_cdp(session.connect_url)
                try:
                    page = browser.contexts[0].new_page()
                    page.route(
                        "**/*",
                        lambda route: (
                            route.abort()
                            if route.request.resource_type == "image"
                            else route.continue_()
                        ),
                    )
                    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    status = response.status if response else 0
                    html = page.content()
                    return UnlockResult(
                        200 <= status < 300 and not is_blocked(status, "", html[:4096]),
                        html,
                        status,
                    )
                finally:
                    browser.close()
        finally:
            http.post(
                f"{endpoint}/{session.id}",
                headers=headers,
                json={"projectId": project, "status": "REQUEST_RELEASE"},
            ).raise_for_status()
    except Exception:
        # Neither CDP URLs nor vendor error bodies cross the credential boundary.
        raise RuntimeError("Browserbase request failed") from None
