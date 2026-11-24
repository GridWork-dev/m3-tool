# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from m3_pipeline.refs.filters import FilterTarget, evaluate
from m3_pipeline.refs.store import RefStore

if TYPE_CHECKING:
    from PIL import Image

# Quoted forward references keep the alias PIL-free at import time, matching
# imaging.py's lazy Pillow import.
Remover = Callable[["Image.Image"], "Image.Image"]
logger = logging.getLogger(__name__)


class BackgroundRemovalUnavailable(RuntimeError):
    pass


def load_remover(model: str = "birefnet-general", *, models_dir: Path) -> Remover:
    os.environ.setdefault("U2NET_HOME", str(models_dir))
    try:
        rembg = importlib.import_module("rembg")
    except ImportError:
        raise BackgroundRemovalUnavailable(
            "rembg is not installed; run `uv sync --group bg`"
        ) from None
    session = rembg.new_session(model)
    return lambda im: cast("Image.Image", rembg.remove(im, session=session))


def cutout_relpath(image_id: str) -> str:
    return f"refs/cutouts/{image_id}.png"


@dataclass(frozen=True)
class CutoutReport:
    created: int
    existing: int
    failed: int


def make_cutouts(store: RefStore, subject: str, remover: Remover) -> CutoutReport:
    from PIL import Image, ImageOps

    target = FilterTarget.from_subject(subject)
    created = existing = failed = 0
    for record in store.records(subject):
        if not evaluate(record, target).accepted:
            continue
        path = store.work_dir / cutout_relpath(record.id)
        if path.exists():
            existing += 1
            continue
        try:
            with Image.open(store.image_path(record)) as image:
                result = remover(ImageOps.exif_transpose(image)).convert("RGBA")
                path.parent.mkdir(parents=True, exist_ok=True)
                result.save(path, format="PNG")
            created += 1
        except Exception:
            path.unlink(missing_ok=True)
            logger.exception("cutout failed for %s", record.id)
            failed += 1
    return CutoutReport(created, existing, failed)
