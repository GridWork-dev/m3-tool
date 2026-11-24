import hashlib
import json
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from refs_helpers import FakeClock
from refs_site import Site
from refs_site import site as site

from m3_pipeline.config import load_settings
from m3_pipeline.prices import check
from m3_pipeline.prices.apply import apply_observations
from m3_pipeline.prices.check import check_prices
from m3_pipeline.prices.config import PricingConfig, SellerConfig
from m3_pipeline.prices.fetch import brightdata, tier
from m3_pipeline.refs.store import RefStore
from m3_pipeline.stages.lib import spend


@dataclass
class Smoke:
    data: Path
    cfg: PricingConfig
    http: httpx.Client
    store: RefStore
    site: Site
    paid: list[httpx.Request]
    fallback: list[str]


def test_prices_offline_end_to_end_smoke(smoke: Smoke) -> None:
    report = check_prices(
        smoke.data / "parts", cfg=smoke.cfg, http=smoke.http, store=smoke.store, today=date.today()
    )
    assert report.checked == 2 and not report.failed and not report.blocked
    assert len(report.observations) == 2 and report.images_added == 1
    assert report.unblock_used == {"brightdata": 1}
    assert len(smoke.paid) == 1 and smoke.fallback == []
    assert smoke.site.hits("/market/product") == 1
    assert smoke.site.hits("/polite/product") == 1
    applied = apply_observations(smoke.data / "parts", report)
    assert len(applied.changed_files) == 1
    row: dict[str, Any] = yaml.safe_load(applied.changed_files[0].read_text())
    assert "prices" not in row
    assert [p["amount"] for p in row["options"][0]["prices"][-2:]] == [110, 120]
    assert all(p["checked"] == date.today().isoformat() for p in row["options"][0]["prices"][-2:])
    assert all(o.option_id == "fixture-wheel-17x8" for o in report.observations)
    assert validate_data(smoke.data).returncode == 0
    assert "| checked | 2 |" in report.render()
    assert "brightdata 1 unlocker requests" in report.render()
    assert smoke.store.records("product-fixture-wheel")[0].source_kind == "crawl"
    again = check_prices(
        smoke.data / "parts", cfg=smoke.cfg, http=smoke.http, store=smoke.store, today=date.today()
    )
    assert again.checked == 0 and again.skipped_this_week == 2
    assert smoke.site.hits("/polite/product") == smoke.site.hits("/market/product") == 1


def validate_data(data: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "tools/check-data.ts", str(data)],
        cwd=load_settings().repo_root,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, site: Site, store: RefStore
) -> Iterator[Smoke]:
    repo = load_settings().repo_root
    data = tmp_path / "fixture-data"
    shutil.copytree(repo / "tests/fixtures/data/valid", data)
    part = data / "parts/e46/fixture-wheel.yaml"
    for other in (data / "parts").rglob("*.yaml"):
        if other != part:
            other.unlink()
    row: dict[str, Any] = yaml.safe_load(part.read_text())
    row["options"] = row["options"][:1]

    def price(seller: str, amount: int) -> dict[str, Any]:
        return {
            "amount": amount,
            "currency": "USD",
            "seller": seller,
            "checked": "2026-11-01",
            "url": f"https://{seller}.test/product",
        }

    row["options"][0]["prices"] = [price("polite", 100), price("market", 100)]
    part.write_text(yaml.safe_dump(row, sort_keys=False))
    validation = validate_data(data)
    assert validation.returncode == 0, validation.stdout + validation.stderr
    for seller in ("polite", "market"):
        site.add(
            f"/{seller}/robots.txt",
            body="User-agent: *\nDisallow: /private\n",
            content_type="text/plain",
        )
    site.add("/polite/product", body='<span class="price">$110</span><img src="/photo.jpg">')
    site.add("/polite/photo.jpg", body=site.routes["/big.jpg"][1], content_type="image/jpeg")
    site.add("/market/product", body="<title>Vercel Security Checkpoint</title>", status=429)
    clock = FakeClock()

    def throttle(interval: float) -> check.Throttle:
        return check.Throttle(interval, clock=clock.now, sleep=clock.sleep)

    monkeypatch.setattr(check, "_throttle", throttle)
    monkeypatch.setenv("M3_WORK_DIR", str(store.work_dir))
    monkeypatch.setenv("M3_BRIGHTDATA_UNLOCKER_TOKEN", "test-key")
    monkeypatch.setenv("M3_BRIGHTDATA_UNLOCKER_ZONE", "test-zone")
    monkeypatch.setenv("M3_PRICES_BRIGHTDATA_COST_USD", "0.01")
    monkeypatch.setenv("M3_SPEND_SESSION", "smoke")
    target = "https://market.test/product"
    tag = f"prices-brightdata-{date.today()}-{hashlib.sha256(target.encode()).hexdigest()[:16]}"
    ledger = tmp_path / "spend-ledger.md"
    ledger.write_text(
        "| Date | Session cap | Service | Purpose | Units | Cost (USD) | Running total / cap |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        f"| {date.today()} | $1 | all | cap approved by the user session:smoke | — | 0 | 0 / 1 |\n"
        f"| {date.today()} | — | Bright Data | spike:{tag} | 1 request | 0.01 | 0.01 / 1 |\n"
    )

    def authorize(tag: str, price: Decimal, **kwargs: object) -> None:
        spend.authorize(tag, price, ledger=ledger, journal=tmp_path / "spend-journal.jsonl")

    monkeypatch.setattr(brightdata, "_authorize", authorize)
    fallback: list[str] = []

    def browserbase(*args: object) -> brightdata.UnlockResult:
        fallback.append("browserbase")
        pytest.fail("unexpected Browserbase rung")

    def evomi(*args: object) -> brightdata.UnlockResult:
        fallback.append("evomi")
        pytest.fail("unexpected Evomi rung")

    monkeypatch.setattr(tier, "_browserbase", browserbase)
    monkeypatch.setattr(tier, "_evomi", evomi)
    paid: list[httpx.Request] = []
    cfg = PricingConfig(
        "test-agent",
        {
            seller: SellerConfig(seller, f"https://{seller}.test", "polite")
            for seller in ("polite", "market")
        },
    )
    with httpx.Client(trust_env=False) as local:

        def respond(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.brightdata.com":
                paid.append(request)
                assert request.headers["Authorization"] == "Bearer test-key"
                assert json.loads(request.content) == {
                    "zone": "test-zone",
                    "url": target,
                    "format": "raw",
                }
                assert (tmp_path / "spend-journal.jsonl").exists()
                return httpx.Response(200, text='<span class="price">$120</span>')
            assert request.url.host in {"polite.test", "market.test"}
            seller = request.url.host.split(".")[0]
            response = local.get(
                site.url(f"/{seller}{request.url.path}"),
                headers={"User-Agent": request.headers["User-Agent"]},
            )
            return httpx.Response(
                response.status_code,
                content=response.content,
                headers=response.headers,
                request=request,
            )

        with httpx.Client(transport=httpx.MockTransport(respond)) as http:
            yield Smoke(data, cfg, http, store, site, paid, fallback)
