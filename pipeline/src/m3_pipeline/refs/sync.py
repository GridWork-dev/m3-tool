# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import hashlib
import importlib
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from m3_pipeline.refs.manifest import Manifest
from m3_pipeline.refs.models import ImageRecord
from m3_pipeline.refs.store import RefStore

MANIFEST_KEY = "manifest.jsonl"
BUCKET = "m3-tool-refs"


class SyncError(Exception):
    pass


class ObjectStore(Protocol):
    def list_keys(self, prefix: str = "") -> set[str]: ...
    def put_file(self, key: str, path: Path) -> None: ...
    def get_file(self, key: str, dest: Path) -> None: ...


class R2Store:
    def __init__(self, client: Any, bucket: str = BUCKET) -> None:
        self.client = client
        self.bucket = bucket

    def list_keys(self, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        token: str | None = None
        while True:
            kwargs: dict[str, str] = {"Bucket": self.bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            response = self.client.list_objects_v2(**kwargs)
            keys.update(item["Key"] for item in response.get("Contents", []))
            if not response.get("IsTruncated"):
                return keys
            token = response["NextContinuationToken"]

    def put_file(self, key: str, path: Path) -> None:
        self.client.upload_file(str(path), self.bucket, key)

    def get_file(self, key: str, dest: Path) -> None:
        self.client.download_file(self.bucket, key, str(dest))


def make_r2_client(env: Mapping[str, str]) -> Any:
    required = ("M3_R2_ACCOUNT_ID", "M3_R2_ACCESS_KEY_ID", "M3_R2_SECRET_ACCESS_KEY")
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise SyncError(f"missing environment variables: {', '.join(missing)}")
    boto3 = importlib.import_module("boto3")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{env['M3_R2_ACCOUNT_ID']}.r2.cloudflarestorage.com",
        region_name="auto",
        aws_access_key_id=env["M3_R2_ACCESS_KEY_ID"],
        aws_secret_access_key=env["M3_R2_SECRET_ACCESS_KEY"],
    )


def remote_key(record: ImageRecord) -> str:
    return f"images/{record.id[:2]}/{record.id}.{record.ext}"


def merge_manifests(
    local: Sequence[ImageRecord],
    remote: Sequence[ImageRecord],
) -> list[ImageRecord]:
    merged = {record.id: record for record in local}
    for record in remote:
        current = merged.get(record.id)
        if current is None or (current.labels is None and record.labels is not None):
            merged[record.id] = record
    return list(merged.values())


@dataclass(frozen=True)
class SyncReport:
    uploaded: int
    downloaded: int
    skipped: int


def push(store: RefStore, remote: ObjectStore, *, force: bool = False) -> SyncReport:
    keys = remote.list_keys("images/")
    uploaded = skipped = 0
    records = store.records()
    for record in records:
        key = remote_key(record)
        if key in keys:
            skipped += 1
            continue
        remote.put_file(key, store.image_path(record))
        uploaded += 1
    refs_dir = store.work_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=refs_dir) as directory:
        manifest_path = Path(directory) / MANIFEST_KEY
        if not force and MANIFEST_KEY in remote.list_keys():
            remote.get_file(MANIFEST_KEY, manifest_path)
            local_ids = {r.id for r in records}
            unknown = sum(r.id not in local_ids for r in Manifest.load(manifest_path).records())
            if unknown:
                raise SyncError(
                    f"remote manifest has {unknown} records missing locally; "
                    "run `pipeline refs sync pull` first or pass --force"
                )
        manifest_path.write_text("".join(r.model_dump_json() + "\n" for r in records))
        remote.put_file(MANIFEST_KEY, manifest_path)
    return SyncReport(uploaded, 0, skipped)


def pull(store: RefStore, remote: ObjectStore) -> SyncReport:
    if MANIFEST_KEY not in remote.list_keys():
        return SyncReport(0, 0, 0)
    refs_dir = store.work_dir / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    downloaded = skipped = 0
    with tempfile.TemporaryDirectory(dir=refs_dir) as directory:
        temp_dir = Path(directory)
        manifest_path = temp_dir / MANIFEST_KEY
        remote.get_file(MANIFEST_KEY, manifest_path)
        records = Manifest.load(manifest_path).records()
        for record in records:
            dest = store.image_path(record)
            if dest.exists():
                skipped += 1
                continue
            temp_image = temp_dir / "image.tmp"
            remote.get_file(remote_key(record), temp_image)
            if hashlib.sha256(temp_image.read_bytes()).hexdigest() != record.id:
                raise SyncError(f"hash mismatch for {remote_key(record)}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(temp_image, dest)
            downloaded += 1
        store.update(merge_manifests(store.records(), records))
    return SyncReport(0, downloaded, skipped)
