import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from m3_pipeline.stages.lib.provenance import (
    ViewProvenance,
    check_provenance,
    load_provenance,
    synth_set_usable,
    write_provenance,
)
from m3_pipeline.stages.lib.viewset_io import SpikeViewSet, ViewRef


def _item() -> ViewProvenance:
    return ViewProvenance(
        "side",
        ("photo-1",),
        "a" * 64,
        "codex",
        "2026-11-24T00:00:00Z",
        hashlib.sha256(b"picture").hexdigest(),
        True,
        True,
    )


def _guards(path: Path) -> None:
    (path / "views").mkdir()
    items = [
        replace(_item(), view=view) for view in ("front", "side", "rear", "front_34", "rear_34")
    ]
    for item in items:
        (path / "views" / f"{item.view}.png").write_bytes(b"picture")
    write_provenance(path / "provenance.json", items)
    (path / "proportion.json").write_text(json.dumps({"ok": True, "side_sha256": _item().sha256}))
    (path / "approved.json").write_text(
        json.dumps(
            {
                "approved_by": "user",
                "at": "2026-11-24",
                "views": {item.view: item.sha256 for item in items},
            }
        )
    )


def test_provenance_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "provenance.json"
    write_provenance(path, [_item()])
    assert load_provenance(path) == [_item()]


def test_check_provenance_rejects_an_unknown_input() -> None:
    vs = SpikeViewSet("e46-coupe", "base-car", (), {})
    with pytest.raises(ValueError, match="photo-1"):
        check_provenance([_item()], vs)
    ref = ViewRef(
        "front",
        "photo-1",
        Path("/unused"),
        None,
        False,
        "CC0",
        None,
        None,
        None,
        "lhd",
        None,
        False,
    )
    check_provenance([_item()], replace(vs, views=(ref,)))


@pytest.mark.parametrize("failure", [None, "proportion", "critic", "approval"])
def test_synth_set_needs_all_three_guards(tmp_path: Path, failure: str | None) -> None:
    _guards(tmp_path)
    if failure == "proportion":
        (tmp_path / "proportion.json").unlink()
    elif failure == "critic":
        write_provenance(
            tmp_path / "provenance.json",
            [
                replace(item, critic_ok=False) if item.view == "side" else item
                for item in load_provenance(tmp_path / "provenance.json")
            ],
        )
    elif failure == "approval":
        (tmp_path / "approved.json").unlink()
    assert synth_set_usable(tmp_path) is (failure is None)


def test_replacing_a_view_image_invalidates_its_critic_proportion_and_approval(
    tmp_path: Path,
) -> None:
    _guards(tmp_path)
    (tmp_path / "views/side.png").write_bytes(b"replacement")
    assert not synth_set_usable(tmp_path)


@pytest.mark.parametrize("file", ["proportion.json", "approved.json", "provenance.json"])
def test_malformed_guards_fail_closed(tmp_path: Path, file: str) -> None:
    _guards(tmp_path)
    (tmp_path / file).write_text("[]")
    assert not synth_set_usable(tmp_path)


def test_extra_unreviewed_view_is_not_usable(tmp_path: Path) -> None:
    _guards(tmp_path)
    (tmp_path / "views/unknown.png").write_bytes(b"unreviewed")
    assert not synth_set_usable(tmp_path)


def test_provenance_rejects_duplicate_views(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        write_provenance(tmp_path / "provenance.json", [_item(), _item()])


def test_side_only_probe_is_never_a_usable_set(tmp_path: Path) -> None:
    _guards(tmp_path)
    write_provenance(tmp_path / "provenance.json", [_item()])
    for path in (tmp_path / "views").glob("*.png"):
        if path.stem != "side":
            path.unlink()
    (tmp_path / "approved.json").write_text(
        json.dumps({"approved_by": "user", "at": "2026-11-24", "views": {"side": _item().sha256}})
    )
    assert not synth_set_usable(tmp_path)


@pytest.mark.parametrize("name", ["provenance.json", "proportion.json", "approved.json", "views"])
def test_guard_paths_cannot_escape_synth_dir(tmp_path: Path, name: str) -> None:
    synth = tmp_path / "synth"
    synth.mkdir()
    _guards(synth)
    path = synth / name
    outside = tmp_path / name
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=name == "views")
    assert not synth_set_usable(synth)


@pytest.mark.parametrize(
    "field,value",
    [
        ("view", []),
        ("inputs", {}),
        ("inputs", [False]),
        ("engine", []),
        ("created_at", {}),
        ("sha256", []),
        ("critic_ok", 1),
        ("prompt_sha256", None),
    ],
)
def test_wrong_provenance_types_fail_closed(tmp_path: Path, field: str, value: object) -> None:
    _guards(tmp_path)
    path = tmp_path / "provenance.json"
    raw = json.loads(path.read_text())
    raw[0][field] = value
    path.write_text(json.dumps(raw))
    assert not synth_set_usable(tmp_path)


def test_legacy_provenance_without_inspection_proof_is_not_usable(tmp_path: Path) -> None:
    from dataclasses import asdict

    _guards(tmp_path)
    path = tmp_path / "provenance.json"
    legacy: list[dict[str, object]] = [asdict(item) for item in load_provenance(path)]
    for item in legacy:
        item.pop("images_inspected")
    path.write_text(json.dumps(legacy))
    assert all(item.images_inspected is None for item in load_provenance(path))
    assert not synth_set_usable(tmp_path)
