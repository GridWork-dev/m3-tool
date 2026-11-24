from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from m3_pipeline.refs.imaging import hamming
from m3_pipeline.refs.models import ImageRecord
from m3_pipeline.refs.store import RefStore


def find_duplicates(records: Sequence[ImageRecord], max_distance: int = 6) -> dict[str, str]:
    groups: dict[str, list[ImageRecord]] = defaultdict(list)
    for record in records:
        groups[record.subject].append(record)
    duplicates: dict[str, str] = {}
    for group in groups.values():
        kept: list[ImageRecord] = []
        for record in sorted(group, key=lambda r: (-(r.width * r.height), r.id)):
            winner = next((r for r in kept if hamming(record.phash, r.phash) <= max_distance), None)
            if winner:
                duplicates[record.id] = winner.id
            else:
                kept.append(record)
    return duplicates


@dataclass(frozen=True)
class DedupeReport:
    duplicates: int
    changed: int


def apply_dedupe(store: RefStore, subject: str | None = None) -> DedupeReport:
    records = store.records(subject)
    losers = find_duplicates(records)
    updates: dict[str, ImageRecord] = {}
    for record in records:
        if record.id in losers:
            updated = record.model_copy(
                update={"status": "duplicate", "duplicate_of": losers[record.id]}
            )
        elif record.status == "duplicate":
            updated = record.model_copy(
                update={
                    "status": "labeled" if record.labels is not None else "new",
                    "duplicate_of": None,
                }
            )
        else:
            updated = record
        if updated != record:
            updates[record.id] = updated
    store.update(updates.get(r.id, r) for r in store.records())
    return DedupeReport(len(losers), len(updates))
