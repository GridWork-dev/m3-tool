import html
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

import httpx
from pydantic import BaseModel

from m3_pipeline.refs.models import Source
from m3_pipeline.refs.sources import RefsSources
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.subjects import parse_subject
from m3_pipeline.refs.throttle import Throttle

PAGE_SIZE = 50
_LOG = logging.getLogger(__name__)
_API = "https://commons.wikimedia.org/w/api.php"


class CommonsFile(BaseModel):
    title: str
    page_url: str
    thumb_url: str
    mime: str
    license_short: str
    license_url: str | None
    author: str | None


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def merge_batch(acc: dict[str, dict[str, Any]], pages: Sequence[Mapping[str, Any]]) -> None:
    for page in pages:
        title = str(page["title"])
        current = acc.setdefault(title, {})
        previous: list[dict[str, Any]] = current.get("imageinfo", [])
        incoming: list[dict[str, Any]] = page.get("imageinfo", [])
        current.update({k: v for k, v in page.items() if k != "imageinfo"})
        if incoming:
            info = dict(previous[0]) if previous else {}
            info.update(incoming[0])
            current["imageinfo"] = [info]


def parse_page(page: Mapping[str, Any]) -> CommonsFile | None:
    infos: list[dict[str, Any]] = page.get("imageinfo", [])
    if not infos:
        return None
    info = infos[0]
    mime = info.get("mime")
    if mime not in {"image/jpeg", "image/png", "image/webp", "image/tiff"}:
        return None
    meta: dict[str, dict[str, Any]] = info.get("extmetadata") or {}
    license_short = str(meta.get("LicenseShortName", {}).get("value", "")).strip() or "unknown"
    license_url = str(meta.get("LicenseUrl", {}).get("value", "")).strip() or None
    parser = _Text()
    parser.feed(str(meta.get("Artist", {}).get("value", "")))
    author = " ".join(html.unescape("".join(parser.parts)).split()) or None
    return CommonsFile(
        title=str(page["title"]),
        page_url=info.get("descriptionurl", ""),
        thumb_url=info.get("thumburl") or info.get("url", ""),
        mime=mime,
        license_short=license_short,
        license_url=license_url,
        author=author,
    )


class CommonsThrottled(Exception):
    pass


class CommonsThumbWidthRejected(Exception):
    pass


@dataclass
class CommonsReport:
    seen: int = 0
    added: int = 0
    known: int = 0
    skipped_mime: int = 0
    skipped_no_imageinfo: int = 0
    failed: int = 0
    stopped_early: bool = False
    stop_reason: str | None = None


class CommonsClient:
    def __init__(
        self,
        http: httpx.Client,
        store: RefStore,
        *,
        sources: RefsSources,
        throttle: Throttle,
        max_retries: int = 3,
    ) -> None:
        self.http = http
        self.store = store
        self.sources = sources
        self.throttle = throttle
        self.max_retries = max_retries

    def _get(self, url: str, params: Mapping[str, str | int] | None = None) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            self.throttle.wait("commons", max(1.0, self.sources.commons.min_interval_s))
            response = self.http.get(
                url, params=params, headers={"User-Agent": self.sources.user_agent}
            )
            if response.status_code == 429 and "thumbnail steps" in response.text.lower():
                raise CommonsThumbWidthRejected
            error = ""
            if response.status_code == 200 and "json" in response.headers.get("content-type", ""):
                body: dict[str, Any] = response.json()
                error = str(body.get("error", {}).get("code", ""))
            if response.status_code not in {429, 503} and error not in {"maxlag", "ratelimited"}:
                response.raise_for_status()
                return response
            if attempt == self.max_retries:
                raise CommonsThrottled(
                    f"commons: HTTP {response.status_code} {error}; retries exhausted"
                )
            try:
                retry_after = max(0.0, float(response.headers.get("Retry-After", "5")))
            except ValueError:
                retry_after = 5.0
            delay = min(120.0, retry_after * 2**attempt)
            _LOG.info(
                "commons: HTTP %s from %s; Retry-After %gs; retry %s/%s",
                response.status_code,
                response.url.host,
                delay,
                attempt + 1,
                self.max_retries,
            )
            self.throttle.pause(delay)
        raise AssertionError("unreachable")

    def collect(
        self,
        subject: str,
        categories: Sequence[str] = (),
        *,
        search_terms: Sequence[str] = (),
        limit: int | None = None,
    ) -> CommonsReport:
        parse_subject(subject)
        report = CommonsReport()
        try:
            generators: list[dict[str, str | int]] = []
            for category in categories:
                title = category if category.startswith("Category:") else f"Category:{category}"
                generators.append(
                    {
                        "generator": "categorymembers",
                        "gcmtitle": title,
                        "gcmtype": "file",
                        "gcmlimit": PAGE_SIZE,
                    }
                )
            for term in search_terms:
                generators.append(
                    {
                        "generator": "search",
                        "gsrsearch": term,
                        "gsrnamespace": 6,
                        "gsrlimit": PAGE_SIZE,
                    }
                )
            for generator in generators:
                params: dict[str, str | int] = {
                    "action": "query",
                    "format": "json",
                    "formatversion": 2,
                    "prop": "imageinfo",
                    "iiprop": "url|size|mime|extmetadata",
                    "iiurlwidth": self.sources.commons.thumb_width,
                    "maxlag": 5,
                    **generator,
                }
                acc: dict[str, dict[str, Any]] = {}
                while True:
                    body: dict[str, Any] = self._get(_API, params).json()
                    merge_batch(acc, body.get("query", {}).get("pages", []))
                    continuation: dict[str, str | int] = body.get("continue", {})
                    if not continuation:
                        break
                    params.update(continuation)
                for title in sorted(acc)[:limit]:
                    page = acc[title]
                    report.seen += 1
                    file = parse_page(page)
                    if file is None:
                        if page.get("imageinfo"):
                            report.skipped_mime += 1
                        else:
                            report.skipped_no_imageinfo += 1
                        continue
                    if self.store.known_url(file.thumb_url) or self.store.known_url(file.page_url):
                        report.known += 1
                        continue
                    try:
                        response = self._get(file.thumb_url)
                    except httpx.HTTPError:
                        report.failed += 1
                        continue
                    if not response.headers.get("content-type", "").lower().startswith("image/"):
                        report.failed += 1
                        continue
                    result = self.store.ingest_bytes(
                        response.content,
                        subject=subject,
                        source=Source(
                            "commons",
                            file.thumb_url,
                            file.page_url,
                            file.author,
                            file.license_short,
                            file.license_url,
                        ),
                    )
                    if result.outcome == "added":
                        report.added += 1
                    elif result.outcome == "known_bytes":
                        report.known += 1
                    else:
                        report.failed += 1
        except CommonsThrottled as exc:
            report.stopped_early, report.stop_reason = True, str(exc)
        except CommonsThumbWidthRejected:
            report.stopped_early = True
            report.stop_reason = (
                "thumbnail width rejected; set commons.thumb_width to a standard step "
                "(1920 or 3840) in pipeline/refs-sources.toml"
            )
        return report
