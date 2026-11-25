import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from m3_pipeline.prices import pr
from m3_pipeline.prices.apply import ApplyResult, PriceChange
from m3_pipeline.prices.models import Observation
from m3_pipeline.prices.report import CheckReport


def setup_pr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ApplyResult, CheckReport, list[list[str]], list[str]]:
    path = tmp_path / "data/parts/e46/fixture-wheel.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("id: fixture-wheel\n")
    monkeypatch.setenv("M3_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("M3_WORK_DIR", str(tmp_path / "work"))
    obs = Observation(
        "fixture-wheel",
        "wide",
        "https://example.test/p",
        "example",
        Decimal("250"),
        "USD",
        date(2026, 11, 24),
    )
    result = ApplyResult([path], [PriceChange(obs, Decimal("100"))])
    report = CheckReport(observations=[obs], unblock_used={"brightdata": 1})
    calls: list[list[str]] = []
    bodies: list[str] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(args)
        if args[:3] == ["gh", "pr", "create"]:
            bodies.append(Path(args[args.index("--body-file") + 1]).read_text())
            return subprocess.CompletedProcess(
                args, 0, "https://github.com/example/m3-tool/pull/42\n", ""
            )
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(pr, "_run", run)
    return result, report, calls, bodies


def test_open_pr_stages_only_changed_files_and_renders_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, report, calls, bodies = setup_pr(tmp_path, monkeypatch)
    url = pr.open_pr(apply_result=result, report=report, today=date(2026, 11, 24), runner_env={})
    assert url == "https://github.com/example/m3-tool/pull/42"
    assert ["git", "switch", "-c", "data/prices-2026-11-24"] in calls
    assert ["git", "add", "--", "data/parts/e46/fixture-wheel.yaml"] in calls
    assert any(c[:2] == ["git", "push"] for c in calls)
    assert "100 → 250" in bodies[0] and ">20%" in bodies[0] and "wide" in bodies[0]
    assert "Ledger units:" in bodies[0] and "Claude-Session" not in bodies[0]
    assert "session URL" not in bodies[0] and all("-A" not in c for c in calls)


def test_no_pr_flow_never_pushes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, report, calls, bodies = setup_pr(tmp_path, monkeypatch)
    assert (
        pr.open_pr(
            apply_result=result,
            report=report,
            today=date(2026, 11, 24),
            runner_env={"M3_PRICES_NO_PR": "1"},
        )
        is None
    )
    assert any(c[:2] == ["git", "commit"] for c in calls)
    assert not any(c[:2] in (["git", "push"], ["gh", "pr"]) for c in calls)
    assert not bodies


def test_empty_and_dry_run_results_do_not_call_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result, report, calls, _ = setup_pr(tmp_path, monkeypatch)
    assert (
        pr.open_pr(
            apply_result=ApplyResult(), report=report, today=date(2026, 11, 24), runner_env={}
        )
        is None
    )
    result.dry_run = True
    assert (
        pr.open_pr(apply_result=result, report=report, today=date(2026, 11, 24), runner_env={})
        is None
    )
    assert calls == []


def test_pr_refuses_paths_outside_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, report, calls, _ = setup_pr(tmp_path, monkeypatch)
    result.changed_files = [tmp_path / "AGENTS.md"]
    with pytest.raises(ValueError, match="data/parts"):
        pr.open_pr(apply_result=result, report=report, today=date(2026, 11, 24), runner_env={})
    assert not calls


def test_change_table_flags_over_ten_times(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    result, report, _, bodies = setup_pr(tmp_path, monkeypatch)
    result.changes[0] = PriceChange(result.changes[0].observation, Decimal("1"))
    pr.open_pr(apply_result=result, report=report, today=date(2026, 11, 24), runner_env={})
    assert ">10×" in bodies[0]
