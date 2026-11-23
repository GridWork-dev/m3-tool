import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast, get_args

AssetKind = Literal["base-car", "interior", "product"]

# Asset ids are kebab-case, like every id in the data files. They also become directory names
# under the work dir, so this keeps a hand-edited assets.toml from naming a path like `..`.
ID_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


@dataclass(frozen=True)
class AssetSpec:
    id: str
    kind: AssetKind
    generation: str
    subject: str


class AssetConfigError(ValueError):
    pass


def load_assets(path: Path) -> dict[str, AssetSpec]:
    with path.open("rb") as f:
        data = tomllib.load(f)
    return {asset_id: _parse(asset_id, table) for asset_id, table in data.items()}


def _parse(asset_id: str, table: object) -> AssetSpec:
    if not ID_PATTERN.fullmatch(asset_id):
        raise AssetConfigError(
            f"asset id {asset_id!r} must be kebab-case: lowercase letters and digits "
            "joined by single hyphens"
        )
    if not isinstance(table, dict):
        raise AssetConfigError(f"asset {asset_id!r}: expected a table")
    fields = cast("dict[str, object]", table)
    values: dict[str, str] = {}
    for key in ("kind", "generation", "subject"):
        value = fields.get(key)
        if not isinstance(value, str):
            raise AssetConfigError(f"asset {asset_id!r}: {key} must be a string")
        values[key] = value
    kinds = get_args(AssetKind)
    if values["kind"] not in kinds:
        raise AssetConfigError(
            f"asset {asset_id!r}: unknown kind {values['kind']!r}; known: {', '.join(kinds)}"
        )
    return AssetSpec(
        asset_id,
        cast("AssetKind", values["kind"]),
        values["generation"],
        values["subject"],
    )
