import json
from pathlib import Path
from typing import Any, get_args

import pytest
from refs_helpers import ingest, make_image_bytes, make_labels, write_jsonl
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.refs.classify import (
    LabelImportError,
    export_batches,
    import_labels,
    render_classify_md,
)
from m3_pipeline.refs.models import ImageRecord, View
from m3_pipeline.refs.store import RefStore


def good(rec: ImageRecord) -> dict[str, Any]:
    return {"id": rec.id, **make_labels().model_dump()}


def test_export_writes_batches_of_forty_and_a_classify_md(store: RefStore) -> None:
    for i in range(85):
        ingest(store, make_image_bytes(i))
    r = export_batches(store, "e46-coupe")
    batches = [json.loads(p.read_text()) for p in r.batches]
    assert [len(b["images"]) for b in batches] == [40, 40, 5]
    assert r.images == 85 and (r.directory / "CLASSIFY.md").exists()
    assert all(
        Path(i["path"]).is_absolute() and Path(i["path"]).exists()
        for b in batches
        for i in b["images"]
    )


def test_classify_md_embeds_every_enum_value_and_the_output_file_name() -> None:
    md = render_classify_md("e46-coupe")
    assert all(v in md for v in get_args(View))
    assert all(
        w in md
        for w in (
            "labels-001.jsonl",
            "unknown",
            "quality",
            "drive_side",
            "lhd",
            "rhd",
            "seat",
            "driver",
            "passenger",
            "trim",
            "csl",
            "ducktail",
        )
    )


def test_export_skips_duplicates_and_already_labeled(store: RefStore) -> None:
    a, b, c = [ingest(store, make_image_bytes(i)) for i in range(3)]
    store.update(
        [
            a,
            b.model_copy(update={"status": "duplicate"}),
            c.model_copy(update={"status": "labeled", "labels": make_labels()}),
        ]
    )
    result = export_batches(store, "e46-coupe")
    assert result.images == 1
    assert json.loads(result.batches[0].read_text())["images"][0]["id"] == a.id


def test_export_clears_stale_batch_files(store: RefStore) -> None:
    a, b = [ingest(store, make_image_bytes(i)) for i in range(2)]
    first = export_batches(store, "e46-coupe", batch_size=1)
    store.update([a, b.model_copy(update={"status": "labeled", "labels": make_labels()})])
    second = export_batches(store, "e46-coupe", batch_size=1)
    assert second.images == 1
    assert sorted(p.name for p in first.directory.glob("batch-*.json")) == ["batch-001.json"]


def test_import_marks_labeled_and_stores_labels(store: RefStore, tmp_path: Path) -> None:
    rec = ingest(store, make_image_bytes(1))
    res = import_labels(store, write_jsonl(tmp_path, [good(rec)]))
    saved = store.get(rec.id)
    assert res.labeled == 1 and saved is not None and saved.status == "labeled"
    assert saved.labels is not None and saved.labels.view == "front_34_left"


def test_import_is_all_or_nothing_and_reports_every_bad_line(
    store: RefStore, tmp_path: Path
) -> None:
    rec = ingest(store, make_image_bytes(1))
    g = good(rec)
    f = write_jsonl(
        tmp_path, [g, {**g, "id": "f" * 64}, {**g, "view": "side"}, {**g, "quality": 6}]
    )
    with pytest.raises(LabelImportError) as e:
        import_labels(store, f)
    assert len(e.value.errors) == 3 and e.value.errors[0].startswith("line 2")
    assert store.get(rec.id) == rec


def test_import_rejects_duplicate_ids_invalid_json_and_extra_fields(
    store: RefStore,
    tmp_path: Path,
) -> None:
    rec = ingest(store, make_image_bytes(1))
    f = write_jsonl(tmp_path, [good(rec), good(rec), {**good(rec), "extra": True}])
    with f.open("a") as out:
        out.write("{broken\n")
    with pytest.raises(LabelImportError) as e:
        import_labels(store, f)
    assert len(e.value.errors) == 3
    assert [s.split(":")[0] for s in e.value.errors] == ["line 2", "line 3", "line 4"]
    assert store.get(rec.id) == rec


@pytest.mark.parametrize("field,value", [("drive_side", "left"), ("trim", "gt")])
def test_import_rejects_an_unknown_drive_side_or_trim_value(
    store: RefStore,
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    rec = ingest(store, make_image_bytes(1))
    with pytest.raises(LabelImportError):
        import_labels(store, write_jsonl(tmp_path, [{**good(rec), field: value}]))
    assert store.get(rec.id) == rec


def test_relabeling_overwrites_and_counts_it(store: RefStore, tmp_path: Path) -> None:
    rec = ingest(store, make_image_bytes(1))
    import_labels(store, write_jsonl(tmp_path, [good(rec)]))
    res = import_labels(store, write_jsonl(tmp_path, [{**good(rec), "view": "rear"}]))
    saved = store.get(rec.id)
    assert res.labeled == 0 and res.relabeled == 1
    assert saved is not None and saved.labels is not None and saved.labels.view == "rear"


def test_labeling_a_duplicate_keeps_its_duplicate_status(store: RefStore, tmp_path: Path) -> None:
    rec = ingest(store, make_image_bytes(1)).model_copy(
        update={"status": "duplicate", "duplicate_of": "f" * 64}
    )
    store.update([rec])
    import_labels(store, write_jsonl(tmp_path, [good(rec)]))
    saved = store.get(rec.id)
    assert saved is not None and saved.status == "duplicate"
    assert saved.duplicate_of == "f" * 64 and saved.labels == make_labels()


def test_classify_cli_roundtrip(
    store: RefStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for i in range(2):
        ingest(store, make_image_bytes(i))
    monkeypatch.setenv("M3_WORK_DIR", str(store.work_dir))
    runner = CliRunner()
    result = runner.invoke(app, ["refs", "classify", "export", "--subject", "e46-coupe"])
    assert result.exit_code == 0, result.output
    batch = json.loads((store.work_dir / "refs/classify/e46-coupe/batch-001.json").read_text())
    path = write_jsonl(
        tmp_path, [{"id": r["id"], **make_labels().model_dump()} for r in batch["images"]]
    )
    result = runner.invoke(app, ["refs", "classify", "import", str(path)])
    assert result.exit_code == 0 and "labeled=2" in result.output
