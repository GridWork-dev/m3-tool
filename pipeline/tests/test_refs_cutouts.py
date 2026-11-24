import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image
from refs_helpers import ingest, make_image_bytes, make_labels

from m3_pipeline.refs.cutouts import (
    BackgroundRemovalUnavailable,
    cutout_relpath,
    load_remover,
    make_cutouts,
)
from m3_pipeline.refs.store import RefStore


def test_make_cutouts_writes_rgba_png_for_accepted_images_only(store: RefStore) -> None:
    a, b = [ingest(store, make_image_bytes(i)) for i in range(2)]
    store.update(
        [
            a.model_copy(update={"labels": make_labels(), "status": "labeled"}),
            b.model_copy(update={"labels": make_labels(stock=False), "status": "labeled"}),
        ]
    )
    report = make_cutouts(store, "e46-coupe", lambda im: im.convert("RGBA"))
    assert (report.created, report.existing, report.failed) == (1, 0, 0)
    with Image.open(store.work_dir / cutout_relpath(a.id)) as image:
        assert image.mode == "RGBA" and image.format == "PNG"
    assert not (store.work_dir / cutout_relpath(b.id)).exists()


def test_make_cutouts_skips_existing_and_survives_a_failing_remover(store: RefStore) -> None:
    records = [ingest(store, make_image_bytes(i)) for i in range(3)]
    store.update(
        [r.model_copy(update={"labels": make_labels(), "status": "labeled"}) for r in records]
    )
    existing = store.work_dir / cutout_relpath(records[0].id)
    existing.parent.mkdir(parents=True)
    Image.new("RGBA", (2, 2)).save(existing)
    calls = 0

    def remove(image: Image.Image) -> Image.Image:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("failed")
        return image.convert("RGBA")

    report = make_cutouts(store, "e46-coupe", remove)
    assert (report.created, report.existing, report.failed) == (1, 1, 1)
    assert len(list(existing.parent.glob("*.png"))) == 2


def test_missing_rembg_gives_actionable_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setitem(sys.modules, "rembg", None)
    with pytest.raises(BackgroundRemovalUnavailable, match="uv sync --group bg"):
        load_remover(models_dir=tmp_path)


def test_importing_the_cli_does_not_import_rembg() -> None:
    out = subprocess.run(
        [sys.executable, "-c", "import sys, m3_pipeline.cli; print('rembg' in sys.modules)"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0 and out.stdout.strip() == "False"
