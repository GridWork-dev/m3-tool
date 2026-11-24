import pytest

from m3_pipeline.refs.crawl.blocked import is_blocked
from m3_pipeline.refs.crawl.extract import extract_image_urls
from m3_pipeline.refs.crawl.robots import parse_robots
from m3_pipeline.refs.sources import DEFAULT_USER_AGENT


@pytest.mark.parametrize("status,expect", [(404, True), (410, True), (500, False), (403, False)])
def test_parse_robots_status_rules(status: int, expect: bool) -> None:
    assert parse_robots(status, "").can_fetch(DEFAULT_USER_AGENT, "https://h/x") is expect


def test_robots_matches_our_product_token_and_exposes_crawl_delay() -> None:
    p = parse_robots(200, "User-agent: m3-tool-refs\nCrawl-delay: 10\nDisallow: /private/\n")
    assert not p.can_fetch(DEFAULT_USER_AGENT, "https://h/private/a")
    assert p.can_fetch(DEFAULT_USER_AGENT, "https://h/public/a")
    assert p.crawl_delay(DEFAULT_USER_AGENT) == 10


@pytest.mark.parametrize(
    "status,title,head,blocked",
    [
        (403, "", "", True),
        (429, "Vercel Security Checkpoint", "", True),
        (200, "Just a moment...", "", True),
        (200, "x", "Please verify you are human", True),
        (200, "Vercel Security Checkpoint", "", True),
        (200, "E46 M3 gallery", "photos", False),
    ],
)
def test_is_blocked(status: int, title: str, head: str, blocked: bool) -> None:
    assert is_blocked(status, title, head) is blocked


def test_extract_image_urls_covers_img_srcset_links_og_and_lazy_attrs() -> None:
    html = (
        '<meta property="og:image" content="/og.jpg"><img src="a.jpg"><img data-src="b.jpg">'
        '<img srcset="c1.jpg 400w, c2.jpg 1600w"><a href="d.png">x</a>'
        '<img src="data:image/gif;base64,AAAA">'
    )
    assert extract_image_urls(html, "https://h/p/") == [
        "https://h/og.jpg",
        "https://h/p/a.jpg",
        "https://h/p/b.jpg",
        "https://h/p/c2.jpg",
        "https://h/p/d.png",
    ]
