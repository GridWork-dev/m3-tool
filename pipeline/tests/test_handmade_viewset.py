import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import pytest

from m3_pipeline.stages.lib.handmade import (
    HandmadeError,
    Pick,
    build_handmade_viewset,
    load_picks,
    main,
)
from m3_pipeline.stages.lib.viewset_io import load_viewset

INTERIOR = "e46-coupe-interior"


def _photo(directory: Path, name: str, data: bytes | None = None) -> Path:
    """A stand-in photo: the builder hashes and copies bytes, so no real image is needed."""
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data if data is not None else f"fake photo {name}".encode())
    return path


def _pick(path: Path, view: str, **overrides: Any) -> Pick:
    fields: dict[str, Any] = {
        "file": path,
        "view": view,
        "license_short": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0",
        "author": "Jane Doe",
        "page_url": f"https://commons.wikimedia.org/wiki/File:{path.name}",
    }
    fields.update(overrides)
    return Pick(**fields)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    doc: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return doc


def _interior_entry(tmp_path: Path, view: str, **overrides: Any):
    src = tmp_path / "src"
    path = build_handmade_viewset(
        tmp_path / "work",
        INTERIOR,
        "interior",
        [_pick(_photo(src, f"{view}.jpg"), view, **overrides)],
    )
    return load_viewset(tmp_path / "work", INTERIOR).components[view][0], path


def test_build_handmade_viewset_round_trips_through_load_viewset(tmp_path: Path) -> None:
    src, work = tmp_path / "src", tmp_path / "work"
    front = _photo(src, "front.jpg")
    side = _photo(src, "side.JPG")
    mask = _photo(src, "side-mask.png")
    path = build_handmade_viewset(
        work,
        "e46-coupe",
        "base-car",
        [
            _pick(side, "side_left", mask=mask, license_short="CC0", license_url=None, author=None),
            _pick(front, "front_34_left", drive_side="lhd"),
        ],
    )
    assert path == work / "refs/viewsets/e46-coupe.json"
    vs = load_viewset(work, "e46-coupe")
    assert (vs.subject, vs.kind, vs.components) == ("e46-coupe", "base-car", {})
    # Views come back in the photo lane's slot order, not in pick order.
    assert [v.view for v in vs.views] == ["front_34_left", "side_left"]
    front_ref, side_ref = vs.views
    assert front_ref.image_id == _sha(front)
    assert front_ref.image_path == work / f"refs/images/{_sha(front)[:2]}/{_sha(front)}.jpg"
    assert front_ref.image_path.read_bytes() == front.read_bytes()
    assert front_ref.cutout_path is None
    assert (front_ref.license_short, front_ref.author) == ("CC BY 4.0", "Jane Doe")
    assert front_ref.page_url == "https://commons.wikimedia.org/wiki/File:front.jpg"
    assert (front_ref.mirrored, front_ref.contains_text_risk, front_ref.seat) == (
        False,
        False,
        None,
    )
    # `.JPG` is stored as `.jpg`, and the mask under cutouts/<image sha>.png.
    assert side_ref.image_path.name == f"{_sha(side)}.jpg"
    assert side_ref.cutout_path == work / f"refs/cutouts/{_sha(side)}.png"
    assert side_ref.cutout_path is not None
    assert side_ref.cutout_path.read_bytes() == mask.read_bytes()
    assert (side_ref.license_short, side_ref.license_url, side_ref.author) == ("CC0", None, None)


def test_build_handmade_viewset_writes_the_photo_lanes_shape(tmp_path: Path) -> None:
    # The field names of ViewSet / ViewEntry in photo-tooling Task 8. The lane's `refs credits`
    # validates the stored file with its own model, so a missing key would break it.
    path = build_handmade_viewset(
        tmp_path / "work",
        "e46-coupe",
        "base-car",
        [_pick(_photo(tmp_path / "src", "a.jpg"), "front", license_short="CC BY-SA 4.0")],
    )
    doc = _json(path)
    assert set(doc) == {
        "subject", "kind", "views", "components", "missing", "all_cc_or_pd", "licenses", "rejected",
    }  # fmt: skip
    entry = doc["views"][0]
    assert set(entry) == {
        "view", "image_id", "image_path", "cutout_path", "mirrored", "score", "source_kind",
        "license_short", "license_url", "author", "page_url", "drive_side", "seat",
        "contains_text_risk",
    }  # fmt: skip
    assert entry["score"] == 0.0 and entry["source_kind"] == "local"
    assert doc["missing"] == ["front_34_left", "rear_34_right", "side_left", "rear"]
    assert doc["licenses"] == ["CC BY-SA 4.0"] and doc["all_cc_or_pd"] is True  # the lane's flag
    assert doc["rejected"] == {} and doc["components"] == {}


def test_all_cc_or_pd_is_false_for_an_unknown_license(tmp_path: Path) -> None:
    path = build_handmade_viewset(
        tmp_path / "work",
        "e46-coupe",
        "base-car",
        [_pick(_photo(tmp_path / "src", "a.jpg"), "front", license_short="unknown")],
    )
    assert _json(path)["all_cc_or_pd"] is False


def test_build_handmade_viewset_is_idempotent_by_hash(tmp_path: Path) -> None:
    src, work = tmp_path / "src", tmp_path / "work"
    a = _photo(src, "a.jpg")
    same_bytes = _photo(src, "copy-of-a.jpg", a.read_bytes())
    mask = _photo(src, "a-mask.png")
    picks = [_pick(a, "front", mask=mask), _pick(same_bytes, "rear")]
    path = build_handmade_viewset(work, "e46-coupe", "base-car", picks)
    first_json = path.read_bytes()
    first_files = sorted(p.relative_to(work) for p in work.rglob("*") if p.is_file())
    assert build_handmade_viewset(work, "e46-coupe", "base-car", picks) == path
    assert path.read_bytes() == first_json
    assert sorted(p.relative_to(work) for p in work.rglob("*") if p.is_file()) == first_files
    # Two picks of identical bytes are stored once: one image, one mask, one view-set file.
    assert len(first_files) == 3


def test_a_rebuild_replaces_the_view_set_and_keeps_earlier_images(tmp_path: Path) -> None:
    src, work = tmp_path / "src", tmp_path / "work"
    a, b = _photo(src, "a.jpg"), _photo(src, "b.jpg")
    build_handmade_viewset(work, "e46-coupe", "base-car", [_pick(a, "front")])
    build_handmade_viewset(work, "e46-coupe", "base-car", [_pick(b, "rear")])
    assert [v.view for v in load_viewset(work, "e46-coupe").views] == ["rear"]
    assert (work / f"refs/images/{_sha(a)[:2]}/{_sha(a)}.jpg").is_file()


def test_handmade_lhd_dash_is_neither_mirrored_nor_flagged(tmp_path: Path) -> None:
    entry, _ = _interior_entry(tmp_path, "interior_dash", drive_side="lhd")
    assert (entry.mirrored, entry.contains_text_risk, entry.drive_side) == (False, False, "lhd")


def test_handmade_rhd_whole_dash_is_mirrored_and_flagged(tmp_path: Path) -> None:
    entry, _ = _interior_entry(tmp_path, "interior_dash", drive_side="rhd")
    assert (entry.mirrored, entry.contains_text_risk, entry.drive_side) == (True, True, "rhd")


def test_handmade_rhd_door_follows_the_whole_dash_rule(tmp_path: Path) -> None:
    entry, _ = _interior_entry(tmp_path, "interior_door", drive_side="rhd")
    assert (entry.mirrored, entry.contains_text_risk) == (True, True)


@pytest.mark.parametrize("view", ["interior_gauges", "interior_steering"])
@pytest.mark.parametrize("side", ["lhd", "rhd", "unknown"])
def test_handmade_rhd_gauges_are_not_mirrored(tmp_path: Path, view: str, side: str) -> None:
    entry, _ = _interior_entry(tmp_path, view, drive_side=side)
    assert (entry.mirrored, entry.contains_text_risk, entry.drive_side) == (False, False, side)


def test_handmade_console_is_used_as_is_from_either_side(tmp_path: Path) -> None:
    entry, _ = _interior_entry(tmp_path, "interior_console", drive_side="rhd")
    assert (entry.mirrored, entry.contains_text_risk) == (False, False)


def test_handmade_seats_record_the_seat(tmp_path: Path) -> None:
    src, work = tmp_path / "src", tmp_path / "work"
    picks = [
        _pick(_photo(src, "s1.jpg"), "interior_seats", seat="driver", drive_side="rhd"),
        _pick(_photo(src, "s2.jpg"), "interior_seats", seat="passenger"),
        _pick(_photo(src, "s3.jpg"), "interior_seats"),
    ]
    build_handmade_viewset(work, INTERIOR, "interior", picks)
    seats = load_viewset(work, INTERIOR).components["interior_seats"]
    assert [s.seat for s in seats] == ["driver", "passenger", "unknown"]  # pick order is rank
    assert not any(s.mirrored or s.contains_text_risk for s in seats)


def test_interior_components_are_grouped_and_ordered(tmp_path: Path) -> None:
    src, work = tmp_path / "src", tmp_path / "work"
    picks = [
        _pick(_photo(src, "g.jpg"), "interior_gauges"),
        _pick(_photo(src, "d1.jpg"), "interior_dash"),
        _pick(_photo(src, "d2.jpg"), "interior_dash"),
    ]
    path = build_handmade_viewset(work, INTERIOR, "interior", picks)
    vs = load_viewset(work, INTERIOR)
    assert vs.kind == "interior" and vs.views == ()
    assert list(vs.components) == ["interior_dash", "interior_gauges"]
    assert [r.image_id for r in vs.components["interior_dash"]] == [
        _sha(src / "d1.jpg"),
        _sha(src / "d2.jpg"),
    ]
    doc = _json(path)
    assert doc["views"] == []
    assert doc["missing"] == [  # every component under three entries, in the lane's order
        "interior_dash", "interior_gauges", "interior_steering", "interior_seats",
        "interior_door", "interior_console",
    ]  # fmt: skip


def test_a_component_with_three_pictures_is_not_missing(tmp_path: Path) -> None:
    src = tmp_path / "src"
    picks = [_pick(_photo(src, f"d{i}.jpg"), "interior_dash") for i in range(3)]
    path = build_handmade_viewset(tmp_path / "work", INTERIOR, "interior", picks)
    assert "interior_dash" not in _json(path)["missing"]


@pytest.mark.parametrize(
    "kind,view",
    [("base-car", "interior_dash"), ("interior", "front"), ("base-car", "top"), ("base-car", "x")],
)
def test_a_view_that_does_not_belong_to_the_kind_is_refused(
    tmp_path: Path, kind: Literal["base-car", "interior"], view: str
) -> None:
    subject = "e46-coupe-interior" if kind == "interior" else "e46-coupe"
    pick = _pick(_photo(tmp_path / "src", "a.jpg"), view)
    with pytest.raises(HandmadeError, match=view):
        build_handmade_viewset(tmp_path / "work", subject, kind, [pick])
    assert not (tmp_path / "work").exists()  # refused before anything was written


@pytest.mark.parametrize(
    "subject,kind",
    [("e46-coupe", "interior"), ("e46-coupe-interior", "base-car"), ("product-x", "base-car")],
)
def test_a_subject_that_does_not_fit_the_kind_is_refused(
    tmp_path: Path, subject: str, kind: Literal["base-car", "interior"]
) -> None:
    pick = _pick(_photo(tmp_path / "src", "a.jpg"), "front")
    with pytest.raises(HandmadeError, match="subject"):
        build_handmade_viewset(tmp_path / "work", subject, kind, [pick])


def test_the_same_exterior_view_twice_is_refused(tmp_path: Path) -> None:
    src = tmp_path / "src"
    picks = [_pick(_photo(src, "a.jpg"), "front"), _pick(_photo(src, "b.jpg"), "front")]
    with pytest.raises(HandmadeError, match="front"):
        build_handmade_viewset(tmp_path / "work", "e46-coupe", "base-car", picks)


@pytest.mark.parametrize("view", ["interior_dash", "interior_door"])
def test_a_whole_dash_or_door_must_say_which_side_drives(tmp_path: Path, view: str) -> None:
    pick = _pick(_photo(tmp_path / "src", "a.jpg"), view, drive_side="unknown")
    with pytest.raises(HandmadeError, match="drive side"):
        build_handmade_viewset(tmp_path / "work", INTERIOR, "interior", [pick])


def test_a_drive_side_other_than_lhd_rhd_or_unknown_is_refused(tmp_path: Path) -> None:
    pick = _pick(_photo(tmp_path / "src", "a.jpg"), "interior_gauges", drive_side="left")
    with pytest.raises(HandmadeError, match="drive_side"):
        build_handmade_viewset(tmp_path / "work", INTERIOR, "interior", [pick])


def test_a_seat_is_only_for_seat_views_and_must_be_a_known_role(tmp_path: Path) -> None:
    src = tmp_path / "src"
    with pytest.raises(HandmadeError, match="seat"):
        build_handmade_viewset(
            tmp_path / "w1", INTERIOR, "interior",
            [_pick(_photo(src, "a.jpg"), "interior_dash", seat="driver")],
        )  # fmt: skip
    with pytest.raises(HandmadeError, match="seat"):
        build_handmade_viewset(
            tmp_path / "w2", INTERIOR, "interior",
            [_pick(_photo(src, "b.jpg"), "interior_seats", seat="back")],
        )  # fmt: skip


def test_a_missing_photo_or_an_unsupported_extension_is_refused(tmp_path: Path) -> None:
    src, work = tmp_path / "src", tmp_path / "work"
    with pytest.raises(HandmadeError, match="nope.jpg"):
        build_handmade_viewset(work, "e46-coupe", "base-car", [_pick(src / "nope.jpg", "front")])
    gif = _photo(src, "a.gif")
    with pytest.raises(HandmadeError, match=r"\.gif"):
        build_handmade_viewset(work, "e46-coupe", "base-car", [_pick(gif, "front")])
    jpg = _photo(src, "b.jpg")
    with pytest.raises(HandmadeError, match="mask"):
        build_handmade_viewset(work, "e46-coupe", "base-car", [_pick(jpg, "front", mask=gif)])


def test_jpeg_png_webp_and_avif_extensions_are_kept_and_jpeg_becomes_jpg(tmp_path: Path) -> None:
    src, work = tmp_path / "src", tmp_path / "work"
    names = {"a.jpeg": "jpg", "b.png": "png", "c.webp": "webp", "d.avif": "avif"}
    views = ["front", "rear", "side_left", "front_34_left"]
    picks = [_pick(_photo(src, n), v) for n, v in zip(names, views, strict=True)]
    build_handmade_viewset(work, "e46-coupe", "base-car", picks)
    got = {v.view: v.image_path.suffix for v in load_viewset(work, "e46-coupe").views}
    assert got == {
        "front": ".jpg", "rear": ".png", "side_left": ".webp", "front_34_left": ".avif",
    }  # fmt: skip


def _toml(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, "utf-8")
    return path


def test_load_picks_reads_pick_tables_and_resolves_files_next_to_the_toml(tmp_path: Path) -> None:
    toml = _toml(
        tmp_path / "spike/picks.toml",
        """
[[pick]]
file = "photos/a.jpg"
view = "front"
license_short = "CC BY 4.0"
license_url = "https://creativecommons.org/licenses/by/4.0"
author = "Jane Doe"
page_url = "https://commons.wikimedia.org/wiki/File:A.jpg"

[[pick]]
file = "/abs/b.jpg"
view = "interior_seats"
license_short = "CC0"
page_url = "https://commons.wikimedia.org/wiki/File:B.jpg"
drive_side = "rhd"
seat = "driver"
mask = "photos/b-mask.png"
""",
    )
    first, second = load_picks(toml)
    assert first == Pick(
        file=tmp_path / "spike/photos/a.jpg",
        view="front",
        license_short="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0",
        author="Jane Doe",
        page_url="https://commons.wikimedia.org/wiki/File:A.jpg",
    )
    assert (first.drive_side, first.seat, first.mask) == ("lhd", None, None)
    assert second.file == Path("/abs/b.jpg") and second.mask == tmp_path / "spike/photos/b-mask.png"
    assert (second.license_url, second.author) == (None, None)
    assert (second.drive_side, second.seat) == ("rhd", "driver")


@pytest.mark.parametrize("key", ["file", "view", "license_short", "page_url"])
def test_load_picks_missing_key_names_the_file_and_key(tmp_path: Path, key: str) -> None:
    fields = {"file": "a.jpg", "view": "front", "license_short": "CC0", "page_url": "https://x/y"}
    del fields[key]
    body = "[[pick]]\n" + "".join(f'{k} = "{v}"\n' for k, v in fields.items())
    toml = _toml(tmp_path / "picks-e46-coupe.toml", body)
    with pytest.raises(HandmadeError, match=rf"picks-e46-coupe\.toml.*pick\[0\]\.{key}"):
        load_picks(toml)


def test_load_picks_refuses_a_misspelled_key(tmp_path: Path) -> None:
    # `drive-side` would otherwise be ignored and the pick treated as LHD.
    toml = _toml(
        tmp_path / "p.toml",
        '[[pick]]\nfile = "a.jpg"\nview = "front"\nlicense_short = "CC0"\n'
        'page_url = "https://x/y"\ndrive-side = "rhd"\n',
    )
    with pytest.raises(HandmadeError, match=r"p\.toml.*drive-side"):
        load_picks(toml)


def test_load_picks_refuses_an_empty_file_and_bad_toml(tmp_path: Path) -> None:
    with pytest.raises(HandmadeError, match=r"empty\.toml.*pick"):
        load_picks(_toml(tmp_path / "empty.toml", "# nothing\n"))
    with pytest.raises(HandmadeError, match=r"bad\.toml"):
        load_picks(_toml(tmp_path / "bad.toml", "[[pick"))
    with pytest.raises(HandmadeError, match=r"absent\.toml"):
        load_picks(tmp_path / "absent.toml")


def _repo_env(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    monkeypatch.setenv("M3_REPO_ROOT", str(repo))


def test_main_builds_a_view_set_from_a_picks_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_env(monkeypatch, tmp_path / "repo")
    photo = _photo(tmp_path / "spike", "a.jpg")
    toml = _toml(
        tmp_path / "spike/picks.toml",
        f'[[pick]]\nfile = "{photo.name}"\nview = "front"\nlicense_short = "CC0"\n'
        'page_url = "https://commons.wikimedia.org/wiki/File:A.jpg"\n',
    )
    work = tmp_path / "work"
    assert main([str(work), "e46-coupe", "base-car", str(toml)]) == 0
    assert "front" in capsys.readouterr().out
    assert [v.view for v in load_viewset(work, "e46-coupe").views] == ["front"]


def test_main_refuses_a_work_dir_inside_the_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "repo"
    _repo_env(monkeypatch, repo)
    photo = _photo(tmp_path / "spike", "a.jpg")
    toml = _toml(
        tmp_path / "spike/picks.toml",
        f'[[pick]]\nfile = "{photo.name}"\nview = "front"\nlicense_short = "CC0"\npage_url = "u"\n',
    )
    assert main([str(repo / "work"), "e46-coupe", "base-car", str(toml)]) == 1
    assert "inside the repo" in capsys.readouterr().err
    assert not (repo / "work").exists()


def test_main_reports_a_bad_picks_file_and_a_bad_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _repo_env(monkeypatch, tmp_path / "repo")
    assert main([str(tmp_path / "work"), "e46-coupe", "base-car", str(tmp_path / "no.toml")]) == 1
    assert "no.toml" in capsys.readouterr().err
    assert main([str(tmp_path / "work"), "e46-coupe", "product", "picks.toml"]) == 2
    assert main([str(tmp_path / "work"), "e46-coupe"]) == 2
    assert "usage" in capsys.readouterr().err
