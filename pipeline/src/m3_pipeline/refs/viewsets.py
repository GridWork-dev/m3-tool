import os
import re
import tempfile
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from m3_pipeline.refs.cutouts import cutout_relpath
from m3_pipeline.refs.filters import FilterTarget, evaluate
from m3_pipeline.refs.imaging import hamming
from m3_pipeline.refs.models import ImageRecord, Kind, SourceKind
from m3_pipeline.refs.store import RefStore

EXTERIOR_PRIORITY = ("front_34_left", "rear_34_right", "side_left", "front", "rear")
INTERIOR_ORDER = (
    "interior_dash",
    "interior_gauges",
    "interior_steering",
    "interior_seats",
    "interior_door",
    "interior_console",
)
DRIVE_DEPENDENT = ("interior_dash", "interior_door")
NEVER_MIRRORED = ("interior_steering", "interior_gauges")
PRODUCT_ORDER = ("product_34", "product_front", "product_side", "product_detail")
MIRROR_OF: dict[str, str] = {
    "front_34_left": "front_34_right",
    "front_34_right": "front_34_left",
    "rear_34_left": "rear_34_right",
    "rear_34_right": "rear_34_left",
    "side_left": "side_right",
    "side_right": "side_left",
}


@dataclass(frozen=True)
class ViewsetPolicy:
    max_views: int = 5
    min_views: int = 3
    prefer_market: Literal["us", "euro"] | None = "us"
    spread_bits: int = 12


def score_image(record: ImageRecord, policy: ViewsetPolicy = ViewsetPolicy()) -> float:
    labels = record.labels
    if labels is None:
        raise ValueError(f"{record.id}: labels required for scoring")
    return (
        labels.quality * 20
        + min(min(record.width, record.height), 2000) / 2000 * 20
        - {"none": 0, "minor": 10, "major": 40}[labels.occlusion]
        - (5 if labels.stock is None else 0)
        + (5 if labels.market == policy.prefer_market else 0)
    )


def is_cc_or_pd(license_short: str) -> bool:
    return bool(
        re.match(r"^CC0|^CC BY(-SA)? \d|^(Public domain|PD)\b|^No restrictions", license_short)
    )


def pick_spread(
    ranked: Sequence[ImageRecord],
    limit: int,
    *,
    taken: Sequence[ImageRecord] = (),
    min_distance: int = 12,
) -> list[ImageRecord]:
    chosen: list[ImageRecord] = []
    taken_ids = {r.id for r in taken}
    for record in ranked:
        if len(chosen) >= limit:
            break
        previous = [*taken, *chosen]
        if record.id in taken_ids or any(r.id == record.id for r in chosen):
            continue
        seat = (
            record.labels.seat
            if record.labels and record.labels.view == "interior_seats"
            else "unknown"
        )
        new_seat = seat != "unknown" and all(
            r.labels is None or r.labels.seat != seat for r in previous
        )
        if new_seat or all(hamming(record.phash, r.phash) > min_distance for r in previous):
            chosen.append(record)
    ids = taken_ids | {r.id for r in chosen}
    for record in ranked:
        if len(chosen) >= limit:
            break
        if record.id not in ids:
            chosen.append(record)
            ids.add(record.id)
    return chosen


class ViewEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    view: str
    image_id: str
    image_path: str
    cutout_path: str | None
    mirrored: bool
    score: float
    source_kind: SourceKind
    license_short: str
    license_url: str | None
    author: str | None
    page_url: str | None
    drive_side: str
    seat: str | None
    contains_text_risk: bool


class ViewSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    subject: str
    kind: Kind
    views: list[ViewEntry]
    components: dict[str, list[ViewEntry]]
    missing: list[str]
    all_cc_or_pd: bool
    licenses: list[str]
    rejected: dict[str, int]

    def entries(self) -> list[ViewEntry]:
        return [*self.views, *(entry for group in self.components.values() for entry in group)]


def _entry(
    record: ImageRecord,
    view: str,
    mirrored: bool,
    text_risk: bool,
    cutouts: Collection[str],
    policy: ViewsetPolicy,
) -> ViewEntry:
    assert record.labels is not None
    assert not (view in NEVER_MIRRORED and mirrored)
    return ViewEntry(
        view=view,
        image_id=record.id,
        image_path=RefStore.image_relpath(record),
        cutout_path=cutout_relpath(record.id) if record.id in cutouts else None,
        mirrored=mirrored,
        score=score_image(record, policy),
        source_kind=record.source_kind,
        license_short=record.license_short,
        license_url=record.license_url,
        author=record.author,
        page_url=record.page_url,
        drive_side=record.labels.drive_side,
        seat=record.labels.seat if view == "interior_seats" else None,
        contains_text_risk=text_risk,
    )


def build_viewset(
    subject: str,
    records: Sequence[ImageRecord],
    *,
    cutouts: Collection[str] = (),
    policy: ViewsetPolicy = ViewsetPolicy(),
) -> ViewSet:
    target = FilterTarget.from_subject(subject)
    rejected: Counter[str] = Counter()
    accepted: list[ImageRecord] = []
    for record in records:
        decision = evaluate(record, target)
        if not decision.accepted:
            rejected.update(decision.reasons)
            continue
        assert record.labels is not None
        if (
            target.kind == "interior"
            and record.labels.view in DRIVE_DEPENDENT
            and record.labels.drive_side == "unknown"
        ):
            rejected["drive_side_unknown"] += 1
            continue
        accepted.append(record)
    ranked = sorted(
        accepted, key=lambda r: (-score_image(r, policy), -int(is_cc_or_pd(r.license_short)), r.id)
    )
    views: list[ViewEntry] = []
    components: dict[str, list[ViewEntry]] = {}
    missing: list[str] = []
    if target.kind == "interior":
        for component in INTERIOR_ORDER:
            candidates = [r for r in ranked if r.labels and r.labels.view == component]
            if component in DRIVE_DEPENDENT:
                left = [r for r in candidates if r.labels and r.labels.drive_side == "lhd"]
                right = [r for r in candidates if r.labels and r.labels.drive_side == "rhd"]
                picks = pick_spread(left, policy.max_views, min_distance=policy.spread_bits)
                picks += pick_spread(
                    right,
                    policy.max_views - len(picks),
                    taken=picks,
                    min_distance=policy.spread_bits,
                )
            else:
                picks = pick_spread(candidates, policy.max_views, min_distance=policy.spread_bits)
            if picks:
                components[component] = [
                    _entry(
                        r,
                        component,
                        component in DRIVE_DEPENDENT
                        and r.labels is not None
                        and r.labels.drive_side == "rhd",
                        component in DRIVE_DEPENDENT
                        and r.labels is not None
                        and r.labels.drive_side == "rhd",
                        cutouts,
                        policy,
                    )
                    for r in picks
                ]
            if len(picks) < policy.min_views:
                missing.append(component)
    else:
        slots = EXTERIOR_PRIORITY if target.kind == "base-car" else PRODUCT_ORDER
        for slot in slots:
            direct = [r for r in ranked if r.labels and r.labels.view == slot]
            mirrored = False
            if not direct and target.kind == "base-car" and slot in MIRROR_OF:
                direct = [r for r in ranked if r.labels and r.labels.view == MIRROR_OF[slot]]
                mirrored = True
            if direct and len(views) < policy.max_views:
                views.append(_entry(direct[0], slot, mirrored, False, cutouts, policy))
            else:
                missing.append(slot)
    entries = [*views, *(e for group in components.values() for e in group)]
    return ViewSet(
        subject=subject,
        kind=target.kind,
        views=views,
        components=components,
        missing=missing,
        all_cc_or_pd=bool(entries) and all(is_cc_or_pd(e.license_short) for e in entries),
        licenses=sorted({e.license_short for e in entries}),
        rejected=dict(rejected),
    )


def write_viewset(
    store: RefStore,
    subject: str,
    dest: Path,
    *,
    policy: ViewsetPolicy = ViewsetPolicy(),
) -> ViewSet:
    records = store.records(subject)
    cutouts = {r.id for r in records if (store.work_dir / cutout_relpath(r.id)).exists()}
    viewset = build_viewset(subject, records, cutouts=cutouts, policy=policy)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=dest.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(viewset.model_dump_json(indent=2) + "\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    return viewset
