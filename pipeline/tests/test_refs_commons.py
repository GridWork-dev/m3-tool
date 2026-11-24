import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from refs_fakes import FakeWikimedia
from refs_helpers import FakeClock

import m3_pipeline.refs.commons as commons_module
from m3_pipeline.refs.commons import CommonsClient, merge_batch, parse_page
from m3_pipeline.refs.sources import (
    DEFAULT_USER_AGENT,
    CommonsSettings,
    CrawlSettings,
    RefsSources,
)
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.throttle import Throttle

FULL = {
    "LicenseShortName": {"value": "CC BY-SA 4.0"},
    "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
    "Artist": {"value": '<a href="//x">Jane <b>Doe</b></a>'},
}


def commons_page(name: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    ii: dict[str, Any] = {
        "url": f"https://upload.wikimedia.org/o/{name}",
        "thumburl": f"https://upload.wikimedia.org/t/{name}",
        "mime": "image/jpeg",
        "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{name}",
        "width": 4000,
        "height": 3000,
    }
    if meta is not None:
        ii["extmetadata"] = meta
    return {"title": f"File:{name}", "imageinfo": [ii]}


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def world(clock: FakeClock) -> FakeWikimedia:
    return FakeWikimedia([commons_page(n, FULL) for n in ("a.jpg", "b.jpg", "c.jpg")], clock=clock)


@pytest.fixture
def make_client(
    world: FakeWikimedia, store: RefStore, clock: FakeClock
) -> Callable[..., CommonsClient]:
    def make(thumb_width: int = 1920) -> CommonsClient:
        return CommonsClient(
            httpx.Client(transport=world.transport, headers={"User-Agent": DEFAULT_USER_AGENT}),
            store,
            sources=RefsSources(
                DEFAULT_USER_AGENT, CommonsSettings(thumb_width), CrawlSettings(), {}
            ),
            throttle=Throttle(3.0, clock=clock.now, sleep=clock.sleep),
        )

    return make


@pytest.fixture
def client(make_client: Callable[..., CommonsClient]) -> CommonsClient:
    return make_client()


def test_parse_page_reads_license_author_and_urls() -> None:
    f = parse_page(commons_page("a.jpg", FULL))
    assert f is not None and f.license_url is not None
    assert (f.license_short, f.author) == ("CC BY-SA 4.0", "Jane Doe")
    assert f.license_url.endswith("/by-sa/4.0")
    assert f.thumb_url.endswith("/t/a.jpg") and f.page_url.endswith("File:a.jpg")


@pytest.mark.parametrize(
    "meta", [None, {}, {"LicenseShortName": {"value": ""}}, {"Artist": {"value": "<br/>"}}]
)
def test_missing_extmetadata_gives_unknown_license(meta: dict[str, Any] | None) -> None:
    f = parse_page(commons_page("a.jpg", meta))
    assert f is not None and (f.license_short, f.license_url, f.author) == ("unknown", None, None)


@pytest.mark.parametrize("mime", ["image/svg+xml", "application/pdf", "video/webm"])
def test_parse_page_skips_non_image_mimes(mime: str) -> None:
    p = commons_page("a.jpg")
    p["imageinfo"][0]["mime"] = mime
    assert parse_page(p) is None


def test_merge_batch_joins_by_title_and_pages_without_imageinfo_stay_unparseable() -> None:
    acc: dict[str, dict[str, Any]] = {}
    merge_batch(
        acc,
        [
            {"title": "File:a.jpg", "imageinfo": [{"url": "u", "mime": "image/jpeg"}]},
            {"title": "File:b.jpg"},
        ],
    )
    merge_batch(
        acc,
        [{"title": "File:a.jpg", "imageinfo": [{"extmetadata": FULL}]}, {"title": "File:b.jpg"}],
    )
    assert acc["File:a.jpg"]["imageinfo"][0] == {
        "url": "u",
        "mime": "image/jpeg",
        "extmetadata": FULL,
    }
    assert parse_page(acc["File:b.jpg"]) is None


def test_collect_survives_continuation_batches_without_imageinfo(
    world: FakeWikimedia,
    client: CommonsClient,
    store: RefStore,
) -> None:
    world.quirky_continuations = True
    rep = client.collect("e46-coupe", ["Test cars"])
    assert rep.added == 3 and rep.skipped_no_imageinfo == 0
    assert {r.license_short for r in store.records()} == {"CC BY-SA 4.0"}


def test_request_params_and_user_agent_are_pinned(
    world: FakeWikimedia, client: CommonsClient
) -> None:
    client.collect("e46-coupe", ["Test cars"])
    req = world.requests[0]
    q = req.url.params
    assert (q["generator"], q["gcmtitle"], q["gcmtype"], q["gcmlimit"], q["prop"]) == (
        "categorymembers",
        "Category:Test cars",
        "file",
        "50",
        "imageinfo",
    )
    assert (q["iiprop"], q["iiurlwidth"], q["maxlag"]) == ("url|size|mime|extmetadata", "1920", "5")
    assert req.headers["user-agent"] == DEFAULT_USER_AGENT


def test_collect_follows_continuation_and_records_provenance(
    world: FakeWikimedia,
    client: CommonsClient,
    store: RefStore,
) -> None:
    rep = client.collect("e46-coupe", ["Test cars"])
    recs = store.records()
    assert (rep.seen, rep.added) == (3, 3) and {r.source_kind for r in recs} == {"commons"}
    assert all(
        r.source_url and r.source_url.startswith("https://upload.wikimedia.org/t/") and r.page_url
        for r in recs
    )


def test_search_terms_use_the_file_namespace_search_generator(
    world: FakeWikimedia,
    client: CommonsClient,
    store: RefStore,
) -> None:
    rep = client.collect("e46-coupe-interior", [], search_terms=["E46 M3 interior"])
    q = world.requests[0].url.params
    assert (q["gsrsearch"], q["gsrnamespace"], q["prop"]) == ("E46 M3 interior", "6", "imageinfo")
    assert rep.added == 3 and len(store.records()) == 3


def test_same_file_from_category_and_search_is_ingested_once(
    client: CommonsClient,
    store: RefStore,
) -> None:
    rep = client.collect("e46-coupe", ["Test cars"], search_terms=["cars"])
    assert rep.added == 3 and rep.known == 3 and len(store.records()) == 3


def test_rerun_skips_known_urls_without_downloading(
    world: FakeWikimedia, client: CommonsClient
) -> None:
    client.collect("e46-coupe", ["Test cars"])
    n = len(world.requests)
    rep = client.collect("e46-coupe", ["Test cars"])
    assert rep.known == 3
    assert [r for r in world.requests[n:] if r.url.host == "upload.wikimedia.org"] == []


def test_api_calls_and_thumbnail_downloads_share_one_three_second_limiter(
    world: FakeWikimedia,
    client: CommonsClient,
) -> None:
    client.collect("e46-coupe", ["Test cars"])
    t = world.request_times
    assert any(r.url.host == "upload.wikimedia.org" for r in world.requests)
    assert all(b - a >= 3.0 for a, b in zip(t, t[1:], strict=False))


def test_maxlag_error_in_body_waits_then_retries(
    world: FakeWikimedia,
    client: CommonsClient,
    clock: FakeClock,
) -> None:
    world.maxlag_first = 1
    world.retry_after = 7
    assert client.collect("e46-coupe", ["Test cars"]).added == 3 and 7.0 in clock.slept


def test_429_with_retry_after_sleeps_via_the_injected_clock_then_succeeds(
    world: FakeWikimedia,
    client: CommonsClient,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    world.api_429_first = 1
    assert client.collect("e46-coupe", ["Test cars"]).added == 3
    assert 2.0 in clock.slept and "Retry-After 2" in caplog.text


def test_429_exhausts_retries_and_stops_cleanly(
    world: FakeWikimedia,
    client: CommonsClient,
    clock: FakeClock,
    store: RefStore,
) -> None:
    world.thumb_status = 429
    rep = client.collect("e46-coupe", ["Test cars"])
    assert rep.stopped_early and "429" in (rep.stop_reason or "") and store.records() == []
    assert {2.0, 4.0, 8.0} <= set(clock.slept)
    assert len([r for r in world.requests if r.url.host == "upload.wikimedia.org"]) == 4


def test_thumbnail_step_rejection_stops_with_config_hint(
    world: FakeWikimedia,
    make_client: Callable[..., CommonsClient],
) -> None:
    client = make_client(thumb_width=2560)
    world.thumb_status, world.thumb_body = 429, b"Use thumbnail steps listed on https://w.wiki/GHai"
    rep = client.collect("e46-coupe", ["Test cars"])
    assert rep.stopped_early and "thumb_width" in (rep.stop_reason or "")
    assert world.requests[0].url.params["iiurlwidth"] == "2560"
    assert len([r for r in world.requests if r.url.host == "upload.wikimedia.org"]) == 1


def test_non_image_thumbnail_body_counts_as_failed_not_stored(
    world: FakeWikimedia,
    client: CommonsClient,
    store: RefStore,
) -> None:
    world.thumb_body = b"<html>error</html>"
    rep = client.collect("e46-coupe", ["Test cars"], limit=1)
    assert rep.failed == 1 and store.records() == []


def test_no_category_names_or_search_terms_are_hard_coded() -> None:
    assert commons_module.__file__ is not None
    src = Path(commons_module.__file__).read_text()
    assert not re.search(r"Category:[A-Za-z]", src) and "E46" not in src and "BMW" not in src
