import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
from refs_fakes import FakeObjectStore, FakeWikimedia
from refs_helpers import FakeClock, make_image_bytes, make_labels, write_jsonl
from test_refs_commons import FULL, commons_page
from test_refs_description import repo as repo

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.refs.classify import export_batches, import_labels
from m3_pipeline.refs.commons import CommonsClient
from m3_pipeline.refs.credits import render_credits
from m3_pipeline.refs.cutouts import make_cutouts
from m3_pipeline.refs.dedupe import apply_dedupe
from m3_pipeline.refs.importer import import_directory
from m3_pipeline.refs.sources import DEFAULT_USER_AGENT, CommonsSettings, CrawlSettings, RefsSources
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.sync import pull, push
from m3_pipeline.refs.throttle import Throttle
from m3_pipeline.refs.viewsets import ViewSet
from m3_pipeline.stages import REGISTRY


def test_full_flow_from_collection_to_refs_stage_and_back_through_sync(
    repo: Settings,
    store: RefStore,
    tmp_path: Path,
) -> None:
    # Use the fixture repository's data with the supplied store's private work directory.
    repo = replace(repo, work_dir=store.work_dir)
    clock = FakeClock()
    world = FakeWikimedia([commons_page("a.jpg", FULL), commons_page("b.jpg")], clock=clock)
    with httpx.Client(transport=world.transport) as http:
        report = CommonsClient(
            http,
            store,
            sources=RefsSources(DEFAULT_USER_AGENT, CommonsSettings(), CrawlSettings(), {}),
            throttle=Throttle(3, clock=clock.now, sleep=clock.sleep),
        ).collect("e46-coupe", ["Test cars"])
    assert report.added == 2
    commons_id = next(r.id for r in store.records() if r.author == "Jane Doe")
    unknown_id = next(r.id for r in store.records() if r.license_short == "unknown")
    photos = tmp_path / "photos"
    photos.mkdir()
    for i in range(4):
        (photos / f"{i}.jpg").write_bytes(make_image_bytes(i + 10))
    assert import_directory(store, photos, subject="e46-coupe", source_note="test").added == 4
    assert apply_dedupe(store).duplicates == 0
    exported = export_batches(store, "e46-coupe")
    batch = json.loads(exported.batches[0].read_text())
    remaining = iter(["side_left", "front", "rear", "top"])
    rows: list[dict[str, Any]] = []
    for image in batch["images"]:
        view = (
            "front_34_left"
            if image["id"] == commons_id
            else "rear_34_right"
            if image["id"] == unknown_id
            else next(remaining)
        )
        rows.append({"id": image["id"], **make_labels(view=view).model_dump()})
    assert import_labels(store, write_jsonl(tmp_path, rows)).labeled == 6
    assert make_cutouts(store, "e46-coupe", lambda im: im.convert("RGBA")).created == 6
    result = REGISTRY["refs"](AssetSpec("body", "base-car", "e46", "e46-coupe"), repo)
    assert result.ok
    viewset = ViewSet.model_validate_json(result.outputs[0].read_text())
    credited = next(e for e in viewset.entries() if e.image_id == commons_id)
    assert not credited.mirrored and credited.cutout_path is not None
    assert not viewset.all_cc_or_pd and "Jane Doe" in render_credits(viewset)
    remote = FakeObjectStore()
    assert push(store, remote).uploaded == 6
    fresh = RefStore(replace(repo, work_dir=tmp_path / "fresh"))
    assert pull(fresh, remote).downloaded == 6
    assert fresh.records() == store.records()
    assert all(
        fresh.image_path(r).read_bytes() == store.image_path(r).read_bytes()
        for r in fresh.records()
    )
