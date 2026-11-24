from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx
import yaml
from pydantic import BaseModel, Field

from m3_pipeline.config import load_settings
from m3_pipeline.prices.config import PricingConfig, SellerConfig
from m3_pipeline.prices.extract import extract_price
from m3_pipeline.prices.fetch.tier import FetchedPage, PageFetchError, fetch_page
from m3_pipeline.prices.models import Observation
from m3_pipeline.prices.report import CheckReport
from m3_pipeline.prices.runstate import RunState
from m3_pipeline.refs.crawl.blocked import is_blocked
from m3_pipeline.refs.crawl.robots import RobotsCache
from m3_pipeline.refs.throttle import Throttle

if TYPE_CHECKING:
    from m3_pipeline.refs.crawl.engine import PageFetcher
    from m3_pipeline.refs.store import RefStore

_throttle = Throttle


class PriceRow(BaseModel):
    amount: Decimal
    currency: str
    seller: str
    checked: date
    url: str | None = None


class PartOption(BaseModel):
    id: str
    prices: list[PriceRow] = Field(default_factory=list[PriceRow])


class PartRow(BaseModel):
    id: str
    name: str = ""
    brand: str = ""
    prices: list[PriceRow] = Field(default_factory=list[PriceRow])
    options: list[PartOption] = Field(default_factory=list[PartOption])


def load_parts(parts_dir: Path) -> Iterator[tuple[Path, PartRow]]:
    for path in sorted([*parts_dir.rglob("*.yaml"), *parts_dir.rglob("*.yml")]):
        yield path, PartRow.model_validate(yaml.safe_load(path.read_text()))


class _AdvisoryRobots(RobotsCache):
    def allowed(self, url: str) -> bool:
        return True

    def crawl_delay(self, url: str) -> float | None:
        return None


def _images(
    page: FetchedPage,
    part_id: str,
    seller: SellerConfig,
    cfg: PricingConfig,
    http: httpx.Client,
    store: RefStore,
    robots: RobotsCache,
    throttle: Throttle,
    report: CheckReport,
) -> None:
    from m3_pipeline.refs.crawl.engine import PageResult, crawl_pages
    from m3_pipeline.refs.sources import CrawlSettings

    class CachedPage:
        def fetch(self, url: str) -> PageResult:
            return PageResult(page.status, page.html, page.final_url)

    result = crawl_pages(
        f"product-{part_id}",
        [page.final_url],
        settings=CrawlSettings(min_side_px=seller.image_min_side_px, delay_s=3, max_pages=1),
        user_agent=cfg.user_agent,
        fetcher=CachedPage(),
        http=http,
        store=store,
        throttle=throttle,
        robots=robots if page.via == "polite" else _AdvisoryRobots(http, cfg.user_agent),
    )
    report.images_added += result.images_added
    report.disallowed.extend(result.disallowed)


def check_prices(
    parts_dir: Path,
    *,
    cfg: PricingConfig,
    http: httpx.Client,
    store: RefStore | None,
    today: date,
    playwright_page_factory: Callable[[], AbstractContextManager[PageFetcher]] | None = None,
) -> CheckReport:
    report = CheckReport()
    root = load_settings().work_dir / "prices"
    state = RunState(root / "last-run.json")
    robots, throttle = RobotsCache(http, cfg.user_agent), _throttle(3)
    for _path, part in load_parts(parts_dir):
        groups = [(None, part.prices), *((opt.id, opt.prices) for opt in part.options)]
        for option_id, prices in groups:
            latest: dict[tuple[str, str], PriceRow] = {}
            for old in prices:
                if old.url and (
                    (old.seller, old.url) not in latest
                    or old.checked > latest[(old.seller, old.url)].checked
                ):
                    latest[(old.seller, old.url)] = old
            for old in latest.values():
                assert old.url is not None
                seller = cfg.sellers.get(old.seller)
                if seller is None:
                    seller = next(
                        (
                            s
                            for s in cfg.sellers.values()
                            if urlsplit(s.base_url).hostname == urlsplit(old.url).hostname
                        ),
                        None,
                    )
                if seller is None or seller.opted_out:
                    continue
                if state.fetched_this_week(old.url, today):
                    report.skipped_this_week += 1
                    continue
                # Persist BEFORE fetching: a failed fetch or crash must not permit a rerun storm.
                state.mark(old.url, today)
                state.save()
                try:
                    page = fetch_page(
                        old.url,
                        seller=seller,
                        cfg=cfg,
                        http=http,
                        playwright_page_factory=playwright_page_factory,
                        robots=robots,
                        throttle=throttle,
                    )
                except PageFetchError as exc:
                    for service, units in exc.usage.items():
                        report.unblock_used[service] = report.unblock_used.get(service, 0) + units
                    target = (
                        report.disallowed
                        if "disallowed" in exc.reason
                        else (report.blocked if "blocked" in exc.reason else report.failed)
                    )
                    target.append(old.url)
                    continue
                report.checked += 1
                for service, units in page.usage.items():
                    report.unblock_used[service] = report.unblock_used.get(service, 0) + units
                if is_blocked(page.status, "", page.html[:4096]):
                    report.blocked.append(old.url)
                    continue
                value = extract_price(page.html, seller, storage_dir=root / "scrapling-store")
                if value is None:
                    report.flagged.append(
                        f"{part.id}: {old.url}: no unambiguous price; calibrate selectors"
                    )
                elif (
                    old.amount <= 0
                    or value.currency != old.currency
                    or max(value.amount / old.amount, old.amount / value.amount) >= 10
                ):
                    report.flagged.append(
                        f"{part.id}: {old.url}: review currency or >=10x price jump"
                    )
                else:
                    report.previous[old.url] = old.amount
                    report.observations.append(
                        Observation(
                            part.id,
                            option_id,
                            old.url,
                            old.seller,
                            value.amount,
                            value.currency,
                            today,
                        )
                    )
                if store is not None:
                    _images(page, part.id, seller, cfg, http, store, robots, throttle, report)
    return report


def save_report(report: CheckReport) -> Path:
    from pydantic import TypeAdapter

    path = load_settings().work_dir / "prices/report.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(TypeAdapter(CheckReport).dump_json(report))
    temp.replace(path)
    (path.parent / "applied.json").unlink(missing_ok=True)
    return path


def read_report() -> CheckReport:
    from pydantic import TypeAdapter

    return TypeAdapter(CheckReport).validate_json(
        (load_settings().work_dir / "prices/report.json").read_bytes()
    )
