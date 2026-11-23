from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.stages import REGISTRY, StageResult


def test_cli_unknown_stage_exits_2() -> None:
    r = CliRunner().invoke(app, ["run", "e46-coupe-body", "--stage", "nope"])
    assert r.exit_code == 2 and "unknown stage 'nope'" in r.output


def test_cli_unknown_asset_exits_2() -> None:
    r = CliRunner().invoke(app, ["run", "nope", "--stage", "validate"])
    assert r.exit_code == 2 and "unknown asset 'nope'" in r.output


def test_cli_runs_registered_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(REGISTRY, "fake", lambda a, s: StageResult(False, ["boom"], []))
    r = CliRunner().invoke(app, ["run", "e46-coupe-body", "--stage", "fake"])
    assert r.exit_code == 1 and "boom" in r.output


def test_cli_run_exits_0_for_a_registered_stage_that_returns_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = Path("/work/e46-coupe-body.validate.json")
    monkeypatch.setitem(REGISTRY, "fake", lambda a, s: StageResult(True, ["all good"], [out]))
    r = CliRunner().invoke(app, ["run", "e46-coupe-body", "--stage", "fake"])
    assert r.exit_code == 0
    assert r.output.splitlines() == ["all good", str(out)]


def test_cli_stages_lists_validate() -> None:
    r = CliRunner().invoke(app, ["stages"])
    assert r.exit_code == 0 and "validate" in r.output.split()
