import json
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from refs_helpers import FakeClock, make_image_bytes

from m3_pipeline.prices import check
from m3_pipeline.prices.config import PricingConfig, SellerConfig
from m3_pipeline.prices.extract import extract_price
from m3_pipeline.prices.report import CheckReport
from m3_pipeline.prices.runstate import RunState
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.throttle import Throttle

TODAY = date(2026, 11, 24)
SELLER = SellerConfig("example", "https://example.test", "polite", price_selectors=(".price",))
CFG = PricingConfig("test-agent", {"example": SELLER})
FIXTURES = Path(__file__).parent / "fixtures/prices"


@pytest.fixture
def price_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    clock = FakeClock()

    def throttle(interval: float) -> Throttle:
        return Throttle(interval, clock=clock.now, sleep=clock.sleep)

    monkeypatch.setattr(check, "_throttle", throttle)
    parts = tmp_path / "parts"
    parts.mkdir()
    return parts


def write_part(parts: Path, *, options: bool = False, amount: int = 100) -> Path:
    row: dict[str, Any] = {
        "id": "fixture-wheel",
        "prices": [
            {
                "amount": amount,
                "currency": "USD",
                "seller": "example",
                "checked": "2026-11-01",
                "url": "https://example.test/p",
            }
        ],
    }
    if options:
        row["options"] = [
            {
                "id": "wide",
                "prices": [
                    {
                        "amount": 200,
                        "currency": "USD",
                        "seller": "example",
                        "checked": "2026-11-01",
                        "url": "https://example.test/option",
                    }
                ],
            }
        ]
    path = parts / "fixture-wheel.yaml"
    path.write_text(yaml.safe_dump(row, sort_keys=False))
    return path


def client(html: str = '<span class="price">$110.00</span>') -> httpx.Client:
    def respond(r: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if r.url.path == "/robots.txt" else 200, text=html)

    return httpx.Client(transport=httpx.MockTransport(respond))


def test_rerun_within_the_week_skips_every_url(price_env: Path) -> None:
    write_part(price_env, options=True)
    with client() as http:
        first = check.check_prices(price_env, cfg=CFG, http=http, store=None, today=TODAY)
    assert first.checked == 2
    with httpx.Client(
        transport=httpx.MockTransport(lambda r: pytest.fail("weekly rerun fetched"))
    ) as http:
        second = check.check_prices(
            price_env, cfg=CFG, http=http, store=None, today=TODAY + timedelta(days=6)
        )
    assert second.skipped_this_week == 2 and second.checked == 0


def test_blocked_page_is_never_extracted() -> None:
    assert (
        extract_price((FIXTURES / "ebay-blocked.html").read_text(), SELLER, storage_dir=None)
        is None
    )
    assert (
        extract_price(
            (FIXTURES / "apex-vercel-checkpoint.html").read_text(), SELLER, storage_dir=None
        )
        is None
    )


def test_extraction_rejects_shipping_and_from_prices(tmp_path: Path) -> None:
    found = extract_price((FIXTURES / "turner-ok.html").read_text(), SELLER, storage_dir=tmp_path)
    assert found is not None and found.amount == Decimal("499.95") and found.currency == "USD"
    assert list(tmp_path.glob("*.db"))
    assert extract_price('<span class="price">From $10</span>', SELLER, storage_dir=None) is None
    assert extract_price('<span class="price">€10</span>', SELLER, storage_dir=None) is None
    assert extract_price('<span class="price">$0</span>', SELLER, storage_dir=None) is None


def test_sale_page_uses_the_current_price_not_the_strikethrough() -> None:
    html = '<del class="price">$199</del><span class="price">$149</span>'
    found = extract_price(html, SELLER, storage_dir=None)
    assert found is not None and found.amount == Decimal("149")


def test_conflicting_price_candidates_are_rejected() -> None:
    html = '<span class="price">$199</span><span class="price">$149</span>'
    assert extract_price(html, SELLER, storage_dir=None) is None


def test_numeric_price_with_foreign_currency_metadata_is_rejected() -> None:
    # Default hint list (no calibrated selectors): the page's own currency metadata
    # must agree with the seller's configured currency.
    plain = SellerConfig("example", "https://example.test", "polite")
    foreign = (
        '<span itemprop="price" content="149.00"></span>'
        '<meta itemprop="priceCurrency" content="EUR">'
    )
    assert extract_price(foreign, plain, storage_dir=None) is None
    matching = (
        '<span itemprop="price" content="149.00"></span>'
        '<meta itemprop="priceCurrency" content="USD">'
    )
    found = extract_price(matching, plain, storage_dir=None)
    assert found is not None and found.amount == Decimal("149.00")


def test_price_jump_over_ten_x_is_flagged(price_env: Path) -> None:
    write_part(price_env, amount=1)
    with client() as http:
        report = check.check_prices(price_env, cfg=CFG, http=http, store=None, today=TODAY)
    assert report.flagged and not report.observations


def test_option_prices_are_checked_their_own_urls(price_env: Path) -> None:
    write_part(price_env, options=True)
    with client() as http:
        report = check.check_prices(price_env, cfg=CFG, http=http, store=None, today=TODAY)
    assert {(o.option_id, o.url) for o in report.observations} == {
        (None, "https://example.test/p"),
        ("wide", "https://example.test/option"),
    }
    assert all(o.checked == TODAY for o in report.observations)


def test_images_ride_along_into_product_subjects(price_env: Path, store: RefStore) -> None:
    write_part(price_env)
    image = make_image_bytes(71)

    def respond(r: httpx.Request) -> httpx.Response:
        if r.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private")
        if r.url.path.endswith(".jpg"):
            assert r.url.path != "/private/hidden.jpg"
            return httpx.Response(200, content=image, headers={"content-type": "image/jpeg"})
        return httpx.Response(
            200,
            text=(
                '<span class="price">$100</span><img src="/photo.jpg">'
                '<img src="/private/hidden.jpg">'
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        report = check.check_prices(price_env, cfg=CFG, http=http, store=store, today=TODAY)
    assert report.images_added == 1
    record = store.records("product-fixture-wheel")[0]
    assert record.source_kind == "crawl" and record.page_url == "https://example.test/p"


def test_torn_runstate_tail_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "last-run.json"
    state = RunState(path)
    state.mark("https://example.test/p", TODAY)
    state.save()
    with path.open("ab") as file:
        file.write(b'{"url":')
    restored = RunState(path)
    assert restored.fetched_this_week("https://example.test/p", TODAY)
    assert not restored.fetched_this_week("https://example.test/p", TODAY + timedelta(days=7))
    assert path.read_bytes().endswith(b"\n")
    path.write_text("{broken}\n" + json.dumps({"url": "x", "day": str(TODAY)}) + "\n")
    with pytest.raises(ValueError, match="last-run.json:1"):
        RunState(path)


def test_report_renders_units_for_the_ledger() -> None:
    text = CheckReport(checked=3, unblock_used={"brightdata": 1, "browserbase": 2}).render()
    assert "| checked | 3 |" in text
    assert "Ledger units:" in text and "brightdata 1 unlocker requests" in text
    assert "browserbase 2 sessions" in text and "evomi 0 GB" in text


def test_prices_cli_import_stays_light() -> None:
    code = (
        "import sys, m3_pipeline.cli; assert not set(('playwright', 'PIL', "
        "'imagehash', 'numpy', 'scipy', 'boto3', 'rembg', 'scrapling')) "
        "& sys.modules.keys()"
    )
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


def test_prices_check_cli_and_report_round_trip(
    price_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from m3_pipeline.cli import app
    from m3_pipeline.prices.check import read_report, save_report

    monkeypatch.setenv("M3_REPO_ROOT", str(price_env.parent))
    (price_env.parent / "pipeline").mkdir()
    (price_env.parent / "pipeline/pricing.toml").write_text("[sellers]\n")
    result = CliRunner().invoke(app, ["prices", "check", "--no-images"])
    assert result.exit_code == 0 and "Ledger units:" in result.output
    report = CheckReport(checked=2)
    save_report(report)
    assert read_report() == report
