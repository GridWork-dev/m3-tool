from refs_helpers import ingest, make_image_bytes, make_labels
from test_refs_description import repo as repo

from m3_pipeline.assets import AssetSpec
from m3_pipeline.config import Settings
from m3_pipeline.refs.store import RefStore
from m3_pipeline.refs.viewsets import INTERIOR_ORDER, ViewSet
from m3_pipeline.stages import REGISTRY
from m3_pipeline.stages.refs import refs_stage

BODY = AssetSpec("e46-coupe-body", "base-car", "e46", "e46-coupe")
INT = AssetSpec("e46-coupe-interior", "interior", "e46", "e46-coupe-interior")


def add_views(
    repo: Settings, views: list[str], subject: str = "e46-coupe", start: int = 0, side: str = "lhd"
) -> None:
    store = RefStore(repo)
    for index, view in enumerate(views, start):
        record = ingest(store, make_image_bytes(index), subject=subject)
        store.update(
            [
                r.model_copy(
                    update={"labels": make_labels(view=view, drive_side=side), "status": "labeled"}
                )
                if r.id == record.id
                else r
                for r in store.records()
            ]
        )


def test_refs_is_registered_through_the_cli_import() -> None:
    import m3_pipeline.cli

    assert m3_pipeline.cli.app is not None and "refs" in REGISTRY


def test_refs_stage_writes_viewset_and_description(repo: Settings) -> None:
    add_views(repo, ["front", "rear", "side_left"])
    result = refs_stage(BODY, repo)
    directory = repo.work_dir / "assets/e46-coupe-body/refs"
    assert result.ok and result.outputs == [
        directory / "viewset.json",
        directory / "description.md",
    ]
    assert ViewSet.model_validate_json(result.outputs[0].read_text()).subject == "e46-coupe"
    assert "## Generator prompt" in result.outputs[1].read_text()


def test_refs_stage_is_not_ok_below_min_views_but_still_writes_outputs(repo: Settings) -> None:
    add_views(repo, ["front", "rear"])
    result = refs_stage(BODY, repo)
    assert not result.ok and len(result.outputs) == 2 and all(p.exists() for p in result.outputs)
    assert all(
        view in "\n".join(result.messages)
        for view in ("front_34_left", "rear_34_right", "side_left")
    )


def test_refs_stage_interior_needs_every_component_at_min_views(repo: Settings) -> None:
    views = [
        component
        for component in INTERIOR_ORDER
        for _ in range(2 if component == "interior_console" else 3)
    ]
    add_views(repo, views, INT.subject)
    result = refs_stage(INT, repo)
    assert not result.ok and "interior_console" in "\n".join(result.messages)
    add_views(repo, ["interior_console"], INT.subject, start=100)
    assert refs_stage(INT, repo).ok


def test_refs_stage_reports_description_error_as_not_ok(repo: Settings) -> None:
    result = refs_stage(AssetSpec("x", "product", "e46", "product-missing"), repo)
    assert not result.ok and "data/parts/e46/missing.yaml" in "\n".join(result.messages)


def test_refs_stage_flags_subject_kind_mismatch(repo: Settings) -> None:
    result = refs_stage(AssetSpec("x", "interior", "e46", "e46-coupe"), repo)
    assert not result.ok and "kind" in "\n".join(result.messages)


def test_refs_stage_messages_flag_text_risk_views(repo: Settings) -> None:
    add_views(repo, ["interior_dash"], INT.subject, side="rhd")
    result = refs_stage(INT, repo)
    assert "interior_dash: mirrored RHD image, text may be reversed" in result.messages
