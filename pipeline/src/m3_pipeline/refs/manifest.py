import logging
import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pydantic import ValidationError

from m3_pipeline.refs.models import ImageRecord


class ManifestError(Exception):
    pass


class Manifest:
    def __init__(self, path: Path, records: Iterable[ImageRecord] = ()) -> None:
        self.path = path
        self._records = {r.id: r for r in records}

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls(path)
        lines = path.read_bytes().splitlines(keepends=True)
        records: list[ImageRecord] = []
        ids: set[str] = set()
        torn = False
        for lineno, line in enumerate(lines, 1):
            try:
                record = ImageRecord.model_validate_json(line)
                if record.id in ids:
                    raise ValueError(f"duplicate id {record.id}")
            except (ValidationError, ValueError) as exc:
                if lineno == len(lines) and not line.endswith(b"\n"):
                    torn = True
                    break
                raise ManifestError(f"{path}:{lineno}: {exc}") from exc
            records.append(record)
            ids.add(record.id)
        manifest = cls(path, records)
        if torn:
            manifest.replace_all(records)
            logging.getLogger(__name__).warning("%s: dropped torn last manifest line", path)
        return manifest

    def get(self, image_id: str) -> ImageRecord | None:
        return self._records.get(image_id)

    def records(self) -> list[ImageRecord]:
        return list(self._records.values())

    def id_for_url(self, url: str) -> str | None:
        return next((r.id for r in self._records.values() if url in r.seen_urls), None)

    def append(self, record: ImageRecord) -> None:
        if record.id in self._records:
            raise ManifestError(f"{self.path}: existing id {record.id}")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as output:
            output.write(record.model_dump_json() + "\n")
            output.flush()
            os.fsync(output.fileno())
        self._records[record.id] = record

    def replace_all(self, records: Iterable[ImageRecord]) -> None:
        new = list(records)
        if len({r.id for r in new}) != len(new):
            raise ManifestError(f"{self.path}: duplicate ids")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent)
        temp = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                for record in new:
                    output.write(record.model_dump_json() + "\n")
                output.flush()
                os.fsync(output.fileno())
            if self.path.exists():
                shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".bak"))
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)
        self._records = {r.id: r for r in new}
