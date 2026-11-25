from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol
from urllib.parse import urljoin, urlsplit

import httpx

from m3_pipeline.prices.config import PricingConfig, SellerConfig
from m3_pipeline.prices.fetch.brightdata import (
    MissingCredentials as MissingCredentials,
)
from m3_pipeline.prices.fetch.brightdata import (
    UnlockResult,
    brightdata_unlock,
    credential,
)
from m3_pipeline.prices.fetch.browserbase import browserbase_unlock
from m3_pipeline.prices.fetch.evomi import evomi_proxy_url, evomi_unlock
from m3_pipeline.refs.crawl.blocked import is_blocked
from m3_pipeline.refs.crawl.robots import RobotsCache
from m3_pipeline.refs.throttle import Throttle
from m3_pipeline.stages.lib.spend import SpendDenied

if TYPE_CHECKING:
    from playwright.sync_api import Route

    from m3_pipeline.refs.crawl.engine import PageFetcher

Via = Literal["polite", "brightdata", "browserbase", "evomi"]


@dataclass(frozen=True)
class FetchedPage:
    html: str
    final_url: str
    status: int
    via: Via
    usage: dict[str, int] = field(default_factory=dict[str, int])


class PageFetchError(Exception):
    def __init__(self, url: str, reason: str, usage: dict[str, int] | None = None) -> None:
        self.url = url
        self.reason = reason
        self.usage = usage or {}
        super().__init__(reason)


def _needs_js(html: str) -> bool:
    return "enable javascript" in html.lower()


class _Unlocker(Protocol):
    def __call__(self, http: httpx.Client, url: str) -> UnlockResult: ...


def _brightdata(http: httpx.Client, url: str) -> UnlockResult:
    return brightdata_unlock(http, url, token=credential("M3_BRIGHTDATA_UNLOCKER_TOKEN"))


_browserbase = browserbase_unlock


def _evomi(http: httpx.Client, url: str) -> UnlockResult:
    return evomi_unlock(
        url,
        proxy_url=evomi_proxy_url(os.environ),
        user_agent=os.environ.get("M3_PRICES_USER_AGENT", "m3-tool-refs/0.1"),
    )


def _unblock(url: str, http: httpx.Client) -> FetchedPage:
    usage: dict[str, int] = {}
    rungs: list[tuple[Via, _Unlocker]] = [
        ("brightdata", _brightdata),
        ("browserbase", _browserbase),
        ("evomi", _evomi),
    ]
    for service, call in rungs:
        try:
            result = call(http, url)
        except MissingCredentials:
            continue
        except SpendDenied:
            raise
        except RuntimeError, httpx.HTTPError:
            usage[service] = 0 if service == "evomi" else 1
            continue
        usage[service] = result.transferred_bytes if service == "evomi" else 1
        if (
            result.success
            and not is_blocked(result.status, "", result.html[:4096])
            and not _needs_js(result.html)
        ):
            return FetchedPage(result.html, url, result.status, service, usage)
    raise PageFetchError(
        url, "blocked: all unblock services failed, lack credentials or returned shells", usage
    )


def _render_polite(
    url: str,
    http: httpx.Client,
    cfg: PricingConfig,
    robots: RobotsCache,
    throttle: Throttle,
) -> FetchedPage:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    def route_request(route: Route) -> None:
        request = route.request
        if request.resource_type == "image" or not robots.allowed(request.url):
            route.abort()
            return
        if request.is_navigation_request():
            throttle.wait(
                urlsplit(request.url).netloc, max(3, robots.crawl_delay(request.url) or 0)
            )
        route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(user_agent=cfg.user_agent, service_workers="block")
            context.route("**/*", route_request)
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return FetchedPage(
                page.content(), page.url, response.status if response else 0, "polite"
            )
        except PlaywrightError as exc:
            raise PageFetchError(url, "javascript rendering failed") from exc
        finally:
            browser.close()


def fetch_page(
    url: str,
    *,
    seller: SellerConfig,
    cfg: PricingConfig,
    http: httpx.Client,
    playwright_page_factory: Callable[[], AbstractContextManager[PageFetcher]] | None,
    robots: RobotsCache,
    throttle: Throttle,
) -> FetchedPage:
    if seller.opted_out:
        raise PageFetchError(url, "opted out")
    if seller.tier == "unblock":
        return _unblock(url, http)
    original = url
    for _hop in range(6):
        if not robots.allowed(url):
            raise PageFetchError(original, "disallowed by robots")
        interval = max(3, robots.crawl_delay(url) or 0)
        response: httpx.Response | None = None
        for attempt in range(2):
            throttle.wait(urlsplit(url).netloc, interval)
            try:
                response = http.get(
                    url, headers={"User-Agent": cfg.user_agent}, follow_redirects=False
                )
            except httpx.HTTPError:
                raise PageFetchError(original, "HTTP transport failed") from None
            if response.status_code < 500:
                break
            if attempt == 0:
                throttle.pause(2 * interval)
        assert response is not None
        if response.status_code >= 500:
            raise PageFetchError(original, f"HTTP {response.status_code}")
        if response.has_redirect_location:
            url = urljoin(str(response.url), response.headers["location"])
            continue
        html, status = response.text, response.status_code
        if is_blocked(status, "", html[:4096]):
            return _unblock(url, http)
        if not 200 <= status < 300:
            raise PageFetchError(original, f"HTTP {status}")
        if _needs_js(html):
            if playwright_page_factory:
                try:
                    with playwright_page_factory() as page:
                        result = page.fetch(url)
                except PageFetchError:
                    raise
                except Exception as exc:
                    # One unavailable page must not abort the whole collection:
                    # check_prices recovers per URL from PageFetchError only.
                    raise PageFetchError(original, "javascript rendering failed") from exc
            else:
                result = _render_polite(url, http, cfg, robots, throttle)
            if not robots.allowed(result.final_url):
                raise PageFetchError(original, "disallowed by robots")
            html, status, url = result.html, result.status, result.final_url
            if is_blocked(status, "", html[:4096]):
                return _unblock(url, http)
            if not 200 <= status < 300:
                raise PageFetchError(original, f"HTTP {status}")
        return FetchedPage(html, url, status, "polite")
    raise PageFetchError(original, "too many redirects")
