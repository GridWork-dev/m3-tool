import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from m3_pipeline.config import Settings
from m3_pipeline.refs.imaging import UnreadableImage, inspect_image
from m3_pipeline.refs.manifest import Manifest
from m3_pipeline.refs.models import ImageRecord, Source
from m3_pipeline.refs.subjects import parse_subject


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
            for line in self._skips_path.read_text().splitlines():
                row: dict[str, str] = json.loads(line)
                self._skips.add(row["url"])

    def ingest_bytes(
        self, data: bytes, *, subject: str, source: Source, now: datetime | None = None
    ) -> IngestResult:
        parse_subject(subject)
        try:
            info = inspect_image(data)
        except UnreadableImage as exc:
            return IngestResult("rejected", None, str(exc))
        image_id = hashlib.sha256(data).hexdigest()
        urls = [source.source_url] if source.source_url else []
        if source.kind == "commons" and source.page_url:
            urls.append(source.page_url)
        existing = self.get(image_id)
        if existing:
            values = existing.model_dump()
            values["seen_urls"] = list(dict.fromkeys([*existing.seen_urls, *urls]))
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
            self.update(record if r.id == image_id else r for r in self.records())
            reason = (
                f"kept first subject {existing.subject}" if existing.subject != subject else None
            )
            return IngestResult("known_bytes", record, reason)
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
                "seen_urls": urls,
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

    def known_url(self, url: str) -> bool:
        return self._manifest.id_for_url(url) is not None

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
