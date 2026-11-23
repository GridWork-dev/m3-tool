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


def test_cli_stages_lists_validate() -> None:
    r = CliRunner().invoke(app, ["stages"])
    assert r.exit_code == 0 and "validate" in r.output.split()
