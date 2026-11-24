import json
from pathlib import Path
from typing import Any

import pytest

from m3_pipeline.stages.lib.viewset_io import ViewSetError, load_viewset


def _id(n: int) -> str:
    return f"{n:064x}"


def _entry(view: str, n: int, **overrides: Any) -> dict[str, Any]:
    """One entry exactly as the photo lane's `ViewEntry.model_dump()` writes it."""
    entry: dict[str, Any] = {
        "view": view,
        "image_id": _id(n),
        "image_path": f"refs/images/{_id(n)[:2]}/{_id(n)}.jpg",
        "cutout_path": None,
        "mirrored": False,
        "score": 61.5,
        "source_kind": "commons",
        "license_short": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0",
        "author": "Jane Doe",
        "page_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
        "drive_side": "lhd",
        "seat": None,
        "contains_text_risk": False,
    }
    entry.update(overrides)
    return entry


def _write(work_dir: Path, subject: str, **fields: Any) -> Path:
    doc: dict[str, Any] = {
        "subject": subject,
        "kind": "base-car",
        "views": [],
        "components": {},
        "missing": [],
        "all_cc_or_pd": True,
        "licenses": ["CC BY 4.0"],
        "rejected": {},
    }
    doc.update(fields)
    path = work_dir / "refs/viewsets" / f"{subject}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), "utf-8")
    return path


def test_load_viewset_reads_exterior_views_and_resolves_paths_under_work_dir(
    tmp_path: Path,
) -> None:
    mask = f"refs/cutouts/{_id(2)}.png"
    _write(
        tmp_path,
        "e46-coupe",
        views=[
            _entry("front_34_left", 1),
            _entry(
                "side_left",
                2,
                cutout_path=mask,
                mirrored=True,
                license_short="CC0",
                license_url=None,
                author=None,
                page_url=None,
            ),
        ],
    )
    vs = load_viewset(tmp_path, "e46-coupe")
    assert (vs.subject, vs.kind, vs.components) == ("e46-coupe", "base-car", {})
    first, second = vs.views
    assert first.view == "front_34_left" and first.image_id == _id(1)
    assert first.image_path == tmp_path / f"refs/images/{_id(1)[:2]}/{_id(1)}.jpg"
    assert first.cutout_path is None and first.mirrored is False
    assert first.license_short == "CC BY 4.0" and first.author == "Jane Doe"
    assert first.page_url == "https://commons.wikimedia.org/wiki/File:Example.jpg"
    assert (first.drive_side, first.seat, first.contains_text_risk) == ("lhd", None, False)
    assert second.cutout_path == tmp_path / mask and second.mirrored is True
    assert (second.license_url, second.author, second.page_url) == (None, None, None)
    assert vs.entries() == [first, second]


def test_load_viewset_reads_interior_components(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "e46-coupe-interior",
        kind="interior",
        components={
            "interior_dash": [_entry("interior_dash", 1, mirrored=True, contains_text_risk=True)],
            "interior_seats": [
                _entry("interior_seats", 2, seat="driver"),
                _entry("interior_seats", 3, seat="passenger"),
            ],
        },
    )
    vs = load_viewset(tmp_path, "e46-coupe-interior")
    assert vs.kind == "interior" and vs.views == ()
    assert list(vs.components) == ["interior_dash", "interior_seats"]
    dash = vs.components["interior_dash"][0]
    assert (dash.mirrored, dash.contains_text_risk) == (True, True)
    assert [r.seat for r in vs.components["interior_seats"]] == ["driver", "passenger"]
    assert [r.image_id for r in vs.entries()] == [_id(1), _id(2), _id(3)]


def test_load_viewset_ignores_keys_it_does_not_use(tmp_path: Path) -> None:
    _write(tmp_path, "e46-coupe", views=[_entry("front", 1, future_field="x")], extra=[1])
    assert load_viewset(tmp_path, "e46-coupe").views[0].view == "front"


@pytest.mark.parametrize(
    "bad", ["../../../etc/passwd", "refs/../../outside.jpg", "/etc/passwd", "refs/images/../.."]
)
def test_load_viewset_rejects_a_path_escaping_work_dir(tmp_path: Path, bad: str) -> None:
    work = tmp_path / "work"
    _write(work, "e46-coupe", views=[_entry("front", 1, image_path=bad)])
    with pytest.raises(ViewSetError, match=r"image_path"):
        load_viewset(work, "e46-coupe")


def test_load_viewset_rejects_a_cutout_path_escaping_work_dir(tmp_path: Path) -> None:
    _write(tmp_path, "e46-coupe", views=[_entry("front", 1, cutout_path="../mask.png")])
    with pytest.raises(ViewSetError, match=r"cutout_path"):
        load_viewset(tmp_path, "e46-coupe")


def test_load_viewset_missing_file_names_the_expected_path(tmp_path: Path) -> None:
    with pytest.raises(ViewSetError) as info:
        load_viewset(tmp_path, "e46-coupe")
    assert str(tmp_path / "refs/viewsets/e46-coupe.json") in str(info.value)


def test_load_viewset_invalid_json_names_the_file(tmp_path: Path) -> None:
    path = _write(tmp_path, "e46-coupe")
    path.write_text("{not json", "utf-8")
    with pytest.raises(ViewSetError, match=r"e46-coupe\.json"):
        load_viewset(tmp_path, "e46-coupe")


def test_load_viewset_missing_top_level_key_names_the_file_and_key(tmp_path: Path) -> None:
    path = _write(tmp_path, "e46-coupe")
    doc = json.loads(path.read_text("utf-8"))
    del doc["kind"]
    path.write_text(json.dumps(doc), "utf-8")
    with pytest.raises(ViewSetError, match=r"e46-coupe\.json.*kind"):
        load_viewset(tmp_path, "e46-coupe")


@pytest.mark.parametrize(
    "key",
    [
        "view",
        "image_id",
        "image_path",
        "cutout_path",
        "mirrored",
        "license_short",
        "license_url",
        "author",
        "page_url",
        "drive_side",
        "seat",
        "contains_text_risk",
    ],
)
def test_load_viewset_missing_entry_key_names_the_file_and_key(tmp_path: Path, key: str) -> None:
    entry = _entry("front", 1)
    del entry[key]
    _write(tmp_path, "e46-coupe", views=[entry])
    with pytest.raises(ViewSetError, match=rf"e46-coupe\.json.*views\[0\]\.{key}"):
        load_viewset(tmp_path, "e46-coupe")


def test_load_viewset_names_the_component_of_a_bad_interior_entry(tmp_path: Path) -> None:
    entry = _entry("interior_dash", 1)
    del entry["drive_side"]
    _write(tmp_path, "e46-coupe-interior", kind="interior", components={"interior_dash": [entry]})
    with pytest.raises(ViewSetError, match=r"components\.interior_dash\[0\]\.drive_side"):
        load_viewset(tmp_path, "e46-coupe-interior")


@pytest.mark.parametrize(
    "overrides",
    [{"mirrored": "yes"}, {"image_id": 7}, {"contains_text_risk": 0}, {"seat": 3}],
)
def test_load_viewset_rejects_a_value_of_the_wrong_type(
    tmp_path: Path, overrides: dict[str, Any]
) -> None:
    _write(tmp_path, "e46-coupe", views=[_entry("front", 1, **overrides)])
    with pytest.raises(ViewSetError, match=rf"views\[0\]\.{next(iter(overrides))}"):
        load_viewset(tmp_path, "e46-coupe")


def test_load_viewset_rejects_a_file_for_another_subject(tmp_path: Path) -> None:
    path = _write(tmp_path, "e46-coupe-interior", kind="interior")
    path.rename(path.with_name("e46-coupe.json"))
    with pytest.raises(ViewSetError, match=r"e46-coupe-interior"):
        load_viewset(tmp_path, "e46-coupe")
