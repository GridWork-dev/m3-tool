from pathlib import Path

import pytest
from refs_helpers import make_record

from m3_pipeline.refs.manifest import Manifest, ManifestError


def test_torn_last_manifest_line_is_dropped_and_manifest_stays_appendable(tmp_path: Path) -> None:
    p = tmp_path / "m.jsonl"
    r1, r2 = make_record(id="a" * 64), make_record(id="b" * 64)
    p.write_text(r1.model_dump_json() + "\n" + r2.model_dump_json()[:40])
    m = Manifest.load(p)
    assert [r.id for r in m.records()] == [r1.id]
    m.append(r2)
    assert [r.id for r in Manifest.load(p).records()] == [r1.id, r2.id]


def test_corrupt_middle_manifest_line_raises_with_line_number(tmp_path: Path) -> None:
    p = tmp_path / "m.jsonl"
    a, b = make_record(id="a" * 64), make_record(id="b" * 64)
    p.write_text(a.model_dump_json() + "\n{not json}\n" + b.model_dump_json() + "\n")
    with pytest.raises(ManifestError, match=r"m\.jsonl:2"):
        Manifest.load(p)
    assert "{not json}" in p.read_text()


def test_replace_all_keeps_a_bak_and_leaves_no_temp_files(tmp_path: Path) -> None:
    p = tmp_path / "m.jsonl"
    a, b = make_record(id="a" * 64), make_record(id="b" * 64)
    m = Manifest.load(p)
    m.append(a)
    before = p.read_bytes()
    m.replace_all([b])
    assert p.with_suffix(".jsonl.bak").read_bytes() == before
    assert Manifest.load(p).records() == [b]
    assert {f.name for f in tmp_path.iterdir()} == {"m.jsonl", "m.jsonl.bak"}


def test_append_rejects_an_existing_id(tmp_path: Path) -> None:
    m = Manifest.load(tmp_path / "m.jsonl")
    a = make_record()
    m.append(a)
    with pytest.raises(ManifestError):
        m.append(a)
    assert Manifest.load(tmp_path / "m.jsonl").records() == [a]


def test_valid_last_line_without_newline_is_normalized_and_stays_appendable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "manifest.jsonl"
    first, second = make_record(id="a" * 64), make_record(id="b" * 64)
    path.write_text(first.model_dump_json())
    manifest = Manifest.load(path)
    assert manifest.records() == [first]
    assert path.read_bytes().endswith(b"\n")
    assert "newline" in caplog.text and str(path) in caplog.text
    manifest.append(second)
    assert Manifest.load(path).records() == [first, second]
