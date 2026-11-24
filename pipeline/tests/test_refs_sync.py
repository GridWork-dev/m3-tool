from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from refs_fakes import FakeObjectStore
from refs_helpers import ingest, make_image_bytes, make_labels, make_record

from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.sync import (
    MANIFEST_KEY,
    R2Store,
    SyncError,
    make_r2_client,
    merge_manifests,
    pull,
    push,
    remote_key,
)


def test_push_uploads_only_missing_hashes_and_the_manifest_last(store: RefStore) -> None:
    for i in range(3):
        ingest(store, make_image_bytes(i))
    remote = FakeObjectStore()
    rep = push(store, remote)
    assert rep.uploaded == 3 and remote.put_order[-1] == MANIFEST_KEY
    assert remote.list_keys() == {remote_key(r) for r in store.records()} | {MANIFEST_KEY}
    assert push(store, remote).uploaded == 0


def test_interrupted_push_never_leaves_a_manifest_that_references_missing_objects(
    store: RefStore,
) -> None:
    for i in range(3):
        ingest(store, make_image_bytes(i))
    remote = FakeObjectStore(fail_after_puts=2)
    with pytest.raises(OSError):
        push(store, remote)
    assert MANIFEST_KEY not in remote.list_keys()
    remote.fail_after_puts = None
    assert push(store, remote).uploaded == 1


def test_push_refuses_to_overwrite_a_remote_manifest_with_unknown_records(
    store: RefStore,
    tmp_path: Path,
) -> None:
    remote = FakeObjectStore()
    other = RefStore(replace(store.settings, work_dir=tmp_path / "other"))
    record = ingest(other, make_image_bytes(1))
    push(other, remote)
    before = remote.objects[MANIFEST_KEY]
    with pytest.raises(SyncError, match="pull"):
        push(store, remote)
    assert remote.objects[MANIFEST_KEY] == before
    push(store, remote, force=True)
    assert record.id not in remote.objects[MANIFEST_KEY].decode()


def test_pull_downloads_missing_images_then_merges_the_manifest(
    store: RefStore, tmp_path: Path
) -> None:
    record = ingest(store, make_image_bytes(1))
    remote = FakeObjectStore()
    push(store, remote)
    remote.objects["images/orphan"] = b"ignored"
    fresh = RefStore(replace(store.settings, work_dir=tmp_path / "fresh"))
    report = pull(fresh, remote)
    assert report.downloaded == 1 and fresh.records() == [record]
    assert fresh.image_path(record).read_bytes() == store.image_path(record).read_bytes()
    assert pull(fresh, remote).downloaded == 0
    local = ingest(fresh, make_image_bytes(2))
    pull(fresh, remote)
    assert {r.id for r in fresh.records()} == {record.id, local.id}


def test_pull_rejects_an_object_whose_hash_does_not_match_its_key(
    store: RefStore, tmp_path: Path
) -> None:
    record = ingest(store, make_image_bytes(1))
    remote = FakeObjectStore()
    push(store, remote)
    remote.objects[remote_key(record)] = b"tampered"
    fresh = RefStore(replace(store.settings, work_dir=tmp_path / "fresh"))
    with pytest.raises(SyncError, match="hash"):
        pull(fresh, remote)
    assert fresh.records() == [] and not fresh.image_path(record).exists()
    assert not list(fresh.work_dir.rglob("*.tmp"))


def test_merge_manifests_unions_and_prefers_remote_only_when_it_alone_is_labeled() -> None:
    a, b, c = [make_record(id=char * 64) for char in "abc"]
    labeled_a = a.model_copy(update={"labels": make_labels(), "status": "labeled"})
    labeled_b = b.model_copy(update={"labels": make_labels(), "status": "labeled"})
    remote_b = labeled_b.model_copy(update={"author": "remote"})
    result = {r.id: r for r in merge_manifests([a, labeled_b], [labeled_a, remote_b, c])}
    assert result == {a.id: labeled_a, b.id: labeled_b, c.id: c}
    assert merge_manifests([labeled_a], [a]) == [labeled_a]


def test_make_r2_client_names_missing_variables_only() -> None:
    with pytest.raises(SyncError) as e:
        make_r2_client({"M3_R2_ACCESS_KEY_ID": "test-key"})
    assert "M3_R2_ACCOUNT_ID" in str(e.value)
    assert "M3_R2_SECRET_ACCESS_KEY" in str(e.value) and "test-key" not in str(e.value)


def test_make_r2_client_targets_the_account_endpoint() -> None:
    client = make_r2_client(
        {
            "M3_R2_ACCOUNT_ID": "acct",
            "M3_R2_ACCESS_KEY_ID": "test-key",
            "M3_R2_SECRET_ACCESS_KEY": "test-key",
        }
    )
    assert client.meta.endpoint_url == "https://acct.r2.cloudflarestorage.com"
    assert client.meta.region_name == "auto"


def test_r2_store_paginates_and_delegates_file_transfers(tmp_path: Path) -> None:
    class Client:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self.uploaded: tuple[str, str, str] | None = None
            self.downloaded: tuple[str, str, str] | None = None

        def list_objects_v2(self, **kw: Any) -> dict[str, Any]:
            self.calls.append(kw)
            if "ContinuationToken" not in kw:
                return {
                    "Contents": [{"Key": "images/a"}],
                    "IsTruncated": True,
                    "NextContinuationToken": "next",
                }
            return {"Contents": [{"Key": "images/b"}], "IsTruncated": False}

        def upload_file(self, path: str, bucket: str, key: str) -> None:
            self.uploaded = path, bucket, key

        def download_file(self, bucket: str, key: str, path: str) -> None:
            self.downloaded = bucket, key, path

    client = Client()
    remote = R2Store(client)
    assert remote.list_keys("images/") == {"images/a", "images/b"}
    assert client.calls == [
        {"Bucket": "m3-tool-refs", "Prefix": "images/"},
        {"Bucket": "m3-tool-refs", "Prefix": "images/", "ContinuationToken": "next"},
    ]
    path = tmp_path / "x"
    remote.put_file("x", path)
    remote.get_file("x", path)
    assert client.uploaded == (str(path), "m3-tool-refs", "x")
    assert client.downloaded == ("m3-tool-refs", "x", str(path))
