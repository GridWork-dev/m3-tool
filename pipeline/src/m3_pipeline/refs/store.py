import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from m3_pipeline.config import Settings
from m3_pipeline.refs.imaging import UnreadableImage, inspect_image
from m3_pipeline.refs.manifest import Manifest
from m3_pipeline.refs.models import ImageRecord, Source
from m3_pipeline.refs.subjects import parse_subject

_LOG = logging.getLogger(__name__)


def _source_urls(source: Source) -> list[str]:
    urls = [source.source_url] if source.source_url else []
    if source.kind == "commons" and source.page_url:
        urls.append(source.page_url)
    return urls


class RefsStoreError(Exception):
    pass


@dataclass(frozen=True)
class IngestResult:
    outcome: Literal["added", "known_bytes", "rejected"]
    record: ImageRecord | None
    reason: str | None


class RefStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.work_dir = settings.work_dir.expanduser().resolve()
        if self.work_dir.is_relative_to(settings.repo_root.expanduser().resolve()):
            raise RefsStoreError("work_dir must be outside the repo")
        self._manifest = Manifest.load(self.work_dir / "refs/manifest.jsonl")
        self._skips_path = self.work_dir / "refs/skipped.jsonl"
        self._skips: set[str] = set()
        if self._skips_path.exists():
            self._load_skips()

    def _load_skips(self) -> None:
        lines = self._skips_path.read_bytes().splitlines(keepends=True)
        for lineno, line in enumerate(lines, 1):
            try:
                value: object = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if lineno == len(lines) and not line.endswith(b"\n"):
                    self._skips_path.write_bytes(b"".join(lines[:-1]))
                    _LOG.warning("%s: dropped torn last skip-log line", self._skips_path)
                    return
                raise RefsStoreError(f"{self._skips_path}:{lineno}: {exc}") from exc
            if not isinstance(value, dict):
                raise RefsStoreError(f"{self._skips_path}:{lineno}: expected a skip record")
            row = cast(dict[str, object], value)
            url = row.get("url")
            if not isinstance(url, str):
                raise RefsStoreError(f"{self._skips_path}:{lineno}: expected a string url")
            self._skips.add(url)
        if lines and not lines[-1].endswith(b"\n"):
            # Keep a complete tail appendable, just like the manifest.
            self._skips_path.write_bytes(b"".join(lines) + b"\n")

    def ingest_bytes(
        self, data: bytes, *, subject: str, source: Source, now: datetime | None = None
    ) -> IngestResult:
        parse_subject(subject)
        try:
            info = inspect_image(data)
        except UnreadableImage as exc:
            return IngestResult("rejected", None, str(exc))
        image_id = hashlib.sha256(data).hexdigest()
        existing = self.get(image_id)
        if existing:
            self.merge_provenance(image_id, source)
            reason = (
                f"kept first subject {existing.subject}" if existing.subject != subject else None
            )
            return IngestResult("known_bytes", self.get(image_id), reason)
        record = ImageRecord.model_validate(
            {
                "id": image_id,
                "subject": subject,
                "source_kind": source.kind,
                "source_url": source.source_url,
                "page_url": source.page_url,
                "author": source.author,
                "license_short": source.license_short,
                "license_url": source.license_url,
                "source_note": source.source_note,
                "retrieved_at": now or datetime.now(UTC),
                "width": info.width,
                "height": info.height,
                "ext": info.ext,
                "phash": info.phash,
                "seen_urls": _source_urls(source),
            }
        )
        path = self.image_path(record)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=path.parent)
            temp = Path(name)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp, path)
            finally:
                temp.unlink(missing_ok=True)
        self._manifest.append(record)
        return IngestResult("added", record, None)

    def records(self, subject: str | None = None) -> list[ImageRecord]:
        return [r for r in self._manifest.records() if subject is None or r.subject == subject]

    def get(self, image_id: str) -> ImageRecord | None:
        return self._manifest.get(image_id)

    def update(self, records: Iterable[ImageRecord]) -> None:
        self._manifest.replace_all(records)

    def merge_provenance(self, image_id: str, source: Source) -> bool:
        existing = self.get(image_id)
        if existing is None:
            return False
        values = existing.model_dump()
        values["seen_urls"] = list(dict.fromkeys([*existing.seen_urls, *_source_urls(source)]))
        if existing.license_short == "unknown" and source.license_short != "unknown":
            values.update(
                source_kind=source.kind,
                source_url=source.source_url,
                page_url=source.page_url,
                author=source.author,
                license_short=source.license_short,
                license_url=source.license_url,
                source_note=source.source_note,
            )
        record = ImageRecord.model_validate(values)
        if record == existing:
            return False
        self.update(record if r.id == image_id else r for r in self.records())
        return True

    def id_for_url(self, url: str) -> str | None:
        return self._manifest.id_for_url(url)

    def known_url(self, url: str) -> bool:
        return self.id_for_url(url) is not None

    def record_skip(self, url: str, reason: str) -> None:
        self._skips_path.parent.mkdir(parents=True, exist_ok=True)
        with self._skips_path.open("a") as output:
            output.write(json.dumps({"url": url, "reason": reason}) + "\n")
        self._skips.add(url)

    def was_skipped(self, url: str) -> bool:
        return url in self._skips

    @staticmethod
    def image_relpath(record: ImageRecord) -> str:
        return f"refs/images/{record.id[:2]}/{record.id}.{record.ext}"

    def image_path(self, record: ImageRecord) -> Path:
        return self.work_dir / self.image_relpath(record)
