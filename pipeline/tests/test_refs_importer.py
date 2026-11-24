from pathlib import Path

import pytest
from refs_helpers import make_image_bytes
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.refs.importer import import_directory
from m3_pipeline.refs.store import RefStore


def make_dir(tmp_path: Path, files: dict[str, bytes]) -> Path:
    directory = tmp_path / "in"
    directory.mkdir()
    for name, data in files.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return directory


def test_import_adds_files_with_unknown_license_by_default(store: RefStore, tmp_path: Path) -> None:
    d = make_dir(tmp_path, {"a.jpg": make_image_bytes(1)})
    rep = import_directory(store, d, subject="e46-coupe", source_note="my own search")
    r = store.records()[0]
    assert rep.added == 1
    assert (r.source_kind, r.license_short, r.source_note, r.source_url) == (
        "local",
        "unknown",
        "my own search",
        None,
    )


def test_import_license_flag_sets_license_short(store: RefStore, tmp_path: Path) -> None:
    d = make_dir(tmp_path, {"a.jpg": make_image_bytes(1)})
    import_directory(store, d, subject="e46-coupe", source_note="n", license_short="CC BY 4.0")
    r = store.records()[0]
    assert r.license_short == "CC BY 4.0" and r.license_url is None


def test_import_continues_past_bad_files_and_reports_them(store: RefStore, tmp_path: Path) -> None:
    d = make_dir(
        tmp_path,
        {
            "good.jpg": make_image_bytes(1),
            "page.jpg": b"<html>error</html>",
            "phone.heic": b"\x00\x00\x00\x18ftypheic" + b"\0" * 64,
            "anim.gif": make_image_bytes(2, fmt="GIF"),
            "notes.txt": b"x",
            ".DS_Store": b"x",
        },
    )
    rep = import_directory(store, d, subject="e46-coupe", source_note="n")
    why = {Path(p).name: r for p, r in rep.skipped}
    assert rep.added == 1 and set(why) == {"page.jpg", "phone.heic", "anim.gif"}
    assert "JPEG" in why["phone.heic"]


def test_import_takes_extension_from_content_not_filename(store: RefStore, tmp_path: Path) -> None:
    d = make_dir(tmp_path, {"x.jpg": make_image_bytes(1, fmt="WEBP")})
    import_directory(store, d, subject="e46-coupe", source_note="n")
    assert store.records()[0].ext == "webp"


def test_import_recurses_and_is_idempotent(store: RefStore, tmp_path: Path) -> None:
    d = make_dir(tmp_path, {"nested/a.jpg": make_image_bytes(1)})
    assert import_directory(store, d, subject="e46-coupe", source_note="n").added == 1
    rep = import_directory(store, d, subject="e46-coupe", source_note="n")
    assert rep.added == 0 and rep.known == 1
    assert len(list((store.work_dir / "refs/images").rglob("*.jpg"))) == 1


def test_import_leaves_the_source_files_untouched(store: RefStore, tmp_path: Path) -> None:
    d = make_dir(tmp_path, {"a.jpg": make_image_bytes(1), "bad.jpg": b"bad"})
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in d.iterdir()}
    import_directory(store, d, subject="e46-coupe", source_note="n")
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in d.iterdir()} == before


def test_import_cli_requires_source_note_and_a_valid_subject(
    store: RefStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = make_dir(tmp_path, {"a.jpg": make_image_bytes(1)})
    monkeypatch.setenv("M3_WORK_DIR", str(store.work_dir))
    runner = CliRunner()
    assert runner.invoke(app, ["refs", "import", str(d), "--subject", "e46-coupe"]).exit_code == 2
    result = runner.invoke(
        app, ["refs", "import", str(d), "--subject", "Bad Id", "--source-note", "n"]
    )
    assert result.exit_code == 2 and "Bad Id" in result.output
