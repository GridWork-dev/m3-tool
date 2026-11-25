from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from m3_pipeline.prices.apply import ApplyResult, apply_observations
from m3_pipeline.prices.check import check_prices, merged_with_unapplied, save_report
from m3_pipeline.prices.config import PricingConfig
from m3_pipeline.prices.pr import open_pr
from m3_pipeline.prices.report import CheckReport

if TYPE_CHECKING:
    from m3_pipeline.refs.store import RefStore

_check = check_prices
_apply = apply_observations
_pr = open_pr


@dataclass(frozen=True)
class WeekResult:
    report: CheckReport
    apply_result: ApplyResult
    pr_url: str | None

    def render(self) -> str:
        return self.report.render() + (f"\nPR: {self.pr_url}" if self.pr_url else "")


def run_week(
    parts_dir: Path,
    *,
    cfg: PricingConfig,
    http: httpx.Client,
    store: RefStore | None,
    today: date,
    runner_env: Mapping[str, str],
    no_apply: bool = False,
    no_pr: bool = False,
) -> WeekResult:
    report = merged_with_unapplied(_check(parts_dir, cfg=cfg, http=http, store=store, today=today))
    save_report(report)
    applied = ApplyResult() if no_apply else _apply(parts_dir, report)
    if not no_apply:
        save_apply_result(applied)
    url = None
    if not no_pr and not no_apply:
        url = _pr(apply_result=applied, report=report, today=today, runner_env=runner_env)
    return WeekResult(report, applied, url)


def save_apply_result(result: ApplyResult) -> None:
    from pydantic import TypeAdapter

    from m3_pipeline.config import load_settings

    path = load_settings().work_dir / "prices/applied.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(TypeAdapter(ApplyResult).dump_json(result))
    temp.replace(path)


def read_apply_result() -> ApplyResult | None:
    from pydantic import TypeAdapter

    from m3_pipeline.config import load_settings

    path = load_settings().work_dir / "prices/applied.json"
    return TypeAdapter(ApplyResult).validate_json(path.read_bytes()) if path.exists() else None
