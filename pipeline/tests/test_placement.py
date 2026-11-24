import ast
import itertools
import math
import re
import sys
from collections.abc import Sequence

import pytest

from m3_pipeline.config import load_settings
from m3_pipeline.stages.lib.dims import Dimensions, tire_radius_m, tire_width_m
from m3_pipeline.stages.lib.frames import Vec, lhw_to_blender_xyz
from m3_pipeline.stages.lib.placement import (
    Orientation,
    ScaleRefused,
    apply_orientation,
    axis_scales,
    body_width_m,
    compose_scales,
    decimate_ratio,
    interior_fit,
    module_cut_planes,
    mount_anchor_positions,
    propose_orientation,
    wheel_anchor_positions,
    wheel_cylinders,
)

REPO = load_settings({}).repo_root
CONTRACT_TS = (REPO / "src/lib/asset-contract.ts").read_text("utf-8")
LIB = REPO / "pipeline/src/m3_pipeline/stages/lib"

E46 = Dimensions(
    length_mm=4492,
    width_mm=1780,
    height_mm=1372,
    wheelbase_mm=2731,
    track_front_mm=1508,
    track_rear_mm=1525,
)
FRONT_TIRE, REAR_TIRE = "225/45ZR18", "255/40ZR18"
FRONT_R, REAR_R = tire_radius_m(FRONT_TIRE), tire_radius_m(REAR_TIRE)
EYE: Vec = (-0.37, 1.1, 0.0)
LENGTH_M, HEIGHT_M, WHEELBASE_M = 4.492, 1.372, 2.731


def _quoted(block: str) -> list[str]:
    return re.findall(r"'([^']+)'", block)


def _box_surface(lo: Vec, hi: Vec, step: float = 0.08) -> list[Vec]:
    """Points on the six faces of an axis-aligned box, on a grid, edges included."""

    def ticks(a: float, b: float) -> list[float]:
        n = max(1, round((b - a) / step))
        return [a + (b - a) * i / n for i in range(n + 1)]

    xs, ys, zs = (ticks(lo[i], hi[i]) for i in range(3))
    points: set[Vec] = set()
    for x, y in itertools.product(xs, ys):
        points |= {(x, y, lo[2]), (x, y, hi[2])}
    for x, z in itertools.product(xs, zs):
        points |= {(x, lo[1], z), (x, hi[1], z)}
    for y, z in itertools.product(ys, zs):
        points |= {(lo[0], y, z), (hi[0], y, z)}
    return sorted(points)


def _coupe_cloud() -> list[Vec]:
    """A coupe in the oriented Blender frame: x width, y length with the nose at +y, z up.
    Sills are wider than the greenhouse, and the cabin sits rearward (toward -y)."""
    body = _box_surface((-0.89, -2.246, 0.15), (0.89, 2.246, 0.85))
    cabin = _box_surface((-0.70, -1.40, 0.85), (0.70, 0.50, 1.40))
    return body + cabin


def _rotations() -> list[tuple[Vec, Vec, Vec]]:
    """The 24 proper rotations that permute and flip the axes, as matrix rows."""
    found: list[tuple[Vec, Vec, Vec]] = []
    for perm in itertools.permutations(range(3)):
        for signs in itertools.product((1.0, -1.0), repeat=3):

            def row(i: int, perm: tuple[int, ...] = perm, signs: tuple[float, ...] = signs) -> Vec:
                return (
                    signs[i] if perm[i] == 0 else 0.0,
                    signs[i] if perm[i] == 1 else 0.0,
                    signs[i] if perm[i] == 2 else 0.0,
                )

            a, b, c = row(0), row(1), row(2)
            if _triple(a, b, c) > 0:
                found.append((a, b, c))
    return found


def _triple(a: Vec, b: Vec, c: Vec) -> float:
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _rotate(vertices: Sequence[Vec], rows: tuple[Vec, Vec, Vec]) -> list[Vec]:
    def dot(row: Vec, v: Vec) -> float:
        return row[0] * v[0] + row[1] * v[1] + row[2] * v[2]

    return [(dot(rows[0], v), dot(rows[1], v), dot(rows[2], v)) for v in vertices]


def _det(o: Orientation) -> float:
    # The images of the three unit vectors are the columns of the rotation, and a matrix has the
    # determinant of its transpose.
    x, y, z = (apply_orientation([axis], o)[0] for axis in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
    return _triple(x, y, z)


def test_there_are_24_proper_rotations() -> None:
    assert len(_rotations()) == 24


def test_propose_orientation_finds_up_and_nose_for_every_axis_permutation() -> None:
    original = _coupe_cloud()
    for rows in _rotations():
        imported = _rotate(original, rows)
        proposal = propose_orientation(imported)
        assert apply_orientation(imported, proposal) == original, (rows, proposal)


def test_propose_orientation_reads_a_coupe_that_is_already_upright() -> None:
    assert propose_orientation(_coupe_cloud()) == Orientation(up="+z", nose="+y")


def test_apply_orientation_is_a_proper_rotation() -> None:
    axes = [f"{sign}{axis}" for sign in "+-" for axis in "xyz"]
    pairs = [(up, nose) for up in axes for nose in axes if up[1] != nose[1]]
    assert len(pairs) == 24
    for up, nose in pairs:
        assert _det(Orientation(up=up, nose=nose)) == pytest.approx(1.0), (up, nose)


def test_apply_orientation_refuses_an_up_and_nose_on_one_axis() -> None:
    with pytest.raises(ValueError, match="axis"):
        apply_orientation([(0.0, 0.0, 1.0)], Orientation(up="+z", nose="-z"))
    with pytest.raises(ValueError, match="'z'"):
        apply_orientation([(0.0, 0.0, 1.0)], Orientation(up="+q", nose="+y"))


def _mesh_with_mirrors(lift: float = 0.0, mirror_reach: float = 0.975) -> list[Vec]:
    """Contract frame. Tires and sills (0 to 0.25 m) are narrower than the body, the body
    (0.25 to 1.0 m) is 1.78 m wide, the greenhouse is narrower, and a door mirror at 1.0 m
    reaches `mirror_reach` on each side."""
    parts = [
        _box_surface((-0.75, 0.0, -2.2), (0.75, 0.25, 2.2)),
        _box_surface((-0.89, 0.25, -2.246), (0.89, 1.0, 2.246)),
        _box_surface((-0.70, 1.0, -0.9), (0.70, 1.372, 0.6)),
        _box_surface((-mirror_reach, 0.97, -0.6), (-0.89, 1.03, -0.5)),
        _box_surface((0.89, 0.97, -0.6), (mirror_reach, 1.03, -0.5)),
    ]
    return [(x, y + lift, z) for part in parts for (x, y, z) in part]


def test_body_width_ignores_door_mirrors() -> None:
    mesh = _mesh_with_mirrors()
    assert 2 * max(abs(x) for x, _, _ in mesh) == pytest.approx(1.95)  # the stubs are there
    assert body_width_m(mesh) == pytest.approx(1.78, abs=0.005)


def test_body_width_band_is_measured_from_the_lowest_point() -> None:
    lifted = _mesh_with_mirrors(lift=0.7)
    # A band read in absolute y would see only the narrow tires of the lifted mesh.
    assert body_width_m(lifted) == pytest.approx(body_width_m(_mesh_with_mirrors()), abs=1e-9)
    assert body_width_m(lifted) == pytest.approx(1.78, abs=0.005)


def test_body_width_does_not_depend_on_where_the_mesh_sits_in_x() -> None:
    mesh = [(x + 0.4, y, z) for x, y, z in _mesh_with_mirrors()]
    assert body_width_m(mesh) == pytest.approx(1.78, abs=0.005)


def test_body_width_with_nothing_in_the_band_is_an_error() -> None:
    with pytest.raises(ValueError, match="band"):
        body_width_m([(0.0, 0.0, 0.0), (0.5, 0.1, 0.0)], y_band=(0.30, 0.90))


def test_axis_scales_hit_the_data_dimensions_exactly() -> None:
    length, height, width = axis_scales((4.492, 1.40, 1.80), E46)
    assert length == pytest.approx(1.0, abs=1e-3)
    assert height == pytest.approx(0.98, abs=1e-3)
    assert width == pytest.approx(0.9889, abs=1e-3)
    for factor, measured, expected in zip(
        (length, height, width), (4.492, 1.40, 1.80), (4.492, 1.372, 1.78), strict=True
    ):
        assert factor * measured == pytest.approx(expected, abs=1e-9)


def test_axis_scales_refuse_a_divergence_over_5_percent() -> None:
    with pytest.raises(ScaleRefused, match="height"):
        axis_scales((4.492, 1.372 * 1.06, 1.78), E46)
    with pytest.raises(ScaleRefused, match="width"):
        axis_scales((4.492, 1.372, 1.78 / 1.06), E46)
    with pytest.raises(ScaleRefused, match="length"):
        axis_scales((4.492 * 0.94, 1.372, 1.78), E46)
    # 4 % off is within the limit, and the limit is a parameter.
    assert axis_scales((4.492, 1.372 * 1.04, 1.78), E46)[1] == pytest.approx(1 / 1.04)
    with pytest.raises(ScaleRefused):
        axis_scales((4.492, 1.372 * 1.04, 1.78), E46, max_divergence=0.03)


def test_axis_scales_reject_a_measurement_that_is_not_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        axis_scales((4.492, 0.0, 1.78), E46)


def test_wheel_anchors_follow_the_data_not_the_mesh() -> None:
    anchors = wheel_anchor_positions(E46, FRONT_R, REAR_R)
    assert anchors["wheel_FL"] == pytest.approx((-0.754, 0.32985, -1.3655))
    assert anchors["wheel_FR"] == pytest.approx((0.754, 0.32985, -1.3655))
    assert anchors["wheel_RL"] == pytest.approx((-0.7625, 0.3306, 1.3655))
    assert anchors["wheel_RR"] == pytest.approx((0.7625, 0.3306, 1.3655))
    # The contract's ground check: wheel anchor y in range, and the four within a small spread.
    y_range = re.search(r"wheelAnchorY:\s*\{\s*min:\s*([\d.]+),\s*max:\s*([\d.]+)", CONTRACT_TS)
    spread = re.search(r"wheelAnchorSpread:\s*([\d.]+)", CONTRACT_TS)
    assert y_range is not None and spread is not None
    low, high, limit = float(y_range[1]), float(y_range[2]), float(spread[1])
    ys = [position[1] for position in anchors.values()]
    assert all(low <= y <= high for y in ys)
    assert max(ys) - min(ys) <= limit


def test_anchor_names_match_the_asset_contract() -> None:
    base = CONTRACT_TS[CONTRACT_TS.index("'base-car': {") :]
    match = re.search(r"requiredAnchors:\s*\[(.*?)\]", base, re.DOTALL)
    assert match is not None
    required = _quoted(match.group(1))
    produced = set(wheel_anchor_positions(E46, FRONT_R, REAR_R)) | set(mount_anchor_positions(E46))
    assert produced == set(required)
    assert len(required) == 10


def _body_modules() -> list[str]:
    match = re.search(r"BODY_MODULES\s*=\s*\[(.*?)\]\s*as const", CONTRACT_TS, re.DOTALL)
    assert match is not None
    return _quoted(match.group(1))


def test_module_cut_planes_cover_exactly_the_four_body_modules() -> None:
    planes = module_cut_planes(E46)
    assert set(planes) == set(_body_modules())
    assert len(planes) == 4
    for name, box in planes.items():
        assert all(lo < hi for lo, hi in zip(box.min, box.max, strict=True)), name
    assert planes["bumper_front"].max[2] <= -LENGTH_M / 2 + 0.45 + 1e-9
    assert planes["bumper_rear"].min[2] >= LENGTH_M / 2 - 0.45 - 1e-9
    assert planes["roof"].min[1] >= 1.15
    assert planes["roof"].max[1] >= HEIGHT_M  # the cut reaches past the roof line


def test_decimate_ratio_targets_150k() -> None:
    assert decimate_ratio(1_200_000) == 0.125
    assert decimate_ratio(90_000) == 1.0
    assert decimate_ratio(300_000, target=100_000) == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="triangles"):
        decimate_ratio(0)


def _cylinders(factor: float | None = None) -> list[dict[str, float]]:
    widths = (tire_width_m(FRONT_TIRE), tire_width_m(REAR_TIRE))
    if factor is None:
        return wheel_cylinders(E46, FRONT_R, REAR_R, *widths)
    return wheel_cylinders(E46, FRONT_R, REAR_R, *widths, wheel_cut_radius_factor=factor)


def test_wheel_cylinders_cut_at_the_factor_times_the_tire_radius() -> None:
    cylinders = _cylinders()
    assert len(cylinders) == 4
    anchors = wheel_anchor_positions(E46, FRONT_R, REAR_R)
    assert [(c["cx"], c["cy"], c["cz"]) for c in cylinders] == list(anchors.values())
    for c in cylinders:
        radius = FRONT_R if c["cz"] < 0 else REAR_R
        assert c["radius"] == pytest.approx(1.04 * radius)  # the default factor
    # The factor is a plan value, so the calibration tasks can change it.
    for c in _cylinders(factor=1.10):
        radius = FRONT_R if c["cz"] < 0 else REAR_R
        assert c["radius"] == pytest.approx(1.10 * radius)
    with pytest.raises(ValueError, match="factor"):
        _cylinders(factor=0.0)


def test_wheel_cylinders_span_the_tire_width_plus_10_mm_each_side() -> None:
    for c in _cylinders():
        width = 0.225 if c["cz"] < 0 else 0.255
        # Centered on the wheel anchor, because the tire is centered on the hub.
        assert c["x_min"] == pytest.approx(c["cx"] - width / 2 - 0.010)
        assert c["x_max"] == pytest.approx(c["cx"] + width / 2 + 0.010)


def _tire_face_centers(
    c: dict[str, float], tread_radius: float, width: float, sides: int = 64
) -> list[Vec]:
    """Centers (as Blender's median center gives them) of every face of a tire: `sides` tread
    quads, and the two flat caps, around the axle through (cx, cy, cz) along x."""
    centers: list[Vec] = []
    for i in range(sides):
        a0, a1 = 2 * math.pi * i / sides, 2 * math.pi * (i + 1) / sides
        corners = [
            (
                c["cx"] + dx,
                c["cy"] + tread_radius * math.cos(a),
                c["cz"] + tread_radius * math.sin(a),
            )
            for dx in (-width / 2, width / 2)
            for a in (a0, a1)
        ]
        centers.append(
            (
                sum(p[0] for p in corners) / 4,
                sum(p[1] for p in corners) / 4,
                sum(p[2] for p in corners) / 4,
            )
        )
    centers += [(c["cx"] - width / 2, c["cy"], c["cz"]), (c["cx"] + width / 2, c["cy"], c["cz"])]
    return centers


@pytest.mark.parametrize("oversize", [1.0, 1.03])
def test_every_face_of_a_fine_tire_falls_inside_the_planned_cylinder(oversize: float) -> None:
    """A tread quad of an n-sided tire has its center at r * cos(pi / n), just under the tread
    radius. A cut at 0.98 R left every tread band of a 64-sided tire at R, and capped it into a
    drum. The cut must take the tread of a tire at the data radius and 3% over it."""
    for c in _cylinders():
        data_radius = FRONT_R if c["cz"] < 0 else REAR_R
        width = 0.225 if c["cz"] < 0 else 0.255
        for x, y, z in _tire_face_centers(c, oversize * data_radius, width):
            assert c["x_min"] <= x <= c["x_max"]
            assert math.hypot(y - c["cy"], z - c["cz"]) <= c["radius"]


def test_compose_scales_takes_a_raw_mesh_to_the_data_dimensions() -> None:
    """The plan carries one set of per-axis factors, the total. The uniform step to the data's
    length and the near-1.0 axis factors are composed here, never applied twice."""
    raw_lhw = (4.40, 1.40, 1.80)  # a mesh whose body is 1.80 m wide and 1.40 m tall
    uniform = 4.492 / raw_lhw[0]
    measured = (raw_lhw[0] * uniform, raw_lhw[1] * uniform, raw_lhw[2] * uniform)
    factors = axis_scales(measured, E46)
    total = compose_scales(uniform, factors)
    scaled = tuple(t * r for t, r in zip(total, raw_lhw, strict=True))
    assert scaled == pytest.approx((4.492, 1.372, 1.78))
    assert lhw_to_blender_xyz(total) == (total[2], total[0], total[1])
    with pytest.raises(ValueError, match="uniform"):
        compose_scales(0.0, factors)


def test_interior_eye_anchor_is_the_data_eye_point() -> None:
    assert interior_fit(E46, EYE).eye == (-0.37, 1.1, 0.0)


def test_seat_driver_sits_below_and_behind_the_eye_point() -> None:
    fit = interior_fit(E46, EYE)
    assert fit.seat_driver[1] < EYE[1]
    assert fit.seat_driver[2] > EYE[2]  # toward +Z, the tail


def test_mount_seat_l_is_at_negative_x_for_a_left_hand_drive_car() -> None:
    fit = interior_fit(E46, EYE)
    assert fit.mount_seat_L[0] < 0 < fit.mount_seat_R[0]


def test_mount_steering_is_forward_of_the_eye_point() -> None:
    assert interior_fit(E46, EYE).mount_steering[2] < EYE[2]  # toward -Z, the nose


def test_cabin_box_lies_inside_the_wheelbase_and_below_the_roof() -> None:
    fit = interior_fit(E46, EYE)
    box = fit.cabin_box
    assert all(lo < hi for lo, hi in zip(box.min, box.max, strict=True))
    assert box.min[2] >= -WHEELBASE_M / 2 - 0.5 and box.max[2] <= WHEELBASE_M / 2 + 0.5
    assert box.max[1] <= HEIGHT_M
    assert all(lo <= p <= hi for lo, p, hi in zip(box.min, EYE, box.max, strict=True))
    assert fit.dash_target_width_m < E46.width_mm / 1000
    assert 0.3 < fit.steering_diameter_m < 0.4


def test_task_3_modules_need_no_third_party_package() -> None:
    allowed_project = {
        "frames.py": set[str](),
        "glbmeta.py": {"m3_pipeline.stages.lib.frames"},
        "placement.py": {"m3_pipeline.stages.lib.dims", "m3_pipeline.stages.lib.frames"},
    }
    for name, project_modules in allowed_project.items():
        tree = ast.parse((LIB / name).read_text("utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"{name}: use absolute imports"
                imported.add(node.module or "")
        stdlib = {m for m in imported if m.split(".")[0] in sys.stdlib_module_names}
        assert imported - stdlib <= project_modules, (name, sorted(imported - stdlib))
