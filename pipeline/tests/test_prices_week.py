from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.prices import week
from m3_pipeline.prices.apply import ApplyResult, PriceChange
from m3_pipeline.prices.check import read_report, save_report
from m3_pipeline.prices.config import PricingConfig
from m3_pipeline.prices.models import Observation
from m3_pipeline.prices.report import CheckReport


def test_week_runs_check_apply_pr_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    report = CheckReport(checked=1)
    result = ApplyResult([tmp_path / "fixture-wheel.yaml"])

    def check(*args: object, **kwargs: object) -> CheckReport:
        calls.append("check")
        return report

    def apply(*args: object, **kwargs: object) -> ApplyResult:
        assert args[1] is report
        calls.append("apply")
        return result

    def pr(**kwargs: object) -> str:
        assert kwargs["apply_result"] is result and kwargs["report"] is report
        calls.append("pr")
        return "https://github.com/example/m3-tool/pull/42"

    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(week, "_check", check)
    monkeypatch.setattr(week, "_apply", apply)
    monkeypatch.setattr(week, "_pr", pr)
    with httpx.Client() as http:
        output = week.run_week(
            tmp_path,
            cfg=PricingConfig("test-agent", {}),
            http=http,
            store=None,
            today=date(2026, 11, 24),
            runner_env={},
        )
    assert calls == ["check", "apply", "pr"]
    text = output.render()
    assert "| checked | 1 |" in text and "Ledger units:" in text and "/pull/42" in text


def test_week_skips_apply_and_pr_independently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def check(*args: object, **kwargs: object) -> CheckReport:
        return CheckReport()

    def apply(*args: object, **kwargs: object) -> ApplyResult:
        calls.append("apply")
        return ApplyResult()

    def pr(**kwargs: object) -> None:
        calls.append("pr")

    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setattr(week, "_check", check)
    monkeypatch.setattr(week, "_apply", apply)
    monkeypatch.setattr(week, "_pr", pr)
    with httpx.Client() as http:
        week.run_week(
            tmp_path,
            cfg=PricingConfig("test-agent", {}),
            http=http,
            store=None,
            today=date(2026, 11, 24),
            runner_env={},
            no_pr=True,
        )
        assert calls == ["apply"]
        calls.clear()
        week.run_week(
            tmp_path,
            cfg=PricingConfig("test-agent", {}),
            http=http,
            store=None,
            today=date(2026, 11, 24),
            runner_env={},
            no_apply=True,
        )
    assert calls == []


def test_week_cli_supports_review_only_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("M3_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline/pricing.toml").write_text("[sellers]\n")
    result = CliRunner().invoke(app, ["prices", "week", "--no-images", "--no-apply", "--no-pr"])
    assert result.exit_code == 0 and "Ledger units:" in result.output


def test_week_report_exposes_failures_and_evomi_gb() -> None:
    report = CheckReport(
        flagged=["fixture-wheel: review price"],
        blocked=["https://example.test/p"],
        unblock_used={"evomi": 500_000_000},
    )
    text = report.render()
    assert "fixture-wheel: review price" in text and "https://example.test/p" in text
    assert "evomi 0.5 GB" in text


def test_new_report_invalidates_previous_apply_handoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from m3_pipeline.prices.check import save_report
    from m3_pipeline.prices.week import read_apply_result, save_apply_result

    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    save_apply_result(ApplyResult([tmp_path / "old.yaml"]))
    assert read_apply_result() is not None
    save_report(CheckReport())
    assert read_apply_result() is None


def test_extraction_rejects_parent_from_label() -> None:
    from decimal import Decimal

    from m3_pipeline.prices.config import SellerConfig
    from m3_pipeline.prices.extract import extract_price

    html = (
        '<div>From <span class="price">$10</span></div><main><span class="price">$110</span></main>'
    )
    price = extract_price(
        html, SellerConfig("example", "https://example.test", "polite"), storage_dir=None
    )
    assert price is not None and price.amount == Decimal("110")


def test_pricing_currency_stays_within_the_read_only_data_contract(tmp_path: Path) -> None:
    from m3_pipeline.prices.config import ConfigError, load_pricing

    path = tmp_path / "pricing.toml"
    path.write_text(
        '[sellers.example]\nbase_url = "https://example.test"\ntier = "polite"\ncurrency = "GBP"\n'
    )
    with pytest.raises(ConfigError, match="currency"):
        load_pricing(path, {})


def test_repeated_check_preserves_unapplied_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    observation = Observation(
        "fixture-wheel",
        None,
        "https://example.test/p",
        "example",
        Decimal("110"),
        "USD",
        date(2026, 11, 24),
    )
    first = CheckReport(
        observations=[observation], previous={"https://example.test/p": Decimal("100")}
    )
    save_report(first)
    save_report(CheckReport(checked=0, skipped_this_week=1))
    kept = read_report()
    assert kept.observations == [observation]
    assert kept.previous["https://example.test/p"] == Decimal("100")


def test_applied_observations_are_not_remerged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    observation = Observation(
        "fixture-wheel",
        None,
        "https://example.test/p",
        "example",
        Decimal("110"),
        "USD",
        date(2026, 11, 24),
    )
    save_report(CheckReport(observations=[observation]))
    week.save_apply_result(ApplyResult(changes=[PriceChange(observation, None)]))
    save_report(CheckReport())
    assert read_report().observations == []
