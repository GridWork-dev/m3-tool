"""A hand-picked view set, for when `pipeline refs viewsets build` has no real one yet.

Delete this module once the photo lane's view sets exist. It writes the same
`<work_dir>/refs/viewsets/<subject>.json` the lane writes (photo-tooling Task 8), with the images
under `refs/images/` and masks under `refs/cutouts/`, so every consumer reads it through
`load_viewset` and can't tell the difference. The photos never enter the repo.

    python -m m3_pipeline.stages.lib.handmade <work_dir> <subject> <kind> <picks.toml>

`picks.toml` has one `[[pick]]` table per photo; see `load_picks` for the keys.
"""

import hashlib
import json
import os
import re
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from m3_pipeline.config import Settings, load_settings
from m3_pipeline.stages.lib.paths import (
    require_work_dir_outside_repo,
    require_write_target_outside_repo,
    subject_body,
)
from m3_pipeline.stages.lib.viewset_io import viewset_path

Kind = Literal["base-car", "interior"]

# These mirror the photo lane's constants (photo-tooling Task 8), which are not importable here.
EXTERIOR_VIEWS = ("front_34_left", "rear_34_right", "side_left", "front", "rear")
INTERIOR_COMPONENTS = (
    "interior_dash",
    "interior_gauges",
    "interior_steering",
    "interior_seats",
    "interior_door",
    "interior_console",
)
# Whole dashes and doors have a driver's side: an RHD picture is used mirrored and flagged, because
# its lettering then reads backwards. Steering, gauges, seats and the console are used as they are.
DRIVE_DEPENDENT = ("interior_dash", "interior_door")
DRIVE_SIDES = ("lhd", "rhd", "unknown")
SEATS = ("driver", "passenger", "both", "unknown")
MIN_VIEWS = 3  # fewer pictures than this and an interior component counts as missing
_EXTENSIONS = {".jpg": "jpg", ".jpeg": "jpg", ".png": "png", ".webp": "webp", ".avif": "avif"}
_PICK_KEYS = {
    "file", "view", "license_short", "license_url", "author", "page_url", "drive_side", "seat",
    "mask",
}  # fmt: skip
_REQUIRED_PICK_KEYS = ("file", "view", "license_short", "page_url")
# The photo lane's `is_cc_or_pd`: a field of the file it writes, not a check made here.
_CC_OR_PD = re.compile(r"^(CC0|CC BY(-SA)? \d|(Public domain|PD)\b|No restrictions)")


class HandmadeError(ValueError):
    """A picks file or a pick is not usable."""


@dataclass(frozen=True)
class Pick:
    file: Path
    view: str
    license_short: str
    license_url: str | None
    author: str | None
    page_url: str
    drive_side: str = "lhd"
    seat: str | None = None
    mask: Path | None = None


def load_picks(path: Path) -> list[Pick]:
    """Read the `[[pick]]` tables of a TOML file.

    Required keys: `file`, `view`, `license_short`, `page_url`. Optional: `license_url`, `author`,
    `drive_side` (`lhd` by default), `seat`, `mask`. `file` and `mask` may be relative to the TOML
    file. Order matters: the first pick of a view or component ranks first.
    """
    try:
        raw: object = tomllib.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        raise HandmadeError(f"{path} does not exist") from None
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise HandmadeError(f"{path}: could not read: {error}") from error
    tables = cast("dict[str, object]", raw).get("pick")
    if not isinstance(tables, list) or not tables:
        raise HandmadeError(f"{path}: needs at least one [[pick]] table")
    return [_parse_pick(table, path, i) for i, table in enumerate(cast("list[object]", tables))]


def build_handmade_viewset(work_dir: Path, subject: str, kind: Kind, picks: Sequence[Pick]) -> Path:
    """Copy the picked photos into `work_dir` and write `refs/viewsets/<subject>.json`.

    Images are stored by content hash (`refs/images/<sha[:2]>/<sha>.<ext>`) and masks as
    `refs/cutouts/<sha>.png`, so running this again with the same picks changes nothing, and two
    picks of identical bytes share one file. Everything is checked before anything is written,
    the real location of every destination included: no photo may land in the repo, even
    through a link inside `work_dir` (the repo root comes from `load_settings()`).
    Returns the view-set path. Raises HandmadeError for a pick that doesn't fit or a destination
    in the repo.
    """
    _check_subject(subject, kind)
    ordered = _check_picks(kind, picks)
    writes: dict[Path, bytes] = {}  # destination -> content, in write order (view set last)
    entries: list[dict[str, object]] = []
    for pick in ordered:
        data = pick.file.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        ext = _EXTENSIONS[pick.file.suffix.lower()]
        image_rel = f"refs/images/{sha[:2]}/{sha}.{ext}"
        writes[work_dir / image_rel] = data
        cutout_rel = None
        if pick.mask is not None:
            cutout_rel = f"refs/cutouts/{sha}.png"
            writes[work_dir / cutout_rel] = pick.mask.read_bytes()
        entries.append(_entry(pick, sha, image_rel, cutout_rel))

    if kind == "base-car":
        views, components = entries, {}
        missing = [v for v in EXTERIOR_VIEWS if v not in {e["view"] for e in entries}]
    else:
        views = []
        components = {
            name: [e for e in entries if e["view"] == name]
            for name in INTERIOR_COMPONENTS
            if any(e["view"] == name for e in entries)
        }
        missing = [n for n in INTERIOR_COMPONENTS if len(components.get(n, [])) < MIN_VIEWS]
    licenses = sorted({str(e["license_short"]) for e in entries})
    doc: dict[str, object] = {
        "subject": subject,
        "kind": kind,
        "views": views,
        "components": components,
        "missing": missing,
        "all_cc_or_pd": bool(entries) and all(_CC_OR_PD.match(name) for name in licenses),
        "licenses": licenses,
        "rejected": {},
    }
    dest = viewset_path(work_dir, subject)
    writes[dest] = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
    repo_root = load_settings().repo_root
    try:
        for path in writes:
            require_write_target_outside_repo(path, repo_root)
    except ValueError as error:
        raise HandmadeError(str(error)) from error
    for path, data in writes.items():
        _write_atomic(path, data)
    return dest


def main(argv: list[str]) -> int:
    """Command line: `<work_dir> <subject> <kind> <picks.toml>`. Exit 0 ok, 1 not ok, 2 usage."""
    if len(argv) != 4 or argv[2] not in ("base-car", "interior"):
        print(
            "usage: python -m m3_pipeline.stages.lib.handmade "
            "<work_dir> <subject> <base-car|interior> <picks.toml>",
            file=sys.stderr,
        )
        return 2
    work_dir, subject, kind, picks_path = argv
    try:
        settings = Settings(
            repo_root=load_settings().repo_root, work_dir=Path(work_dir).expanduser().resolve()
        )
        require_work_dir_outside_repo(settings)
        picks = load_picks(Path(picks_path).expanduser())
        dest = build_handmade_viewset(settings.work_dir, subject, cast("Kind", kind), picks)
    except (ValueError, OSError) as error:  # HandmadeError is a ValueError
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"wrote {dest}")
    for pick in picks:
        print(f"  {pick.view}: {pick.file.name} ({pick.license_short}, {pick.drive_side})")
    return 0


def _parse_pick(table: object, path: Path, index: int) -> Pick:
    where = f"pick[{index}]"
    if not isinstance(table, dict):
        raise HandmadeError(f"{path}: {where} is not a table")
    fields = cast("dict[str, object]", table)
    for key in _REQUIRED_PICK_KEYS:
        if key not in fields:
            raise HandmadeError(f"{path}: {where}.{key} is missing")
    # A misspelled optional key (`drive-side`) would silently fall back to its default.
    unknown = sorted(set(fields) - _PICK_KEYS)
    if unknown:
        raise HandmadeError(
            f"{path}: {where} has unknown keys {unknown}; known: {sorted(_PICK_KEYS)}"
        )

    def text(key: str) -> str | None:
        value = fields.get(key)
        if value is not None and not isinstance(value, str):
            raise HandmadeError(f"{path}: {where}.{key} is not a string")
        return value

    def required(key: str) -> str:
        value = text(key)
        if value is None:
            raise HandmadeError(f"{path}: {where}.{key} is missing")
        return value

    def located(value: str) -> Path:
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else path.parent / candidate

    mask = text("mask")
    return Pick(
        file=located(required("file")),
        view=required("view"),
        license_short=required("license_short"),
        license_url=text("license_url"),
        author=text("author"),
        page_url=required("page_url"),
        drive_side=text("drive_side") or "lhd",
        seat=text("seat"),
        mask=None if mask is None else located(mask),
    )


def _check_subject(subject: str, kind: Kind) -> None:
    try:
        subject_body(subject)
    except ValueError as error:
        raise HandmadeError(str(error)) from error
    if subject.endswith("-interior") != (kind == "interior"):
        raise HandmadeError(f"subject {subject!r} does not fit kind {kind!r}")


def _check_picks(kind: Kind, picks: Sequence[Pick]) -> list[Pick]:
    """Validate every pick and return them in file order: the lane's slot order for an exterior
    set, the picks' own order for an interior one."""
    valid_views = EXTERIOR_VIEWS if kind == "base-car" else INTERIOR_COMPONENTS
    seen: set[str] = set()
    for pick in picks:
        name = pick.file.name
        if pick.view not in valid_views:
            raise HandmadeError(f"{name}: view {pick.view!r} is not one of {list(valid_views)}")
        if kind == "base-car" and pick.view in seen:
            raise HandmadeError(f"{name}: view {pick.view!r} is picked twice")
        seen.add(pick.view)
        if pick.drive_side not in DRIVE_SIDES:
            raise HandmadeError(f"{name}: drive_side {pick.drive_side!r} is not in {DRIVE_SIDES}")
        if pick.view in DRIVE_DEPENDENT and pick.drive_side == "unknown":
            raise HandmadeError(f"{name}: a whole {pick.view} needs a known drive side")
        if pick.seat is not None and (pick.view != "interior_seats" or pick.seat not in SEATS):
            raise HandmadeError(
                f"{name}: seat {pick.seat!r} is only for interior_seats, as one of {SEATS}"
            )
        if not pick.file.is_file():
            raise HandmadeError(f"{pick.file} does not exist")
        if pick.file.suffix.lower() not in _EXTENSIONS:
            raise HandmadeError(
                f"{name}: extension {pick.file.suffix!r} is not one of {list(_EXTENSIONS)}"
            )
        if pick.mask is not None and (
            not pick.mask.is_file() or pick.mask.suffix.lower() != ".png"
        ):
            raise HandmadeError(f"{name}: mask {pick.mask} must be an existing .png file")
    if kind == "base-car":
        return sorted(picks, key=lambda p: EXTERIOR_VIEWS.index(p.view))
    return list(picks)


def _entry(pick: Pick, sha: str, image_rel: str, cutout_rel: str | None) -> dict[str, object]:
    flipped = pick.view in DRIVE_DEPENDENT and pick.drive_side == "rhd"
    return {
        "view": pick.view,
        "image_id": sha,
        "image_path": image_rel,
        "cutout_path": cutout_rel,
        "mirrored": flipped,
        "score": 0.0,
        "source_kind": "local",
        "license_short": pick.license_short,
        "license_url": pick.license_url,
        "author": pick.author,
        "page_url": pick.page_url,
        "drive_side": pick.drive_side,
        "seat": (pick.seat or "unknown") if pick.view == "interior_seats" else None,
        "contains_text_risk": flipped,
    }


def _write_atomic(dest: Path, data: bytes) -> None:
    """Write `data` to `dest` through a temp file in the same folder, so a crash never leaves
    half a file.

    The temp file is created exclusively (`mkstemp`: O_CREAT | O_EXCL, a name nobody planned), so
    it can never be an existing file or a link that a predictable `<dest>.tmp` could have been
    pointed at: the bytes only ever go where the destination check looked. It is flushed and
    fsynced before the rename, and removed again if anything fails. The file is created owner-only
    (0600), which suits a private cache.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.", suffix=".tmp")
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, dest)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
