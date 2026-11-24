from dataclasses import dataclass, field
from pathlib import Path

from m3_pipeline.refs.models import Source
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.subjects import parse_subject


@dataclass
class ImportReport:
    added: int = 0
    known: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list[tuple[str, str]])


def import_directory(
    store: RefStore,
    directory: Path,
    *,
    subject: str,
    source_note: str,
    license_short: str | None = None,
) -> ImportReport:
    parse_subject(subject)
    if not directory.is_dir():
        raise ValueError(f"{directory}: expected a directory")
    report = ImportReport()
    suffixes = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".avif",
        ".heic",
        ".heif",
        ".tif",
        ".tiff",
        ".gif",
        ".bmp",
    }
    source = Source(
        "local",
        None,
        None,
        None,
        license_short=license_short or "unknown",
        source_note=source_note,
    )
    for path in sorted(directory.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in suffixes:
            continue
        try:
            result = store.ingest_bytes(path.read_bytes(), subject=subject, source=source)
        except OSError as exc:
            report.skipped.append((str(path), str(exc)))
            continue
        if result.outcome == "added":
            report.added += 1
        elif result.outcome == "known_bytes":
            report.known += 1
        else:
            reason = result.reason or "unreadable image"
            if path.suffix.lower() in {".heic", ".heif"}:
                reason += (
                    "; convert to JPEG first (macOS: sips -s format jpeg in.heic --out out.jpg)"
                )
            report.skipped.append((str(path), reason))
    return report
