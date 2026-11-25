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
    )


def _guards(path: Path) -> None:
    (path / "views").mkdir()
    (path / "views/side.png").write_bytes(b"picture")
    write_provenance(path / "provenance.json", [_item()])
    (path / "proportion.json").write_text(json.dumps({"ok": True, "side_sha256": _item().sha256}))
    (path / "approved.json").write_text(
        json.dumps(
            {
                "approved_by": "user",
                "at": "2026-11-24",
                "views": {"side": _item().sha256},
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
        write_provenance(tmp_path / "provenance.json", [replace(_item(), critic_ok=False)])
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
    (tmp_path / "views/rear.png").write_bytes(b"unreviewed")
    assert not synth_set_usable(tmp_path)


def test_provenance_rejects_duplicate_views(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        write_provenance(tmp_path / "provenance.json", [_item(), _item()])
