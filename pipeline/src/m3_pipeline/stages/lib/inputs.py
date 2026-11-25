"""Prepare privacy-reviewed copies in upright, unmirrored pixel coordinates.

EXIF orientation is applied before both proposal and masking. Boxes always describe this
upright image; optional view-set mirroring happens only after masking. Legacy plain-list
cache entries remain valid for originals without EXIF rotation/reflection. Other originals
need an explicit ``{"coordinate_space": "upright-v1", "boxes": [...]}`` cache entry after
human re-review, so old raw-coordinate reviews never silently migrate.
"""

import json
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast
from urllib.parse import urlsplit

from m3_pipeline.stages.lib.codex import run_codex
from m3_pipeline.stages.lib.paths import require_outside_repo, require_write_target_outside_repo
from m3_pipeline.stages.lib.viewset_io import ViewRef

_REPO = Path(__file__).resolve().parents[5]
_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


@dataclass(frozen=True)
class Box:
    x: int
    y: int
    w: int
    h: int
    kind: Literal["person", "plate"]

    def __post_init__(self) -> None:
        if any(type(n) is not int for n in (self.x, self.y, self.w, self.h)):
            raise ValueError("redaction coordinates must be integers")
        if self.x < 0 or self.y < 0 or self.w <= 0 or self.h <= 0:
            raise ValueError("redaction boxes need nonnegative origins and positive sizes")
        if self.kind not in ("person", "plate"):
            raise ValueError("redaction kind must be person or plate")


@dataclass(frozen=True)
class Prepared:
    image_id: str
    path: Path
    mirrored: bool
    redactions: int


class InputsNotReviewed(ValueError):
    """An input has not received human privacy review."""


def _boxes(raw: object) -> list[Box]:
    if not isinstance(raw, list):
        raise ValueError("redactions must be a JSON array of boxes")
    result: list[Box] = []
    for item in cast(list[object], raw):
        if not isinstance(item, dict):
            raise ValueError("each redaction must be an object")
        fields = cast(dict[str, object], item)
        if set(fields) != {"x", "y", "w", "h", "kind"}:
            raise ValueError("each redaction needs x, y, w, h and kind")
        coords = [fields[key] for key in ("x", "y", "w", "h")]
        if any(type(value) is not int for value in coords):
            raise ValueError("redaction coordinates must be integers")
        kind = fields["kind"]
        if kind not in ("person", "plate"):
            raise ValueError("redaction kind must be person or plate")
        x, y, w, h = cast(list[int], coords)
        result.append(Box(x, y, w, h, kind))
    return result


def propose_redactions(ref: ViewRef, work_dir: Path, *, cwd: Path) -> list[Box]:
    url = urlsplit(ref.page_url or "")
    if url.scheme not in ("https", "http") or url.hostname != "commons.wikimedia.org":
        raise ValueError(f"{ref.image_id}: non-Commons photos require hand-written redactions")
    image = ref.image_path.resolve()
    if not image.is_relative_to(work_dir.resolve()):
        raise ValueError(f"{ref.image_id}: original is outside work_dir")
    require_outside_repo(repo_root=_REPO, path=image)
    if not cwd.resolve().is_relative_to(work_dir.resolve()):
        raise ValueError(f"{ref.image_id}: proposal cwd is outside work_dir")
    require_outside_repo(repo_root=_REPO, path=cwd)
    last = cwd / "redaction-proposal.json"
    if not last.resolve().is_relative_to(work_dir.resolve()):
        raise ValueError(f"{ref.image_id}: proposal output is outside work_dir")
    require_write_target_outside_repo(dest=last, repo_root=_REPO)
    cwd.mkdir(parents=True, exist_ok=True)
    # Vision clients may interpret EXIF differently. Attach the exact upright pixel space
    # that prepare_image masks, with no orientation metadata left for a client to reinterpret.
    from PIL import Image, ImageOps

    proposal = cwd / f"{ref.image_id}-upright.png"
    if not _ID.fullmatch(ref.image_id):
        raise ValueError("unsafe image_id")
    if not proposal.resolve().is_relative_to(work_dir.resolve()):
        raise ValueError(f"{ref.image_id}: proposal image is outside work_dir")
    require_write_target_outside_repo(dest=proposal, repo_root=_REPO)
    if proposal.resolve() == image:
        raise ValueError("proposal output must not overwrite its original")
    with Image.open(image) as original:
        upright = ImageOps.exif_transpose(original).convert("RGB")
        clean = Image.new("RGB", upright.size)
        clean.paste(upright)
        clean.save(proposal, format="PNG")
    prompt = (
        "Locate every person and number plate in this original photograph. Return only a JSON "
        'array of pixel boxes {"x":int,"y":int,"w":int,"h":int,"kind":"person"|"plate"}. '
        "Use the attached upright, unmirrored pixel coordinates. "
        "Return [] only when neither is present."
    )
    return _boxes(
        json.loads(
            run_codex(
                prompt,
                [proposal.resolve()],
                cwd=cwd.resolve(),
                last_message=last.resolve(),
                sandbox="read-only",
            )
        )
    )


def prepare_image(ref: ViewRef, work_dir: Path, out_dir: Path, boxes: Sequence[Box]) -> Prepared:
    from PIL import Image, ImageDraw, ImageOps

    if not _ID.fullmatch(ref.image_id):
        raise ValueError("unsafe image_id")
    source = ref.image_path.resolve()
    if not source.is_relative_to(work_dir.resolve()):
        raise ValueError(f"{ref.image_id}: original is outside work_dir")
    dest = out_dir / f"{ref.image_id}.png"
    require_outside_repo(repo_root=_REPO, path=source)
    if not dest.resolve().is_relative_to(work_dir.resolve()):
        raise ValueError(f"{ref.image_id}: prepared output is outside work_dir")
    require_write_target_outside_repo(dest=dest, repo_root=_REPO)
    if dest.resolve() == source:
        raise ValueError("prepared output must not overwrite its original")
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert("RGB")
    draw = ImageDraw.Draw(image)
    for box in boxes:
        if box.x + box.w > image.width or box.y + box.h > image.height:
            raise ValueError(f"{ref.image_id}: redaction box outside image")
        draw.rectangle((box.x, box.y, box.x + box.w - 1, box.y + box.h - 1), fill=(128, 128, 128))
    if ref.mirrored:
        image = ImageOps.mirror(image)
    image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    # A fresh image drops EXIF and all other metadata inherited by Pillow conversions.
    clean = Image.new("RGB", image.size)
    clean.paste(image)
    out_dir.mkdir(parents=True, exist_ok=True)
    clean.save(dest, format="PNG")
    return Prepared(ref.image_id, dest.resolve(), ref.mirrored, len(boxes))


def ensure_reviewed(prepared: Sequence[Prepared], reviewed_ids: Collection[str]) -> None:
    missing = sorted({item.image_id for item in prepared} - set(reviewed_ids))
    if missing:
        raise InputsNotReviewed("inputs need privacy review: " + ", ".join(missing))


def load_redactions(path: Path) -> dict[str, list[Box]]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text("utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("redaction cache must map image ids to boxes")
    result: dict[str, list[Box]] = {}
    for key, value in cast(dict[str, object], raw).items():
        if isinstance(value, dict):
            envelope = cast(dict[str, object], value)
            if (
                set(envelope) != {"coordinate_space", "boxes"}
                or envelope["coordinate_space"] != "upright-v1"
            ):
                raise ValueError(f"{key}: invalid upright redaction envelope")
            value = envelope["boxes"]
        result[key] = _boxes(value)
    return result


def validate_redaction_orientation(ref: ViewRef, cache_path: Path) -> None:
    """Require explicit re-review of legacy boxes when EXIF changes the pixel frame."""
    from PIL import Image

    with Image.open(ref.image_path) as original:
        orientation = original.getexif().get(274, 1)
    if orientation in (None, 1):
        return
    raw: object = json.loads(cache_path.read_text("utf-8"))
    if isinstance(raw, dict):
        entry = cast(dict[str, object], raw).get(ref.image_id)
        if isinstance(entry, dict):
            fields = cast(dict[str, object], entry)
            if fields.get("coordinate_space") == "upright-v1":
                _boxes(fields.get("boxes"))
                return
    raise InputsNotReviewed(
        f"{ref.image_id}: EXIF orientation {orientation} needs privacy re-review on the upright "
        'proposal image; set its cache entry to {"coordinate_space":"upright-v1","boxes":[...]} '
        "only after reviewing those upright coordinates"
    )


def save_redactions(
    path: Path, boxes: Mapping[str, Sequence[Box]], *, upright_ids: Collection[str] = ()
) -> None:
    require_write_target_outside_repo(dest=path, repo_root=_REPO)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Preserve explicit upright review markers when another image's proposal updates the cache.
    previous: dict[str, object] = {}
    if path.exists():
        raw: object = json.loads(path.read_text("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("redaction cache must map image ids to boxes")
        previous = cast(dict[str, object], raw)
    body: dict[str, object] = {}
    for key, value in boxes.items():
        encoded = [asdict(b) for b in value]
        old = previous.get(key)
        if key in upright_ids or (
            isinstance(old, dict)
            and cast(dict[str, object], old).get("coordinate_space") == "upright-v1"
        ):
            body[key] = {"coordinate_space": "upright-v1", "boxes": encoded}
        else:
            body[key] = encoded
    path.write_text(
        json.dumps(body, indent=2) + "\n",
        "utf-8",
    )
