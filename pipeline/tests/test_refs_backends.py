import json
import subprocess
import sys
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from refs_site import Site
from refs_site import site as site
from typer.testing import CliRunner

import m3_pipeline.refs.crawl as crawl_pkg
from m3_pipeline.cli import app
from m3_pipeline.refs.crawl.browserbase import (
    browserbase_session_payload,
    create_session,
    redact,
)
from m3_pipeline.refs.crawl.fetchers import MissingCredentials, open_fetcher
from m3_pipeline.refs.crawl.robots import RobotsCache
from m3_pipeline.refs.sources import DEFAULT_USER_AGENT


def test_session_payload_turns_off_captcha_proxies_and_stealth() -> None:
    p = browserbase_session_payload("proj")
    b = p["browserSettings"]
    assert p["projectId"] == "proj" and p["proxies"] is False and p["timeout"] == 900
    assert b["verified"] is False
    assert b["solveCaptchas"] is False and b["advancedStealth"] is False and "fingerprint" not in b


def test_create_session_sends_key_header_and_never_logs_connect_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    requests: list[httpx.Request] = []

    def respond(r: httpx.Request) -> httpx.Response:
        requests.append(r)
        return httpx.Response(
            200,
            json={
                "id": "s1",
                "connectUrl": "wss://h?apiKey=test-key&sessionId=s1",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        s = create_session(http, "test-key", "proj")
    assert s.id == "s1" and "test-key" not in caplog.text and "test-key" not in repr(s)
    assert requests[0].headers["X-BB-API-Key"] == "test-key"
    assert requests[0].method == "POST"
    assert json.loads(requests[0].content) == browserbase_session_payload("proj")


def test_redact_strips_api_key_query() -> None:
    assert redact("wss://h?apiKey=abc&sessionId=1") == "wss://h?apiKey=***&sessionId=1"


def test_release_session_is_called_even_when_the_crawl_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    cdp_calls: list[tuple[str, dict[str, str]]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "s1",
                "connectUrl": "wss://h?apiKey=test-key&sessionId=s1",
            },
        )

    def send(method: str, params: dict[str, str]) -> None:
        cdp_calls.append((method, params))

    def route(pattern: str, handler: object) -> None:
        pass

    page = SimpleNamespace(close=lambda: None, route=route)

    def new_cdp_session(p: object) -> SimpleNamespace:
        return SimpleNamespace(send=send)

    context = SimpleNamespace(new_page=lambda: page, new_cdp_session=new_cdp_session)
    browser = SimpleNamespace(contexts=[context], close=lambda: None)

    def connect_over_cdp(url: str) -> SimpleNamespace:
        return browser

    @contextmanager
    def fake_playwright() -> Generator[Any]:
        yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect_over_cdp))

    monkeypatch.setattr("playwright.sync_api.sync_playwright", fake_playwright)
    with (
        httpx.Client(transport=httpx.MockTransport(respond)) as http,
        pytest.raises(RuntimeError, match="crawl failed"),
        open_fetcher(
            "browserbase",
            user_agent=DEFAULT_USER_AGENT,
            env={"M3_BROWSERBASE_API_KEY": "test-key", "M3_BROWSERBASE_PROJECT_ID": "proj"},
            http=http,
        ),
    ):
        raise RuntimeError("crawl failed")
    assert requests[-1].url.path == "/v1/sessions/s1"
    assert json.loads(requests[-1].content)["status"] == "REQUEST_RELEASE"
    assert ("Network.setUserAgentOverride", {"userAgent": DEFAULT_USER_AGENT}) in cdp_calls


def test_browserbase_backend_names_only_the_missing_variables() -> None:
    with httpx.Client() as http, pytest.raises(MissingCredentials) as e:
        open_fetcher(
            "browserbase",
            user_agent=DEFAULT_USER_AGENT,
            env={"M3_BROWSERBASE_API_KEY": "test-key"},
            http=http,
        )
    assert "M3_BROWSERBASE_PROJECT_ID" in str(e.value) and "test-key" not in str(e.value)
    assert "M3_BROWSERBASE_API_KEY" not in str(e.value)


def test_no_evasion_code_is_present() -> None:
    assert crawl_pkg.__file__ is not None
    text = "".join(p.read_text() for p in Path(crawl_pkg.__file__).parent.glob("*.py"))
    assert not [
        t
        for t in (
            "playwright_stealth",
            "stealth_sync",
            "fake_useragent",
            "2captcha",
            "Mozilla/5.0",
            "HeadlessChrome",
        )
        if t in text
    ]


def test_importing_the_cli_loads_no_heavy_dependencies() -> None:
    code = (
        "import sys, m3_pipeline.cli; "
        "print(','.join(sorted(m for m in "
        "('playwright', 'PIL', 'imagehash', 'numpy', 'scipy', 'boto3', 'rembg') "
        "if m in sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == ""


def test_crawl_cli_without_urls_exits_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline/refs-sources.toml").write_text("")
    monkeypatch.setenv("M3_REPO_ROOT", str(tmp_path))
    result = CliRunner().invoke(app, ["refs", "crawl", "--subject", "e46-coupe"])
    assert result.exit_code == 2 and "pipeline/refs-sources.toml" in result.output


@pytest.mark.browser
def test_playwright_fetcher_reports_status_and_sends_our_user_agent(site: Site) -> None:
    with (
        httpx.Client() as http,
        open_fetcher(
            "local",
            user_agent=DEFAULT_USER_AGENT,
            env={},
            http=http,
        ) as f,
    ):
        r = f.fetch(site.url("/ok.html"))
    assert r.status == 200 and "big.jpg" in r.html
    assert site.hits("/big.jpg") == 0 and site.hits("/small.jpg") == 0
    assert {x.user_agent for x in site.requests if x.path == "/ok.html"} == {DEFAULT_USER_AGENT}


@pytest.mark.browser
def test_playwright_fetcher_reports_403_status(site: Site) -> None:
    with (
        httpx.Client() as http,
        open_fetcher(
            "local",
            user_agent=DEFAULT_USER_AGENT,
            env={},
            http=http,
        ) as f,
    ):
        assert f.fetch(site.url("/blocked.html")).status == 403


@pytest.mark.browser
def test_browser_blocks_disallowed_subresources(site: Site) -> None:
    site.add(
        "/ok.html",
        body=(
            '<iframe src="/private/page.html"></iframe>'
            '<script src="/private/script.js"></script>'
            '<script src="/allowed.js"></script>'
            '<img src="/big.jpg">'
        ),
    )
    site.add("/private/script.js", body="window.disallowed = true", content_type="text/javascript")
    site.add("/allowed.js", body="window.allowed = true", content_type="text/javascript")
    with (
        httpx.Client(headers={"User-Agent": DEFAULT_USER_AGENT}) as http,
        open_fetcher(
            "local",
            user_agent=DEFAULT_USER_AGENT,
            env={},
            http=http,
            allowed=RobotsCache(http, DEFAULT_USER_AGENT).allowed,
        ) as fetcher,
    ):
        assert fetcher.fetch(site.url("/ok.html")).status == 200
    assert site.hits("/private/page.html") == site.hits("/private/script.js") == 0
    assert site.hits("/allowed.js") == 1
    assert site.hits("/big.jpg") == 0
