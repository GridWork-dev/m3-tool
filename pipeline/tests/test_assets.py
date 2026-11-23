import re
from pathlib import Path
from typing import get_args

import pytest

from m3_pipeline.assets import AssetConfigError, AssetKind, AssetSpec, load_assets
from m3_pipeline.config import load_settings


def test_load_assets_parses_repo_file() -> None:
    assets = load_assets(load_settings({}).repo_root / "pipeline/assets.toml")
    assert assets["e46-coupe-body"] == AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")


def test_load_assets_accepts_a_body_module(tmp_path: Path) -> None:
    p = tmp_path / "a.toml"
    p.write_text('[e46-csl-trunk-lid]\nkind = "body-module"\ngeneration = "e46"\nsubject = "s"\n')
    assert load_assets(p) == {
        "e46-csl-trunk-lid": AssetSpec("e46-csl-trunk-lid", "body-module", "e46", "s")
    }


def test_asset_kinds_match_the_typescript_contract() -> None:
    # src/lib/asset-contract.ts is the source of truth; AssetKind is its Python copy.
    source = (load_settings({}).repo_root / "src/lib/asset-contract.ts").read_text()
    match = re.search(r"ASSET_KINDS\s*=\s*\[(.*?)\]\s*as const", source, re.DOTALL)
    assert match is not None
    assert re.findall(r"'([^']+)'", match.group(1)) == list(get_args(AssetKind))


def test_load_assets_rejects_unknown_kind(tmp_path: Path) -> None:
    p = tmp_path / "a.toml"
    p.write_text('[x]\nkind="car"\ngeneration="e46"\nsubject="s"\n')
    with pytest.raises(AssetConfigError, match="kind"):
        load_assets(p)


@pytest.mark.parametrize(
    "asset_id", ["E46-body", "e46_body", "e46--body", "-e46", "e46-", "e46 body", "..", "é46"]
)
def test_load_assets_rejects_ids_that_are_not_kebab_case(tmp_path: Path, asset_id: str) -> None:
    p = tmp_path / "a.toml"
    p.write_text(f'["{asset_id}"]\nkind="base-car"\ngeneration="e46"\nsubject="s"\n')
    with pytest.raises(AssetConfigError, match="kebab-case"):
        load_assets(p)


def test_load_assets_accepts_kebab_case_ids(tmp_path: Path) -> None:
    p = tmp_path / "a.toml"
    p.write_text('[e46-m3-2]\nkind="product"\ngeneration="e46"\nsubject="s"\n')
    assert list(load_assets(p)) == ["e46-m3-2"]
