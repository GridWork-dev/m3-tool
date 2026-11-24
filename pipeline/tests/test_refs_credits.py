from pathlib import Path

import pytest
from refs_helpers import ingest, make_image_bytes, make_labels, make_record
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.refs.credits import render_credits
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.viewsets import ViewSet, build_viewset


def test_credits_list_commons_entries_once_with_author_license_and_urls() -> None:
    record = make_record(
        source_kind="commons",
        author="Jane",
        license_short="CC BY-SA 4.0",
        license_url="https://cc/by-sa",
        page_url="https://commons/File:x",
        labels=make_labels(view="front"),
    )
    vs = build_viewset("e46-coupe", [record])
    vs = vs.model_copy(
        update={"views": [*vs.views, vs.views[0].model_copy(update={"mirrored": True})]}
    )
    text = render_credits(vs)
    assert text.count("Jane") == 1
    assert all(s in text for s in ("CC BY-SA 4.0", "https://cc/by-sa", "https://commons/File:x"))


def test_credits_mark_unknown_author_and_count_non_commons_images() -> None:
    vs = build_viewset(
        "e46-coupe",
        [
            make_record(source_kind="commons", labels=make_labels(view="front")),
            make_record(id="b" * 64, labels=make_labels(view="rear")),
        ],
    )
    text = render_credits(vs)
    assert "Author unknown" in text and "no license URL" in text
    assert text.endswith("Not credited: 1 non-Commons images in this set.\n")


def test_viewsets_build_cli_writes_json_and_credits_cli_reads_it(
    store: RefStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("M3_WORK_DIR", str(store.work_dir))
    runner = CliRunner()
    missing = runner.invoke(app, ["refs", "credits", "--subject", "e46-coupe"])
    assert missing.exit_code == 1 and "viewsets build" in missing.output
    record = ingest(store, make_image_bytes(1), kind="commons", author="Jane")
    store.update([record.model_copy(update={"labels": make_labels(), "status": "labeled"})])
    result = runner.invoke(app, ["refs", "viewsets", "build", "--subject", "e46-coupe"])
    assert result.exit_code == 0, result.output
    path: Path = store.work_dir / "refs/viewsets/e46-coupe.json"
    assert ViewSet.model_validate_json(path.read_text()).views[0].image_id == record.id
    result = runner.invoke(app, ["refs", "credits", "--subject", "e46-coupe"])
    assert result.exit_code == 0 and "Jane" in result.output
