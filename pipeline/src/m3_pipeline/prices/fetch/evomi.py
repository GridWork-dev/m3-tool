from collections.abc import Mapping

import httpx

from m3_pipeline.prices.fetch.brightdata import MissingCredentials, UnlockResult, authorize_fetch
from m3_pipeline.refs.crawl.blocked import is_blocked

_client = httpx.Client


def evomi_proxy_url(env: Mapping[str, str]) -> str:
    value = env.get("M3_EVOMI_PROXY_URL")
    if not value:
        raise MissingCredentials("missing variable: M3_EVOMI_PROXY_URL")
    return value


def evomi_unlock(url: str, *, proxy_url: str, user_agent: str) -> UnlockResult:
    authorize_fetch("evomi", url)
    try:
        with _client(proxy=proxy_url, timeout=60, follow_redirects=True) as http:
            response = http.get(url, headers={"User-Agent": user_agent})
    except httpx.HTTPError:
        raise RuntimeError("Evomi request failed") from None
    return UnlockResult(
        200 <= response.status_code < 300
        and not is_blocked(response.status_code, "", response.text[:4096]),
        response.text,
        response.status_code,
    )
