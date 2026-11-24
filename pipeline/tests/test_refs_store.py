import hashlib
import socket
from pathlib import Path

import pytest
from refs_helpers import ingest, make_image_bytes
from typer.testing import CliRunner

from m3_pipeline.cli import app
from m3_pipeline.config import Settings
from m3_pipeline.refs.manifest import Manifest
from m3_pipeline.refs.models import Source
from m3_pipeline.refs.store import RefsStoreError, RefStore

SRC = Source(kind="local", source_url=None, page_url=None, author=None, source_note="n")


def test_work_dir_inside_repo_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RefsStoreError, match="outside the repo"):
        RefStore(Settings(repo_root=tmp_path, work_dir=tmp_path / "w"))


def test_ingest_stores_by_hash_and_writes_manifest(store: RefStore) -> None:
    d = make_image_bytes(1)
    r = store.ingest_bytes(d, subject="e46-coupe", source=SRC)
    i = hashlib.sha256(d).hexdigest()
    assert r.outcome == "added" and r.record is not None
    assert r.record.id == i and r.record.retrieved_at.tzinfo
    assert (store.work_dir / f"refs/images/{i[:2]}/{i}.jpg").read_bytes() == d
    assert Manifest.load(store.work_dir / "refs/manifest.jsonl").get(i) == r.record


def test_ingest_same_bytes_twice_is_idempotent(store: RefStore) -> None:
    d = make_image_bytes(1)
    store.ingest_bytes(d, subject="e46-coupe", source=SRC)
    assert store.ingest_bytes(d, subject="e46-coupe", source=SRC).outcome == "known_bytes"
    assert len((store.work_dir / "refs/manifest.jsonl").read_text().splitlines()) == 1
    assert len(list((store.work_dir / "refs/images").rglob("*.jpg"))) == 1


def test_second_collector_same_bytes_keeps_one_record_and_upgrades_unknown_license(
    store: RefStore,
) -> None:
    d = make_image_bytes(2)
    store.ingest_bytes(
        d,
        subject="e46-coupe",
        source=Source(
            "crawl",
            "https://a/x.jpg",
            "https://a/p",
            None,
        ),
    )
    r = store.ingest_bytes(
        d,
        subject="e46-coupe",
        source=Source(
            "commons",
            "https://c/t.jpg",
            "https://c/File:x",
            "Jane",
            "CC BY-SA 4.0",
            "https://cc/by-sa",
        ),
    )
    assert len(store.records()) == 1 and r.outcome == "known_bytes" and r.record is not None
    assert (r.record.source_kind, r.record.license_short, r.record.author) == (
        "commons",
        "CC BY-SA 4.0",
        "Jane",
    )
    assert {"https://a/x.jpg", "https://c/t.jpg", "https://c/File:x"} <= set(r.record.seen_urls)


def test_known_license_is_never_downgraded_by_a_later_unknown(store: RefStore) -> None:
    d = make_image_bytes(2)
    original = ingest(store, d, license_short="CC BY 4.0", author="Jane")
    result = store.ingest_bytes(d, subject="e46-coupe", source=SRC)
    assert result.record is not None
    assert (result.record.license_short, result.record.author) == ("CC BY 4.0", "Jane")
    assert result.record.id == original.id


def test_same_bytes_under_other_subject_keeps_first_subject(store: RefStore) -> None:
    d = make_image_bytes(2)
    ingest(store, d)
    result = store.ingest_bytes(d, subject="e46-coupe-interior", source=SRC)
    assert result.outcome == "known_bytes" and result.record is not None
    assert result.record.subject == "e46-coupe" and "e46-coupe" in (result.reason or "")
    assert len(store.records()) == 1


def test_known_url_and_was_skipped_after_ingest_and_record_skip(store: RefStore) -> None:
    ingest(store, make_image_bytes(2), source_url="https://a/x.jpg")
    store.record_skip("https://a/small.jpg", "small")
    fresh = RefStore(store.settings)
    assert fresh.known_url("https://a/x.jpg") and not fresh.known_url("https://a/other.jpg")
    assert fresh.was_skipped("https://a/small.jpg") and not fresh.was_skipped("https://a/x.jpg")


def test_resume_after_crash_between_file_write_and_manifest_append(
    store: RefStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = make_image_bytes(4)
    with monkeypatch.context() as m:

        def crash(self: Manifest, rec: object) -> None:
            raise KeyboardInterrupt

        m.setattr(Manifest, "append", crash)
        with pytest.raises(KeyboardInterrupt):
            store.ingest_bytes(d, subject="e46-coupe", source=SRC)
    fresh = RefStore(store.settings)
    assert fresh.records() == []
    assert fresh.ingest_bytes(d, subject="e46-coupe", source=SRC).outcome == "added"
    assert len(RefStore(store.settings).records()) == 1


def test_undecodable_bytes_are_rejected_and_not_stored(store: RefStore) -> None:
    r = store.ingest_bytes(b"<html>error</html>", subject="e46-coupe", source=SRC)
    assert r.outcome == "rejected" and r.reason and r.record is None
    assert store.records() == []
    assert not list((store.work_dir / "refs/images").rglob("*.*"))
    p = store.work_dir / "refs/manifest.jsonl"
    assert not p.exists() or not p.read_text()


def test_refs_stats_cli_counts_by_subject(store: RefStore, monkeypatch: pytest.MonkeyPatch) -> None:
    ingest(store, make_image_bytes(1))
    ingest(store, make_image_bytes(2))
    monkeypatch.setenv("M3_WORK_DIR", str(store.work_dir))
    r = CliRunner().invoke(app, ["refs", "stats"])
    assert r.exit_code == 0 and "e46-coupe images=2 new=2 labeled=0 duplicate=0" in r.output


def test_external_network_is_blocked() -> None:
    with pytest.raises(OSError):
        socket.create_connection(("example.com", 80), timeout=1)


def test_torn_skip_log_tail_is_dropped_and_store_loads(
    store: RefStore, caplog: pytest.LogCaptureFixture
) -> None:
    url = "http://127.0.0.1/small.jpg"
    store.record_skip(url, "small")
    path = store.work_dir / "refs/skipped.jsonl"
    before = path.read_bytes()
    path.write_bytes(before + b'{"url": "http://127.0.0.1/torn')
    recovered = RefStore(store.settings)
    assert recovered.was_skipped(url)
    assert recovered.records() == []
    assert "torn" in caplog.text and str(path) in caplog.text
    assert path.read_bytes() == before
    recovered.record_skip("http://127.0.0.1/next.jpg", "small")
    fresh = RefStore(store.settings)
    assert fresh.was_skipped(url) and fresh.was_skipped("http://127.0.0.1/next.jpg")


def test_corrupt_skip_log_line_in_middle_raises(store: RefStore) -> None:
    store.record_skip("http://127.0.0.1/a.jpg", "small")
    path = store.work_dir / "refs/skipped.jsonl"
    with path.open("a") as output:
        output.write('{not json}\n{"url": "http://127.0.0.1/b.jpg", "reason": "small"}\n')
    before = path.read_bytes()
    with pytest.raises(RefsStoreError, match=r"skipped\.jsonl:2") as exc:
        RefStore(store.settings)
    assert str(path) in str(exc.value)
    assert path.read_bytes() == before


def test_merge_provenance_merges_urls_without_downgrading_and_reports_changes(
    store: RefStore,
) -> None:
    original = ingest(store, make_image_bytes(), author="Jane", license_short="CC BY 4.0")
    incoming = Source("crawl", "http://127.0.0.1/a.jpg", "http://127.0.0.1/page.html", None)
    assert store.merge_provenance(original.id, incoming)
    updated = RefStore(store.settings).get(original.id)
    assert updated is not None
    assert (updated.source_kind, updated.license_short, updated.author) == (
        "local",
        "CC BY 4.0",
        "Jane",
    )
    assert updated.seen_urls == [incoming.source_url]
    before = (store.work_dir / "refs/manifest.jsonl").read_bytes()
    assert not store.merge_provenance(original.id, incoming)
    assert not store.merge_provenance("f" * 64, incoming)
    assert (store.work_dir / "refs/manifest.jsonl").read_bytes() == before


def test_valid_skip_log_tail_without_newline_stays_appendable(store: RefStore) -> None:
    first, second = "http://127.0.0.1/a.jpg", "http://127.0.0.1/b.jpg"
    store.record_skip(first, "small")
    path = store.work_dir / "refs/skipped.jsonl"
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    recovered = RefStore(store.settings)
    assert recovered.was_skipped(first)
    assert path.read_bytes().endswith(b"\n")
    recovered.record_skip(second, "small")
    fresh = RefStore(store.settings)
    assert fresh.was_skipped(first) and fresh.was_skipped(second)
