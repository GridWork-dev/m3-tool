import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from refs_helpers import FakeClock

from m3_pipeline.prices.config import PricingConfig, SellerConfig
from m3_pipeline.prices.fetch import brightdata, tier
from m3_pipeline.prices.fetch.brightdata import UnlockResult, brightdata_unlock, redact
from m3_pipeline.prices.fetch.browserbase import prices_session_payload
from m3_pipeline.prices.fetch.evomi import evomi_proxy_url
from m3_pipeline.refs.crawl.browserbase import browserbase_session_payload
from m3_pipeline.refs.crawl.robots import RobotsCache
from m3_pipeline.refs.throttle import Throttle
from m3_pipeline.stages.lib import spend

SELLER = SellerConfig("example", "https://example.test", "polite")


def fetch(http: httpx.Client, seller: SellerConfig = SELLER) -> tier.FetchedPage:
    clock = FakeClock()
    return tier.fetch_page(
        "https://example.test/p",
        seller=seller,
        cfg=PricingConfig("test-agent", {seller.id: seller}),
        http=http,
        playwright_page_factory=None,
        robots=RobotsCache(http, "test-agent"),
        throttle=Throttle(3, clock=clock.now, sleep=clock.sleep),
    )


def test_polite_fetch_checks_robots_per_hop() -> None:
    seen: list[str] = []

    def respond(r: httpx.Request) -> httpx.Response:
        seen.append(str(r.url))
        if r.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        return httpx.Response(302, headers={"location": "https://other.test/private"})

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(tier.PageFetchError, match="disallowed"),
    ):
        fetch(http)
    assert seen == [
        "https://example.test/robots.txt",
        "https://example.test/p",
        "https://other.test/robots.txt",
    ]


def test_server_error_is_retried_once_not_escalated(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def respond(r: httpx.Request) -> httpx.Response:
        seen.append(r.url.path)
        return httpx.Response(404 if r.url.path == "/robots.txt" else 503)

    def unexpected(*args: object) -> UnlockResult:
        pytest.fail("escalated 503")

    monkeypatch.setattr(tier, "_brightdata", unexpected)
    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(tier.PageFetchError, match="503"),
    ):
        fetch(http)
    assert seen == ["/robots.txt", "/p", "/p"]


def test_blocked_polite_page_escalates_to_brightdata_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def unlock(http: httpx.Client, url: str) -> UnlockResult:
        calls.append(url)
        return UnlockResult(True, "<p>$100</p>", 200)

    monkeypatch.setattr(tier, "_brightdata", unlock)
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(404 if r.url.path == "/robots.txt" else 403)
        )
    ) as http:
        page = fetch(http)
    assert page.via == "brightdata" and len(calls) == 1
    assert page.usage == {"brightdata": 1}


def test_js_heavy_goes_to_browserbase_with_captcha_and_stealth_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(*args: object) -> UnlockResult:
        return UnlockResult(False, "enable javascript", 403)

    def succeeded(*args: object) -> UnlockResult:
        return UnlockResult(True, "<p>$100</p>", 200)

    monkeypatch.setattr(tier, "_brightdata", failed)
    monkeypatch.setattr(tier, "_browserbase", succeeded)
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("direct fetch"))) as http:
        assert fetch(http, replace(SELLER, tier="unblock")).via == "browserbase"
    settings = prices_session_payload("test-project")["browserSettings"]
    assert settings["solveCaptchas"] is True and settings["advancedStealth"] is True


def test_evomi_is_the_last_rung(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def rung(name: str, success: bool) -> object:
        def run(*args: object) -> UnlockResult:
            calls.append(name)
            return UnlockResult(success, "ok" if success else "captcha", 200 if success else 403)

        return run

    for name in ("brightdata", "browserbase", "evomi"):
        monkeypatch.setattr(tier, "_" + name, rung(name, name == "evomi"))
    with httpx.Client() as http:
        assert fetch(http, replace(SELLER, tier="unblock")).via == "evomi"
    assert calls == ["brightdata", "browserbase", "evomi"]


def test_javascript_shell_from_an_unblock_rung_escalates_to_the_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def shell(http: httpx.Client, url: str) -> UnlockResult:
        calls.append("brightdata")
        return UnlockResult(True, "<p>Please enable JavaScript to continue</p>", 200)

    def rendered(http: httpx.Client, url: str) -> UnlockResult:
        calls.append("browserbase")
        return UnlockResult(True, "<p>$100</p>", 200)

    monkeypatch.setattr(tier, "_brightdata", shell)
    monkeypatch.setattr(tier, "_browserbase", rendered)
    with httpx.Client(transport=httpx.MockTransport(lambda r: pytest.fail("direct fetch"))) as http:
        page = fetch(http, replace(SELLER, tier="unblock"))
    assert page.via == "browserbase" and calls == ["brightdata", "browserbase"]
    assert page.usage == {"brightdata": 1, "browserbase": 1}


def test_a_failing_javascript_render_becomes_a_page_error() -> None:
    from collections.abc import Generator
    from contextlib import contextmanager

    from playwright.sync_api import TimeoutError as PlaywrightTimeout

    from m3_pipeline.refs.crawl.engine import PageFetcher, PageResult

    class FailingPageFetcher:
        def fetch(self, url: str) -> PageResult:
            raise PlaywrightTimeout("navigation timed out")

    @contextmanager
    def factory() -> Generator[PageFetcher]:
        yield FailingPageFetcher()

    clock = FakeClock()

    def respond(r: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404 if r.url.path == "/robots.txt" else 200,
            text="<p>please enable javascript</p>",
        )

    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(tier.PageFetchError, match="javascript rendering failed"),
    ):
        tier.fetch_page(
            "https://example.test/p",
            seller=SELLER,
            cfg=PricingConfig("test-agent", {SELLER.id: SELLER}),
            http=http,
            playwright_page_factory=factory,
            robots=RobotsCache(http, "test-agent"),
            throttle=Throttle(0, clock=clock.now, sleep=clock.sleep),
        )


def test_prices_session_payload_is_the_inverse_of_refs() -> None:
    p, r = prices_session_payload("project"), browserbase_session_payload("project")
    assert p["projectId"] == "project" and p["timeout"] == 900 and p["proxies"] is False
    assert p["browserSettings"] == {
        "solveCaptchas": True,
        "advancedStealth": True,
        "verified": False,
    }
    assert r["browserSettings"] == {
        "solveCaptchas": False,
        "advancedStealth": False,
        "verified": False,
    }


def test_no_evasion_code_is_present() -> None:
    assert tier.__file__ is not None
    text = "".join(p.read_text() for p in Path(tier.__file__).parent.glob("*.py"))
    tokens = (
        "playwright_stealth",
        "stealth_sync",
        "fake_useragent",
        "2captcha",
        "Mozilla/5.0",
        "HeadlessChrome",
        "impersonate",
    )
    assert not [t for t in tokens if t in text]


def test_brightdata_token_and_evomi_url_never_logged(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M3_BRIGHTDATA_UNLOCKER_TOKEN", "test-key")
    proxy = "http://test-user:test-pass@proxy.test:8000"
    monkeypatch.setenv("M3_EVOMI_PROXY_URL", proxy)
    raw = f"Authorization: Bearer test-key wss://h?apiKey=test-key {proxy}"
    clean = redact(raw)
    assert all(s not in clean for s in ("test-key", "test-user", "test-pass"))
    assert all(s not in caplog.text for s in ("test-key", proxy))


def test_missing_credentials_name_variables_only() -> None:
    with pytest.raises(tier.MissingCredentials, match="M3_EVOMI_PROXY_URL") as exc:
        evomi_proxy_url({})
    assert "test-key" not in str(exc.value)


def test_brightdata_api_payload_and_spend_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M3_BRIGHTDATA_UNLOCKER_ZONE", "test-zone")
    calls: list[httpx.Request] = []
    authorized: list[tuple[str, Decimal]] = []

    def authorize(tag: str, price: Decimal, **kwargs: object) -> None:
        authorized.append((tag, price))

    monkeypatch.setattr(brightdata, "_authorize", authorize)
    monkeypatch.setenv("M3_PRICES_BRIGHTDATA_COST_USD", "0.01")

    def respond(r: httpx.Request) -> httpx.Response:
        assert authorized
        calls.append(r)
        return httpx.Response(200, text="<p>$100</p>")

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        result = brightdata_unlock(http, "https://example.test/p", token="test-key")
    assert result.success and "test-key" not in repr(result)
    assert str(calls[0].url) == "https://api.brightdata.com/request"
    assert calls[0].headers["Authorization"] == "Bearer test-key"
    assert json.loads(calls[0].content) == {
        "zone": "test-zone",
        "url": "https://example.test/p",
        "format": "raw",
    }
    assert authorized[0][0].startswith("prices-brightdata-")


def test_unblock_denied_without_session_before_any_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("M3_SPEND_SESSION", raising=False)
    monkeypatch.setenv("M3_PRICES_BRIGHTDATA_COST_USD", "0.01")
    monkeypatch.setenv("M3_BRIGHTDATA_UNLOCKER_ZONE", "test-zone")
    with (
        httpx.Client(
            transport=httpx.MockTransport(lambda r: pytest.fail("network before spend guard"))
        ) as http,
        pytest.raises(spend.SpendDenied, match="M3_SPEND_SESSION"),
    ):
        brightdata_unlock(http, "https://example.test/p", token="test-key")


def test_spend_uses_same_day_session_ledger_and_refuses_reuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hashlib
    from datetime import date

    url = "https://example.test/p"
    tag = f"prices-brightdata-{date.today()}-{hashlib.sha256(url.encode()).hexdigest()[:16]}"
    ledger = tmp_path / "ledger.md"
    journal = tmp_path / "journal.jsonl"
    ledger.write_text(
        "| Date | Session cap | Service | Purpose | Units | Cost (USD) | Running total / cap |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        f"| {date.today()} | $1 | all | cap approved by the user session:test | — | 0 | 0 / 1 |\n"
        f"| {date.today()} | — | Bright Data | spike:{tag} | 1 request | 0.01 | 0.01 / 1 |\n"
    )
    monkeypatch.setenv("M3_SPEND_SESSION", "test")
    monkeypatch.setenv("M3_PRICES_BRIGHTDATA_COST_USD", "0.01")
    monkeypatch.setenv("M3_BRIGHTDATA_UNLOCKER_ZONE", "test-zone")

    def guard(tag: str, price: Decimal, **kwargs: object) -> None:
        spend.authorize(tag, price, ledger=ledger, journal=journal)

    monkeypatch.setattr(brightdata, "_authorize", guard)
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))
    ) as http:
        assert brightdata_unlock(http, url, token="test-key").success
        with pytest.raises(spend.SpendDenied):
            brightdata_unlock(http, url, token="test-key")


def test_browserbase_releases_session_even_if_navigation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections.abc import Generator
    from contextlib import contextmanager
    from types import SimpleNamespace
    from typing import Any

    from m3_pipeline.prices.fetch import browserbase

    requests: list[httpx.Request] = []

    def respond(r: httpx.Request) -> httpx.Response:
        requests.append(r)
        return httpx.Response(
            200, json={"id": "test-session", "connectUrl": "wss://h?apiKey=test-key"}
        )

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("wss://h?apiKey=test-key")

    def route(*args: object) -> None:
        pass

    page = SimpleNamespace(route=route, goto=fail)
    browser = SimpleNamespace(contexts=[SimpleNamespace(new_page=lambda: page)], close=lambda: None)

    def connect(url: str) -> SimpleNamespace:
        return browser

    @contextmanager
    def fake_playwright() -> Generator[Any]:
        yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))

    def authorize(*args: object) -> None:
        pass

    monkeypatch.setenv("M3_BROWSERBASE_API_KEY", "test-key")
    monkeypatch.setenv("M3_BROWSERBASE_PROJECT_ID", "test-project")
    monkeypatch.setattr(browserbase, "authorize_fetch", authorize)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", fake_playwright)
    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(RuntimeError) as exc,
    ):
        browserbase.browserbase_unlock(http, "https://example.test/p")
    assert "test-key" not in str(exc.value)
    assert json.loads(requests[0].content) == prices_session_payload("test-project")
    assert requests[-1].url.path == "/v1/sessions/test-session"
    assert json.loads(requests[-1].content)["status"] == "REQUEST_RELEASE"


def test_evomi_proxy_transport_is_injected_and_guarded(monkeypatch: pytest.MonkeyPatch) -> None:
    from m3_pipeline.prices.fetch import evomi

    seen: list[str] = []

    def authorize(*args: object) -> None:
        seen.append("authorized")

    def client(**kwargs: object) -> httpx.Client:
        assert kwargs["proxy"] == "http://test-user:test-pass@proxy.test"
        return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok")))

    monkeypatch.setattr(evomi, "authorize_fetch", authorize)
    monkeypatch.setattr(evomi, "_client", client)
    result = evomi.evomi_unlock(
        "https://example.test/p",
        proxy_url="http://test-user:test-pass@proxy.test",
        user_agent="test-agent",
    )
    assert result.success and seen == ["authorized"]
