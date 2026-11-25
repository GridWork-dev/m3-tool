from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from m3_pipeline.prices.fetch.brightdata import authorize_fetch

_authorize_fetch = authorize_fetch


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str


class _Result(BaseModel):
    url: str
    title: str | None = None


class _Response(BaseModel):
    results: list[_Result] = Field(default_factory=list[_Result])


def exa_search(
    http: httpx.Client, *, query: str, api_key: str, limit: int = 5
) -> list[SearchResult]:
    if not 1 <= limit <= 100:
        raise ValueError("Exa limit must be between 1 and 100")
    _authorize_fetch("exa", query)
    try:
        response = http.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key},
            json={"query": query, "numResults": limit, "type": "auto"},
            timeout=60,
        )
        response.raise_for_status()
        result = _Response.model_validate_json(response.content)
    except httpx.HTTPError, ValueError:
        raise RuntimeError("Exa search failed") from None
    return [
        SearchResult(r.url, r.title or "")
        for r in result.results
        if urlsplit(r.url).scheme in {"http", "https"} and not urlsplit(r.url).username
    ]
