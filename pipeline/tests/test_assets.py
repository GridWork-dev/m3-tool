from pathlib import Path

import pytest

from m3_pipeline.assets import AssetConfigError, AssetSpec, load_assets
from m3_pipeline.config import load_settings


def test_load_assets_parses_repo_file() -> None:
    assets = load_assets(load_settings({}).repo_root / "pipeline/assets.toml")
    assert assets["e46-coupe-body"] == AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")


def test_load_assets_rejects_unknown_kind(tmp_path: Path) -> None:
    p = tmp_path / "a.toml"
    p.write_text('[x]\nkind="car"\ngeneration="e46"\nsubject="s"\n')
    with pytest.raises(AssetConfigError, match="kind"):
        load_assets(p)
