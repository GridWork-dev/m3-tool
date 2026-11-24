import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from m3_pipeline.refs.crawl.blocked import is_blocked
from m3_pipeline.refs.crawl.extract import extract_image_urls
from m3_pipeline.refs.crawl.robots import RobotsCache
from m3_pipeline.refs.imaging import UnreadableImage, inspect_image
from m3_pipeline.refs.models import Source
from m3_pipeline.refs.sources import CrawlSettings
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.subjects import parse_subject
from m3_pipeline.refs.throttle import Throttle

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class PageResult:
    status: int
    html: str
    final_url: str


class PageFetcher(Protocol):
    def fetch(self, url: str) -> PageResult: ...


@dataclass
class CrawlReport:
    pages_fetched: int = 0
    blocked: list[str] = field(default_factory=list[str])
    disallowed: list[str] = field(default_factory=list[str])
    images_added: int = 0
    images_known: int = 0
    images_small: int = 0
    images_failed: int = 0


def _blocked_page(page: PageResult) -> bool:
    title = re.search(r"<title\b[^>]*>(.*?)</title>", page.html, re.I | re.S)
    return is_blocked(page.status, title[1] if title else "", page.html[:4096])


def _log_blocked(status: int, url: str) -> None:
    _LOG.warning(
        "blocked (HTTP %s): %s; save the photos in a normal browser and add them with "
        "`pipeline refs import`",
        status,
        url,
    )


def crawl_pages(
    subject: str,
    urls: Sequence[str],
    *,
    settings: CrawlSettings,
    user_agent: str,
    fetcher: PageFetcher,
    http: httpx.Client,
    store: RefStore,
    throttle: Throttle,
) -> CrawlReport:
    parse_subject(subject)
    report = CrawlReport()
    robots = RobotsCache(http, user_agent)

    def wait(url: str) -> None:
        throttle.wait(urlsplit(url).netloc, max(settings.delay_s, robots.crawl_delay(url) or 0))

    for url in urls[: settings.max_pages]:
        if not robots.allowed(url):
            report.disallowed.append(url)
            continue
        wait(url)
        page = fetcher.fetch(url)
        report.pages_fetched += 1
        if _blocked_page(page):
            throttle.pause(2 * settings.delay_s)
            wait(url)
            page = fetcher.fetch(url)
            if _blocked_page(page):
                report.blocked.append(url)
                _log_blocked(page.status, url)
                continue
        if not 200 <= page.status < 300:
            _LOG.warning("page HTTP %s: %s", page.status, url)
            continue
        for image_url in extract_image_urls(page.html, page.final_url):
            if store.known_url(image_url) or store.was_skipped(image_url):
                continue
            if not robots.allowed(image_url):
                report.disallowed.append(image_url)
                continue
            wait(image_url)
            try:
                response = http.get(image_url, headers={"User-Agent": user_agent})
                if is_blocked(response.status_code, "", ""):
                    _log_blocked(response.status_code, image_url)
                    report.images_failed += 1
                    continue
                if not 200 <= response.status_code < 300 or not response.headers.get(
                    "content-type", ""
                ).lower().startswith("image/"):
                    report.images_failed += 1
                    _LOG.warning(
                        "image HTTP %s or non-image body: %s", response.status_code, image_url
                    )
                    continue
                info = inspect_image(response.content)
            except (httpx.HTTPError, UnreadableImage) as exc:
                report.images_failed += 1
                _LOG.warning("image failed: %s: %s", image_url, exc)
                continue
            if min(info.width, info.height) < settings.min_side_px:
                store.record_skip(image_url, "small")
                report.images_small += 1
                continue
            result = store.ingest_bytes(
                response.content,
                subject=subject,
                source=Source("crawl", image_url, page.final_url, None),
            )
            if result.outcome == "added":
                report.images_added += 1
            elif result.outcome == "known_bytes":
                report.images_known += 1
            else:
                report.images_failed += 1
    return report
