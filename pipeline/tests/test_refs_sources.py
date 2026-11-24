from pathlib import Path

import pytest
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.config import load_settings
from m3_pipeline.refs.sources import DEFAULT_USER_AGENT, load_sources


def test_load_sources_reads_subjects_and_defaults(tmp_path: Path) -> None:
    p = tmp_path / "sources.toml"
    p.write_text('[subjects.e46-coupe]\ncommons_categories=["Test cars"]\nsearch_terms=["cars"]')
    s = load_sources(p, {})
    assert s.subjects["e46-coupe"].commons_categories == ("Test cars",)
    assert s.subjects["e46-coupe"].search_terms == ("cars",)
    assert s.commons.min_interval_s == 3.0
    assert (s.crawl.delay_s, s.crawl.max_pages, s.crawl.min_side_px) == (3.0, 25, 800)
    assert s.user_agent == DEFAULT_USER_AGENT


def test_commons_interval_below_one_second_is_floored(tmp_path: Path) -> None:
    p = tmp_path / "sources.toml"
    p.write_text("[commons]\nmin_interval_s=0.2")
    assert load_sources(p, {}).commons.min_interval_s == 1.0


def test_env_user_agent_overrides_toml(tmp_path: Path) -> None:
    p = tmp_path / "sources.toml"
    p.write_text('[http]\nuser_agent="configured"')
    assert load_sources(p, {}).user_agent == "configured"
    assert load_sources(p, {"M3_REFS_USER_AGENT": "override"}).user_agent == "override"


def test_shipped_sources_file_parses_and_holds_the_example_subjects() -> None:
    s = load_sources(load_settings({}).repo_root / "pipeline/refs-sources.toml", {})
    assert s.subjects["e46-coupe"].commons_categories
    assert s.subjects["e46-coupe-interior"].commons_categories
    assert s.subjects["e46-coupe-interior"].search_terms


def test_commons_cli_without_categories_or_terms_exits_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pipeline").mkdir()
    (tmp_path / "pipeline/refs-sources.toml").write_text("")
    monkeypatch.setenv("M3_REPO_ROOT", str(tmp_path))
    result = CliRunner().invoke(app, ["refs", "commons", "--subject", "e46-coupe"])
    assert result.exit_code == 2 and "pipeline/refs-sources.toml" in result.output
