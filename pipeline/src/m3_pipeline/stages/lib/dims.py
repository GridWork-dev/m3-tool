"""Real-world numbers for a car, read from `data/generations/<generation>.yaml`.

The data files are the source of truth for dimensions, the driver eye point and the stock tires,
so the pipeline reads them instead of copying numbers. A missing file or key raises
`DimensionsError` naming the file and the key. Standard library and PyYAML only.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import yaml

_GENERATION = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# 225/45ZR18: section width in mm, aspect ratio in percent, rim diameter in inches. The `Z` and
# the spaces are optional, because sources write both "225/45R18" and "225/45 ZR 18".
_TIRE = re.compile(r"^(?P<width>\d{3})/(?P<aspect>\d{2})\s*Z?R\s*(?P<rim>\d{2})$")
_MM_PER_INCH = 25.4


class DimensionsError(ValueError):
    """A generation file is absent, malformed or lacks a value this module needs."""


@dataclass(frozen=True)
class Dimensions:
    length_mm: float
    width_mm: float
    height_mm: float
    wheelbase_mm: float
    track_front_mm: float
    track_rear_mm: float


def load_dimensions(repo_root: Path, generation: str, body: str) -> Dimensions:
    """The published exterior dimensions of one body of a generation."""
    path, doc = _load(repo_root, generation)
    bodies = _section(doc, ("dimensions",), path)
    where = ("dimensions", body)
    if body not in bodies:
        raise DimensionsError(f"{path}: no dimensions for body {body!r} (has {sorted(bodies)})")
    fields = _section(doc, where, path)
    return Dimensions(
        length_mm=_number(fields, (*where, "lengthMm"), path),
        width_mm=_number(fields, (*where, "widthMm"), path),
        height_mm=_number(fields, (*where, "heightMm"), path),
        wheelbase_mm=_number(fields, (*where, "wheelbaseMm"), path),
        track_front_mm=_number(fields, (*where, "trackFrontMm"), path),
        track_rear_mm=_number(fields, (*where, "trackRearMm"), path),
    )


def load_eye_point_m(repo_root: Path, generation: str) -> tuple[float, float, float]:
    """The driver eye point in meters. The file's frame is the asset contract's already (origin
    on the ground under mid-wheelbase, +Y up, nose toward -Z), so only the unit changes."""
    path, doc = _load(repo_root, generation)
    where = ("driverEyePoint",)
    fields = _section(doc, where, path)
    return (
        _number(fields, (*where, "xMm"), path) / 1000,
        _number(fields, (*where, "yMm"), path) / 1000,
        _number(fields, (*where, "zMm"), path) / 1000,
    )


def load_stock_tires(repo_root: Path, generation: str) -> dict[str, str]:
    """The stock tire code per axle, as `{"front": "225/45ZR18", "rear": "255/40ZR18"}`."""
    path, doc = _load(repo_root, generation)
    tires: dict[str, str] = {}
    for axle in ("front", "rear"):
        where = ("fitment", axle, "stock")
        tire = _section(doc, where, path).get("tire")
        if not isinstance(tire, str):
            raise DimensionsError(f"{path}: {'.'.join((*where, 'tire'))} is missing or not text")
        tires[axle] = tire
    return tires


def tire_radius_m(tire: str) -> float:
    """Rolling radius from a tire code: half the rim plus the sidewall.
    `225/45ZR18` gives (18 * 25.4 / 2 + 225 * 0.45) / 1000 = 0.32985 m."""
    width_mm, aspect_pct, rim_in = _parse_tire(tire)
    return (rim_in * _MM_PER_INCH / 2 + width_mm * aspect_pct / 100) / 1000


def tire_width_m(tire: str) -> float:
    """Section width in meters: `225/45ZR18` gives 0.225."""
    return _parse_tire(tire)[0] / 1000


def _parse_tire(tire: str) -> tuple[int, int, int]:
    match = _TIRE.match(tire)
    if match is None:
        raise ValueError(f"tire code {tire!r} is not like 225/45ZR18")
    return int(match["width"]), int(match["aspect"]), int(match["rim"])


def _load(repo_root: Path, generation: str) -> tuple[Path, dict[str, object]]:
    # The generation becomes a file name, so it must be an id and can't point out of data/.
    if not _GENERATION.match(generation):
        raise DimensionsError(f"generation {generation!r} is not a kebab-case id")
    path = repo_root / "data" / "generations" / f"{generation}.yaml"
    try:
        parsed: object = yaml.safe_load(path.read_text("utf-8"))
    except FileNotFoundError:
        raise DimensionsError(f"{path} does not exist") from None
    except (OSError, yaml.YAMLError) as error:
        raise DimensionsError(f"{path}: could not read: {error}") from error
    if not isinstance(parsed, dict):
        raise DimensionsError(f"{path}: expected a mapping at the top level")
    return path, cast("dict[str, object]", parsed)


def _section(doc: dict[str, object], keys: tuple[str, ...], path: Path) -> dict[str, object]:
    """The mapping at `keys`, walking down from the file's top level."""
    node = doc
    for depth, key in enumerate(keys):
        where = ".".join(keys[: depth + 1])
        if key not in node:
            raise DimensionsError(f"{path}: {where} is missing")
        child = node[key]
        if not isinstance(child, dict):
            raise DimensionsError(f"{path}: {where} is not a mapping")
        node = cast("dict[str, object]", child)
    return node


def _number(fields: dict[str, object], keys: tuple[str, ...], path: Path) -> float:
    value = fields.get(keys[-1])
    # bool is an int in Python, and a YAML `yes` would otherwise pass as 1 mm.
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise DimensionsError(f"{path}: {'.'.join(keys)} is missing or not a number")
    return float(value)
