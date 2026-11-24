from collections.abc import Sequence

import httpx
import pytest
from refs_helpers import FakeClock
from refs_site import Site
from refs_site import site as site

from m3_pipeline.refs.crawl.engine import CrawlReport, PageResult, crawl_pages
from m3_pipeline.refs.sources import DEFAULT_USER_AGENT, CrawlSettings
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.throttle import Throttle


class HttpxPageFetcher:
    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def fetch(self, url: str) -> PageResult:
        r = self.http.get(url)
        return PageResult(r.status_code, r.text, str(r.url))


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def run(
    site: Site,
    store: RefStore,
    urls: Sequence[str],
    clock: FakeClock,
    *,
    settings: CrawlSettings | None = None,
) -> CrawlReport:
    with httpx.Client(headers={"User-Agent": DEFAULT_USER_AGENT}) as http:
        return crawl_pages(
            "e46-coupe",
            urls,
            settings=settings or CrawlSettings(),
            user_agent=DEFAULT_USER_AGENT,
            fetcher=HttpxPageFetcher(http),
            http=http,
            store=store,
            throttle=Throttle(3.0, clock=clock.now, sleep=clock.sleep),
        )


def test_disallowed_page_is_skipped_and_never_requested(
    site: Site,
    store: RefStore,
    clock: FakeClock,
) -> None:
    rep = run(site, store, [site.url("/private/page.html")], clock)
    assert rep.disallowed == [site.url("/private/page.html")]
    assert site.hits("/private/page.html") == 0


def test_403_page_is_logged_as_blocked_with_an_import_hint_and_retried_once(
    site: Site,
    store: RefStore,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    rep = run(site, store, [site.url("/blocked.html")], clock)
    assert rep.blocked == [site.url("/blocked.html")] and site.hits("/blocked.html") == 2
    assert "refs import" in caplog.text


def test_429_checkpoint_page_is_blocked_and_never_ingested(
    site: Site,
    store: RefStore,
    clock: FakeClock,
) -> None:
    for path in ("/checkpoint.html", "/challenge.html"):
        rep = run(site, store, [site.url(path)], clock)
        assert rep.blocked == [site.url(path)] and site.hits(path) == 2 and store.records() == []


def test_big_image_is_ingested_with_crawl_provenance_and_small_one_is_remembered(
    site: Site,
    store: RefStore,
    clock: FakeClock,
) -> None:
    rep = run(site, store, [site.url("/ok.html")], clock)
    r = store.records()[0]
    assert (rep.images_added, rep.images_small) == (1, 1)
    assert (r.source_kind, r.license_short, r.page_url) == (
        "crawl",
        "unknown",
        site.url("/ok.html"),
    )
    run(site, store, [site.url("/ok.html")], clock)
    assert site.hits("/small.jpg") == 1 and site.hits("/big.jpg") == 1


def test_image_403_is_logged_blocked_and_skipped(
    site: Site,
    store: RefStore,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    site.add("/ok.html", body='<img src="/denied.jpg">')
    site.add("/denied.jpg", status=403)
    rep = run(site, store, [site.url("/ok.html")], clock)
    assert rep.images_failed == 1 and store.records() == []
    assert "blocked" in caplog.text and "denied.jpg" in caplog.text


def test_waits_between_requests_to_the_same_host(
    site: Site,
    store: RefStore,
    clock: FakeClock,
) -> None:
    run(site, store, [site.url("/ok.html")], clock)
    assert clock.slept.count(3.0) >= 2


def test_crawl_delay_larger_than_default_is_honored(
    site: Site,
    store: RefStore,
    clock: FakeClock,
) -> None:
    site.add("/robots.txt", body="User-agent: *\nCrawl-delay: 10\nDisallow: /private/\n")
    run(site, store, [site.url("/ok.html")], clock)
    assert 10.0 in clock.slept


def test_robots_applies_to_images_as_well_as_pages(
    site: Site,
    store: RefStore,
    clock: FakeClock,
) -> None:
    site.add("/ok.html", body='<img src="/private/image.jpg">')
    site.add("/private/image.jpg", body=b"unused", content_type="image/jpeg")
    rep = run(site, store, [site.url("/ok.html")], clock)
    assert site.hits("/private/image.jpg") == 0
    assert site.url("/private/image.jpg") in rep.disallowed


def test_max_pages_caps_visits(site: Site, store: RefStore, clock: FakeClock) -> None:
    rep = run(
        site,
        store,
        [site.url("/ok.html"), site.url("/other.html")],
        clock,
        settings=CrawlSettings(max_pages=1),
    )
    assert rep.pages_fetched == 1 and site.hits("/other.html") == 0


def test_every_request_carries_our_user_agent(
    site: Site, store: RefStore, clock: FakeClock
) -> None:
    run(site, store, [site.url("/ok.html")], clock)
    assert {r.user_agent for r in site.requests} == {DEFAULT_USER_AGENT}
