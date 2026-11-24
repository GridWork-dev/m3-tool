from pathlib import Path
from typing import Any

import pytest
from refs_helpers import make_labels, make_record

from m3_pipeline.refs.models import ImageRecord
from m3_pipeline.refs.viewsets import (
    EXTERIOR_PRIORITY,
    NEVER_MIRRORED,
    ViewsetPolicy,
    build_viewset,
    is_cc_or_pd,
    pick_spread,
    score_image,
)

INT = "e46-coupe-interior"


def rec(i: int, view: str, lab: dict[str, Any] | None = None, **kw: Any) -> ImageRecord:
    return make_record(id=f"{i:064x}", labels=make_labels(view=view, **(lab or {})), **kw)


def irec(i: int, view: str, side: str, **lab: Any) -> ImageRecord:
    return rec(i, view, lab={"drive_side": side, **lab})


def test_exterior_picks_priority_views_in_order() -> None:
    vs = build_viewset(
        "e46-coupe",
        [
            rec(i, v)
            for i, v in enumerate(
                ["rear", "front", "side_left", "rear_34_right", "front_34_left", "top"], 1
            )
        ],
    )
    assert [e.view for e in vs.views] == list(EXTERIOR_PRIORITY)
    assert vs.missing == [] and not any(e.mirrored for e in vs.views)


def test_missing_left_view_is_filled_by_mirroring_the_right() -> None:
    right = rec(1, "side_right")
    vs = build_viewset("e46-coupe", [right])
    assert [(e.view, e.mirrored, e.image_id) for e in vs.views] == [("side_left", True, right.id)]
    assert vs.missing == [v for v in EXTERIOR_PRIORITY if v != "side_left"]


def test_direct_view_beats_a_mirrored_one() -> None:
    left, right = rec(1, "side_left", {"quality": 1}), rec(2, "side_right", {"quality": 5})
    entry = build_viewset("e46-coupe", [right, left]).views[0]
    assert entry.image_id == left.id and not entry.mirrored


def test_product_sets_never_mirror() -> None:
    vs = build_viewset("product-wheel-a", [rec(1, "product_side"), rec(2, "product_34")])
    assert [e.view for e in vs.views] == ["product_34", "product_side"]
    assert not any(e.mirrored for e in vs.entries())
    assert vs.missing == ["product_front", "product_detail"]


def test_exterior_mirroring_is_unchanged_and_carries_no_text_risk_flag() -> None:
    vs = build_viewset("e46-coupe", [rec(1, "front_34_right"), rec(2, "rear_34_left")])
    assert [e.view for e in vs.views] == ["front_34_left", "rear_34_right"]
    assert all(e.mirrored and not e.contains_text_risk for e in vs.entries())


def test_each_interior_component_takes_up_to_five_views() -> None:
    vs = build_viewset(
        INT,
        [irec(i, "interior_steering", "lhd") for i in range(1, 8)]
        + [irec(20, "interior_seats", "lhd", seat="driver")],
    )
    assert len(vs.components["interior_steering"]) == 5
    assert len(vs.components["interior_seats"]) == 1 and vs.views == []


def test_interior_component_under_min_views_is_reported_missing() -> None:
    vs = build_viewset(
        INT,
        [irec(i, "interior_console", "lhd") for i in (1, 2)]
        + [irec(i, "interior_steering", "lhd") for i in (3, 4, 5)],
    )
    assert len(vs.components["interior_console"]) == 2
    assert {"interior_console", "interior_dash"} <= set(vs.missing)
    assert "interior_steering" not in vs.missing


def test_spread_prefers_visually_distinct_images_then_fills_by_rank() -> None:
    a, b, c = (
        make_record(id=f"{i:064x}", phash=h)
        for i, h in ((1, "0" * 16), (2, "0" * 15 + "1"), (3, "f" * 16))
    )
    assert [r.id for r in pick_spread([a, b, c], 2)] == [a.id, c.id]
    assert [r.id for r in pick_spread([a, b, c], 3)] == [a.id, c.id, b.id]
    assert [r.id for r in pick_spread([b, c], 1, taken=[a])] == [c.id]


def test_seats_with_different_seat_labels_count_as_distinct() -> None:
    d1, d2, p = [
        rec(i, "interior_seats", {"seat": seat}, phash="0" * 16)
        for i, seat in ((1, "driver"), (2, "driver"), (3, "passenger"))
    ]
    assert [r.id for r in pick_spread([d1, d2, p], 2)] == [d1.id, p.id]


def test_rhd_steering_gauges_and_console_are_used_as_is_and_never_mirrored() -> None:
    vs = build_viewset(
        INT,
        [
            irec(i, view, "rhd")
            for i, view in enumerate(
                ("interior_steering", "interior_gauges", "interior_console"), 1
            )
        ],
    )
    assert {
        c: [(e.mirrored, e.contains_text_risk) for e in es] for c, es in vs.components.items()
    } == {
        "interior_gauges": [(False, False)],
        "interior_steering": [(False, False)],
        "interior_console": [(False, False)],
    }


@pytest.mark.parametrize("side", ["lhd", "rhd", "unknown"])
def test_steering_and_gauges_are_never_mirrored_whatever_the_drive_side(side: str) -> None:
    vs = build_viewset(INT, [irec(1, v, side) for v in NEVER_MIRRORED])
    assert set(vs.components) == set(NEVER_MIRRORED)
    assert not any(e.mirrored for e in vs.entries())


def test_lhd_whole_dash_entries_rank_before_rhd_ones_which_are_mirrored_and_flagged() -> None:
    es = build_viewset(
        INT,
        [irec(1, "interior_dash", "lhd", quality=2), irec(2, "interior_dash", "rhd", quality=5)],
    ).components["interior_dash"]
    assert [(e.image_id, e.mirrored, e.contains_text_risk) for e in es] == [
        (f"{1:064x}", False, False),
        (f"{2:064x}", True, True),
    ]


def test_rhd_whole_dash_is_used_only_mirrored_and_flagged_when_no_lhd_exists() -> None:
    e = build_viewset(INT, [irec(2, "interior_dash", "rhd")]).components["interior_dash"][0]
    assert (e.mirrored, e.contains_text_risk, e.drive_side) == (True, True, "rhd")


def test_whole_dash_with_unknown_drive_side_is_skipped_and_counted() -> None:
    vs = build_viewset(INT, [irec(1, "interior_dash", "unknown")])
    assert "interior_dash" not in vs.components and vs.rejected["drive_side_unknown"] == 1


def test_seats_are_valid_from_either_drive_side_and_record_which_seat() -> None:
    e = build_viewset(INT, [irec(1, "interior_seats", "rhd", seat="driver")]).components[
        "interior_seats"
    ][0]
    assert (e.seat, e.mirrored, e.contains_text_risk) == ("driver", False, False)


def test_door_follows_the_whole_dash_rule() -> None:
    vs = build_viewset(
        INT,
        [
            irec(1, "interior_door", "rhd", quality=5),
            irec(2, "interior_door", "lhd", quality=2),
            irec(3, "interior_door", "unknown"),
        ],
    )
    assert [
        (e.image_id, e.mirrored, e.contains_text_risk) for e in vs.components["interior_door"]
    ] == [(f"{2:064x}", False, False), (f"{1:064x}", True, True)]
    assert vs.rejected == {"drive_side_unknown": 1}


def test_best_score_wins_and_ties_break_by_lower_id() -> None:
    hi, lo = rec(1, "front", {"quality": 5}), rec(2, "front", {"quality": 3})
    assert build_viewset("e46-coupe", [lo, hi]).views[0].image_id == hi.id
    assert score_image(rec(1, "front")) > score_image(rec(1, "front", {"occlusion": "minor"}))
    assert build_viewset("e46-coupe", [rec(2, "front"), rec(1, "front")]).views[0].image_id == hi.id
    closed, open_ = rec(1, "front"), rec(2, "front", license_short="CC0")
    assert build_viewset("e46-coupe", [closed, open_]).views[0].image_id == open_.id


def test_rejected_images_are_never_selected_and_are_counted() -> None:
    vs = build_viewset(
        "e46-coupe",
        [
            rec(1, "front", {"stock": False}),
            rec(2, "rear", {"body": "sedan"}),
            rec(3, "side_left", {"occlusion": "major"}),
        ],
    )
    assert vs.views == [] and vs.rejected == {"modified": 1, "wrong_body": 1, "major_occlusion": 1}


def test_exterior_set_is_capped_at_max_views_and_lists_missing_views() -> None:
    vs = build_viewset(
        "e46-coupe",
        [rec(i, v) for i, v in enumerate(EXTERIOR_PRIORITY, 1)],
        policy=ViewsetPolicy(max_views=2),
    )
    assert [e.view for e in vs.views] == list(EXTERIOR_PRIORITY[:2])
    assert vs.missing == list(EXTERIOR_PRIORITY[2:])


def test_empty_candidates_give_an_empty_set_not_an_error() -> None:
    vs = build_viewset("e46-coupe", [])
    assert vs.views == [] and vs.components == {} and vs.all_cc_or_pd is False


@pytest.mark.parametrize(
    "name,ok",
    [
        ("CC BY-SA 4.0", True),
        ("CC BY 2.0", True),
        ("CC0", True),
        ("Public domain", True),
        ("PD-USGov", True),
        ("CC BY-NC 4.0", False),
        ("CC BY-ND 2.0", False),
        ("GFDL 1.2", False),
        ("unknown", False),
        ("", False),
    ],
)
def test_is_cc_or_pd(name: str, ok: bool) -> None:
    assert is_cc_or_pd(name) is ok


def test_unknown_license_blocks_all_cc_or_pd() -> None:
    open_ = rec(1, "front", license_short="CC BY-SA 4.0")
    unk = rec(2, "rear", license_short="unknown", source_kind="commons")
    assert build_viewset("e46-coupe", [open_]).all_cc_or_pd
    assert not build_viewset("e46-coupe", [open_, unk]).all_cc_or_pd


def test_paths_are_relative_and_cutouts_attach_only_for_known_ids() -> None:
    a, b = rec(1, "front"), rec(2, "rear")
    vs = build_viewset("e46-coupe", [a, b], cutouts=[a.id, "f" * 64])
    assert vs.views[0].image_path == f"refs/images/{a.id[:2]}/{a.id}.jpg"
    assert not any(Path(e.image_path).is_absolute() for e in vs.entries())
    assert vs.views[0].cutout_path == f"refs/cutouts/{a.id}.png"
    assert vs.views[1].cutout_path is None
