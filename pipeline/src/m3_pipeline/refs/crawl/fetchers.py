from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from contextlib import AbstractContextManager, contextmanager
from typing import TYPE_CHECKING, Literal, Protocol, cast

import httpx

from m3_pipeline.refs.crawl.browserbase import create_session, redact, release_session
from m3_pipeline.refs.crawl.engine import PageFetcher, PageResult

if TYPE_CHECKING:
    from playwright.sync_api import Page, Route


class _CDPSession(Protocol):
    def send(self, method: str, params: dict[str, str]) -> object: ...


class MissingCredentials(Exception):
    pass


class _PlaywrightFetcher:
    def __init__(self, page: Page, allowed: Callable[[str], bool] | None = None) -> None:
        self.page = page
        self.allowed = allowed
        self.page.route("**/*", self._route)

    def _route(self, route: Route) -> None:
        # The engine owns image requests so each one gets robots and throttle checks.
        request = route.request
        if request.resource_type == "image" or (
            self.allowed is not None
            and not (request.is_navigation_request() and request.frame == self.page.main_frame)
            and not self.allowed(request.url)
        ):
            route.abort()
        else:
            # Browsers load subresources in parallel; the host delay governs only
            # pages and images the engine chooses to visit, not subrequests.
            route.continue_()

    def fetch(self, url: str) -> PageResult:
        response = self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
        return PageResult(
            status=response.status if response else 0,
            html=self.page.content(),
            final_url=self.page.url,
        )


def open_fetcher(
    backend: Literal["local", "browserbase"],
    *,
    user_agent: str,
    env: Mapping[str, str],
    http: httpx.Client,
    allowed: Callable[[str], bool] | None = None,
) -> AbstractContextManager[PageFetcher]:
    # Validate eagerly: configuration mistakes must fail before context entry.
    if backend == "browserbase":
        missing = [
            name
            for name in ("M3_BROWSERBASE_API_KEY", "M3_BROWSERBASE_PROJECT_ID")
            if not env.get(name)
        ]
        if missing:
            raise MissingCredentials("missing variables: " + ", ".join(missing))
    elif backend != "local":
        raise ValueError(f"unknown browser backend {backend!r}")
    return _open_fetcher(backend, user_agent=user_agent, env=env, http=http, allowed=allowed)


@contextmanager
def _open_fetcher(
    backend: Literal["local", "browserbase"],
    *,
    user_agent: str,
    env: Mapping[str, str],
    http: httpx.Client,
    allowed: Callable[[str], bool] | None,
) -> Generator[PageFetcher]:
    from playwright.sync_api import sync_playwright

    if backend == "local":
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=user_agent)
                yield _PlaywrightFetcher(context.new_page(), allowed)
            finally:
                browser.close()
        return
    api_key = env["M3_BROWSERBASE_API_KEY"]
    project_id = env["M3_BROWSERBASE_PROJECT_ID"]
    try:
        session = create_session(http, api_key, project_id)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.connect_over_cdp(session.connect_url)
                try:
                    context = browser.contexts[0]
                    page = context.new_page()
                    cdp = cast(_CDPSession, context.new_cdp_session(page))
                    cdp.send("Network.setUserAgentOverride", {"userAgent": user_agent})
                    yield _PlaywrightFetcher(page, allowed)
                finally:
                    browser.close()
        finally:
            release_session(http, api_key, project_id, session.id)
    except Exception as exc:
        # Connection errors can include the credential-bearing CDP URL.
        raise RuntimeError(redact(str(exc)).replace(api_key, "***")) from None
