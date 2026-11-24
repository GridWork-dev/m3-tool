"""Read a photo view set (`<work_dir>/refs/viewsets/<subject>.json`) into typed shapes.

The file is the photo lane's `ViewSet` as `model_dump_json` writes it (photo-tooling Task 8).
This module parses it by hand instead of importing `m3_pipeline.refs`, so the spike needs
nothing from that lane. Only the keys the spike uses are required, and extra keys are ignored,
so the lane may add fields. A missing or mistyped key raises `ViewSetError` naming the file and
the key.

Every entry keeps its license, author and page URL, for provenance. Nothing here checks them.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast


class ViewSetError(ValueError):
    """The view-set file is missing, unreadable or not the shape the photo lane writes."""


@dataclass(frozen=True)
class ViewRef:
    """One picture of a view set. Paths are absolute, under the work dir.

    `mirrored` entries are flipped horizontally by the consumer, and `contains_text_risk` marks a
    mirrored picture whose lettering now reads backwards.
    """

    view: str
    image_id: str
    image_path: Path
    cutout_path: Path | None
    mirrored: bool
    license_short: str
    license_url: str | None
    author: str | None
    page_url: str | None
    drive_side: str
    seat: str | None
    contains_text_risk: bool


@dataclass(frozen=True)
class SpikeViewSet:
    """An exterior set has `views` (one per slot) and no components; an interior set is the
    opposite, one tuple of pictures per component (`interior_dash`, ...)."""

    subject: str
    kind: str
    views: tuple[ViewRef, ...]
    components: dict[str, tuple[ViewRef, ...]]

    def entries(self) -> list[ViewRef]:
        """The views, then every component's pictures, in file order."""
        return [*self.views, *(ref for refs in self.components.values() for ref in refs)]


def viewset_path(work_dir: Path, subject: str) -> Path:
    return work_dir / "refs" / "viewsets" / f"{subject}.json"


def load_viewset(work_dir: Path, subject: str) -> SpikeViewSet:
    """Read and validate `<work_dir>/refs/viewsets/<subject>.json`.

    Raises ViewSetError when the file is absent, is not JSON, is for another subject, lacks a
    key, or names an image or cutout outside `work_dir`.
    """
    path = viewset_path(work_dir, subject)
    try:
        text = path.read_text("utf-8")
    except FileNotFoundError:
        raise ViewSetError(
            f"{path} does not exist; build the view set first (`pipeline refs viewsets build "
            f"--subject {subject}`, or the handmade fallback)"
        ) from None
    except OSError as error:
        raise ViewSetError(f"{path}: could not read: {error}") from error
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError as error:
        raise ViewSetError(f"{path}: not valid JSON: {error}") from error
    doc = _mapping(parsed, path, "the file")
    found = _str(doc, "subject", path, "")
    if found != subject:
        raise ViewSetError(f"{path}: is the view set of {found!r}, not {subject!r}")
    views = tuple(
        _ref(entry, path, work_dir, f"views[{i}]")
        for i, entry in enumerate(_list(doc, "views", path, ""))
    )
    components_raw = _mapping(_get(doc, "components", path, ""), path, "components")
    components = {
        name: tuple(
            _ref(entry, path, work_dir, f"components.{name}[{i}]")
            for i, entry in enumerate(_list(components_raw, name, path, "components"))
        )
        for name in components_raw
    }
    return SpikeViewSet(subject, _str(doc, "kind", path, ""), views, components)


def _ref(entry: object, path: Path, work_dir: Path, where: str) -> ViewRef:
    fields = _mapping(entry, path, where)
    cutout = _opt_str(fields, "cutout_path", path, where)
    return ViewRef(
        view=_str(fields, "view", path, where),
        image_id=_str(fields, "image_id", path, where),
        image_path=_under(
            work_dir, _str(fields, "image_path", path, where), path, where, "image_path"
        ),
        cutout_path=None
        if cutout is None
        else _under(work_dir, cutout, path, where, "cutout_path"),
        mirrored=_bool(fields, "mirrored", path, where),
        license_short=_str(fields, "license_short", path, where),
        license_url=_opt_str(fields, "license_url", path, where),
        author=_opt_str(fields, "author", path, where),
        page_url=_opt_str(fields, "page_url", path, where),
        drive_side=_str(fields, "drive_side", path, where),
        seat=_opt_str(fields, "seat", path, where),
        contains_text_risk=_bool(fields, "contains_text_risk", path, where),
    )


def _under(work_dir: Path, relative: str, path: Path, where: str, key: str) -> Path:
    """`work_dir / relative`, refusing an absolute path or any `..` (a file must not point out)."""
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or not relative:
        raise ViewSetError(f"{path}: {where}.{key} {relative!r} is not a path under the work dir")
    return work_dir / relative


def _key(where: str, key: str) -> str:
    return f"{where}.{key}" if where else key


def _get(fields: Mapping[str, object], key: str, path: Path, where: str) -> object:
    if key not in fields:
        raise ViewSetError(f"{path}: {_key(where, key)} is missing")
    return fields[key]


def _mapping(value: object, path: Path, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ViewSetError(f"{path}: {where} is not an object")
    return cast("dict[str, object]", value)


def _list(fields: Mapping[str, object], key: str, path: Path, where: str) -> list[object]:
    value = _get(fields, key, path, where)
    if not isinstance(value, list):
        raise ViewSetError(f"{path}: {_key(where, key)} is not a list")
    return cast("list[object]", value)


def _str(fields: Mapping[str, object], key: str, path: Path, where: str) -> str:
    value = _get(fields, key, path, where)
    if not isinstance(value, str):
        raise ViewSetError(f"{path}: {_key(where, key)} is not a string")
    return value


def _opt_str(fields: Mapping[str, object], key: str, path: Path, where: str) -> str | None:
    """A key that must be present but may be null."""
    value = _get(fields, key, path, where)
    if value is not None and not isinstance(value, str):
        raise ViewSetError(f"{path}: {_key(where, key)} is not a string or null")
    return value


def _bool(fields: Mapping[str, object], key: str, path: Path, where: str) -> bool:
    value = _get(fields, key, path, where)
    if not isinstance(value, bool):
        raise ViewSetError(f"{path}: {_key(where, key)} is not true or false")
    return value
