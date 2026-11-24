import json
import random
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from m3_pipeline.refs.models import ImageRecord, Labels, Source
from m3_pipeline.refs.store import RefStore


def make_image_bytes(
    seed: int = 0,
    size: tuple[int, int] = (1000, 800),
    fmt: str = "JPEG",
    exif_orientation: int | None = None,
) -> bytes:
    rng = random.Random(seed)
    image = Image.new("RGB", size, (240, 240, 240))
    draw = ImageDraw.Draw(image)
    for _ in range(80):
        x, y = rng.randrange(size[0]), rng.randrange(size[1])
        w, h = rng.randrange(1, size[0] // 3), rng.randrange(1, size[1] // 3)
        color = tuple(rng.randrange(256) for _ in range(3))
        draw.rectangle((x, y, x + w, y + h), fill=color)
    out = BytesIO()
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        image.save(out, format=fmt, exif=exif)
    else:
        image.save(out, format=fmt)
    return out.getvalue()


def resize_bytes(data: bytes, size: tuple[int, int]) -> bytes:
    out = BytesIO()
    with Image.open(BytesIO(data)) as image:
        image.resize(size).save(out, format="JPEG")
    return out.getvalue()


def make_record(**overrides: Any) -> ImageRecord:
    values: dict[str, Any] = {
        "id": "a" * 64,
        "subject": "e46-coupe",
        "source_kind": "local",
        "source_url": None,
        "page_url": None,
        "author": None,
        "retrieved_at": datetime(2026, 11, 23, tzinfo=UTC),
        "width": 1000,
        "height": 800,
        "ext": "jpg",
        "phash": "0123456789abcdef",
    }
    return ImageRecord.model_validate(values | overrides)


def make_labels(**overrides: Any) -> Labels:
    values: dict[str, Any] = {
        "generation": "e46",
        "body": "coupe",
        "market": "us",
        "stock": True,
        "view": "front_34_left",
        "drive_side": "lhd",
        "trim": "standard",
        "occlusion": "none",
        "quality": 4,
    }
    return Labels.model_validate(values | overrides)


def ingest(
    store: RefStore, data: bytes, subject: str = "e46-coupe", **source_kw: Any
) -> ImageRecord:
    values: dict[str, Any] = {
        "kind": "local",
        "source_url": None,
        "page_url": None,
        "author": None,
    }
    result = store.ingest_bytes(data, subject=subject, source=Source(**(values | source_kw)))
    assert result.record is not None, result.reason
    return result.record


def write_jsonl(directory: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "labels.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


class FakeClock:
    def __init__(self) -> None:
        self.slept: list[float] = []
        self._now = 0.0

    def now(self) -> float:
        return self._now

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self._now += s
