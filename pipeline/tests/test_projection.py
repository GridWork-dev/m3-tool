import hashlib
import json
import math
import re
import subprocess
import sys
from itertools import product
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from numpy.typing import NDArray

from m3_pipeline.stages.lib import projection
from m3_pipeline.stages.lib.frames import Vec, contract_to_blender
from m3_pipeline.stages.lib.projection import (
    FIT_FOCAL_MM,
    FRAME_MARGIN_PX,
    MAX_FIT_RENDERS,
    PROXY_MAX_TRIANGLES,
    RENDER_CAP,
    WHEEL_ANCHORS,
    Camera,
    CameraInsideMeshError,
    Mesh,
    add_wheel_proxies,
    camera_to_blender,
    fit_camera,
    load_export_proxy,
    load_proxy,
    project_points,
    render_mask,
    render_ortho_side,
)

# ---------------------------------------------------------------------------------------------
# Meshes built here: a box, and a box-plus-cabin "car" in the contract frame (nose toward -Z).
# ---------------------------------------------------------------------------------------------


def box(low: Vec, high: Vec) -> Mesh:
    """An axis-aligned box of 8 vertices and 12 triangles, wound outward."""
    corners = np.array(
        [[(high if bit else low)[axis] for axis, bit in enumerate(bits)] for bits in _BITS],
        dtype=np.float64,
    )
    return Mesh(corners, _outward_faces(corners))


# Vertex i of a box is (x, y, z) = bits of i, and each quad is one face walked around its edge.
_BITS = [(x, y, z) for z, y, x in product((0, 1), repeat=3)]
_QUADS = [
    (0, 1, 3, 2),  # z low
    (4, 5, 7, 6),  # z high
    (0, 1, 5, 4),  # y low
    (2, 3, 7, 6),  # y high
    (0, 2, 6, 4),  # x low
    (1, 3, 7, 5),  # x high
]


def join(*meshes: Mesh) -> Mesh:
    offsets = np.cumsum([0, *(len(m.vertices) for m in meshes[:-1])])
    return Mesh(
        np.concatenate([m.vertices for m in meshes]),
        np.concatenate([m.faces + int(o) for m, o in zip(meshes, offsets, strict=True)]),
    )


def frustum(low: Vec, high: Vec, top_low: Vec, top_high: Vec) -> Mesh:
    """A box whose top face is smaller than its bottom one: `low` and `high` are the corners of the
    bottom face (their y is the bottom), `top_low` and `top_high` those of the top face."""
    corners = np.array(
        [
            [low[0], low[1], low[2]],
            [high[0], low[1], low[2]],
            [low[0], low[1], high[2]],
            [high[0], low[1], high[2]],
            [top_low[0], top_low[1], top_low[2]],
            [top_high[0], top_low[1], top_low[2]],
            [top_low[0], top_low[1], top_high[2]],
            [top_high[0], top_low[1], top_high[2]],
        ],
        dtype=np.float64,
    )
    return Mesh(corners, _outward_faces(corners))


def _outward_faces(corners: NDArray[np.float64]) -> NDArray[np.int64]:
    centre = corners.mean(axis=0)
    faces: list[list[int]] = []
    for a, b, c, d in _QUADS:
        normal = np.cross(corners[b] - corners[a], corners[c] - corners[a])
        outward = float(normal @ (corners[a] - centre)) > 0
        faces += [[a, b, c], [a, c, d]] if outward else [[a, c, b], [a, d, c]]
    return np.array(faces, dtype=np.int64)


def car(length: float = 4.5) -> Mesh:
    """A body and a sloped cabin set toward the tail (+Z): 1.78 m wide, 1.4 m tall, sill at 0.12 m.
    The slopes matter: a cabin of plain boxes gives the fit's search ridges that real cars do not
    have."""
    k = length / 4.5
    body = box((-0.89, 0.12, -2.25 * k), (0.89, 0.80, 2.25 * k))
    cabin = frustum(
        (-0.78, 0.80, -0.55 * k),
        (0.78, 0.80, 1.65 * k),
        (-0.62, 1.40, 0.05 * k),
        (0.62, 1.40, 1.15 * k),
    )
    return join(body, cabin)


def stretched(mesh: Mesh, factor: float) -> Mesh:
    vertices = mesh.vertices.copy()
    vertices[:, 2] *= factor
    return Mesh(vertices, mesh.faces)


def mask_area(mask: NDArray[np.bool_]) -> int:
    return int(np.count_nonzero(mask))


def bounding_box(mask: NDArray[np.bool_]) -> tuple[int, int, int, int]:
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    return int(rows[0]), int(rows[-1]), int(columns[0]), int(columns[-1])


def signed_volume(mesh: Mesh) -> float:
    triangles = mesh.vertices[mesh.faces]
    return float(
        np.einsum("ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])).sum() / 6
    )


# ---------------------------------------------------------------------------------------------
# render_mask and project_points
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("azimuth", [0.0, 90.0, 180.0])
def test_render_mask_is_a_filled_silhouette_of_the_projected_triangles(azimuth: float) -> None:
    cube = box((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))
    size = 256
    mask = render_mask(cube, Camera(azimuth, 0.0, 10.0, 50.0), size)
    # Seen along an axis, the silhouette is the near face: a square that fills the frame to its
    # margin, with nothing missing inside it.
    expected = (size - 2 * FRAME_MARGIN_PX) ** 2
    assert mask_area(mask) == pytest.approx(expected, rel=0.02)
    top, bottom, left, right = bounding_box(mask)
    assert mask_area(mask) == (bottom - top + 1) * (right - left + 1)
    assert (bottom - top) == pytest.approx(right - left, abs=1)


def test_render_mask_does_not_depend_on_the_winding_of_the_triangles() -> None:
    mesh = car()
    flipped = Mesh(mesh.vertices, mesh.faces[:, ::-1].copy())
    cam = Camera(33.0, 12.0, 9.0, 50.0)
    assert np.array_equal(render_mask(mesh, cam), render_mask(flipped, cam))


def test_render_mask_of_a_mesh_without_triangles_is_empty() -> None:
    mesh = Mesh(np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]]), np.zeros((0, 3), dtype=np.int64))
    assert not render_mask(mesh, Camera(0.0, 0.0, 10.0, 50.0)).any()


def test_project_points_puts_the_look_at_point_at_the_image_center() -> None:
    cube = box((1.0, 2.0, 3.0), (2.0, 3.0, 4.0))
    centre = np.array([[1.5, 2.5, 3.5]])
    for cam in (Camera(0, 0, 8, 50), Camera(123, 17, 6, 35, 8.0), Camera(300, -5, 12, 85, -9.0)):
        # Corners of the cube are the whole mesh, so its center is the look-at point; add it as a
        # vertex that must not move the center.
        points = project_points(np.concatenate([cube.vertices, centre]), cam)
        assert points[-1] == pytest.approx([0.0, 0.0], abs=1e-12)


def test_project_points_front_view_has_the_driver_on_the_right_of_the_image() -> None:
    cube = box((-1.0, 0.0, -1.0), (1.0, 1.0, 1.0))
    # Azimuth 0 is the view from the front, looking back toward +Z: the driver's side (-X) is on
    # the image's right, and up is up.
    points = project_points(cube.vertices, Camera(0.0, 0.0, 10.0, 50.0))
    left_x = points[cube.vertices[:, 0] < 0][:, 0]
    right_x = points[cube.vertices[:, 0] > 0][:, 0]
    assert left_x.min() > 0 > right_x.max()
    assert (
        points[cube.vertices[:, 1] > 0.5][:, 1].min()
        > points[cube.vertices[:, 1] < 0.5][:, 1].max()
    )


def test_project_points_units_are_the_sensor_width() -> None:
    # A point 1 m to the side at 10 m, seen at 36 mm (the sensor's width): x = 1 / 10 = 0.1.
    vertices = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    points = project_points(vertices, Camera(0.0, 0.0, 10.0, 36.0))
    assert abs(points[0, 0] - points[1, 0]) == pytest.approx(2 / 10, rel=0.02)


def test_project_points_roll_turns_the_scene_clockwise_in_the_image() -> None:
    vertices = np.array([[-1.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    # Seen from the side (az 90) the +X end is toward the camera, so look from the front, where
    # the points are on the image's x axis, and roll by 90 degrees: the camera turns counter-
    # clockwise, so what was on the right is now at the bottom.
    level = project_points(vertices, Camera(0.0, 0.0, 10.0, 50.0))
    rolled = project_points(vertices, Camera(0.0, 0.0, 10.0, 50.0, 90.0))
    right = int(np.argmax(level[:, 0]))
    assert rolled[right, 1] < 0
    assert rolled[right, 0] == pytest.approx(0.0, abs=1e-9)


def test_project_points_refuses_a_camera_inside_the_mesh() -> None:
    cube = box((-5.0, -5.0, -5.0), (5.0, 5.0, 5.0))
    with pytest.raises(ValueError, match="inside or behind"):
        project_points(cube.vertices, Camera(0.0, 0.0, 3.0, 50.0))


def test_project_points_refuses_a_camera_that_looks_straight_down() -> None:
    cube = box((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0))
    with pytest.raises(ValueError, match="straight up or down"):
        project_points(cube.vertices, Camera(0.0, 90.0, 10.0, 50.0))


def test_mesh_refuses_malformed_arrays() -> None:
    with pytest.raises(ValueError, match="vertices must be"):
        Mesh(np.zeros((4, 2)), np.zeros((1, 3), dtype=np.int64))
    with pytest.raises(ValueError, match="faces must be"):
        Mesh(np.zeros((4, 3)), np.zeros((1, 4), dtype=np.int64))
    with pytest.raises(ValueError, match="outside"):
        Mesh(np.zeros((3, 3)), np.array([[0, 1, 3]], dtype=np.int64))
    with pytest.raises(ValueError, match="float64"):
        Mesh(
            cast("NDArray[np.float64]", np.zeros((4, 3), dtype=np.float32)),
            np.zeros((1, 3), dtype=np.int64),
        )
    with pytest.raises(ValueError, match="integer"):
        Mesh(np.zeros((4, 3)), cast("NDArray[np.int64]", np.zeros((1, 3))))
    with pytest.raises(ValueError, match="finite"):
        Mesh(np.array([[0.0, 0.0, math.nan]]), np.zeros((0, 3), dtype=np.int64))


# ---------------------------------------------------------------------------------------------
# fit_camera
# ---------------------------------------------------------------------------------------------

KNOWN = Camera(33.0, 12.0, 9.0, 50.0, 6.0)


def test_fit_camera_recovers_a_known_camera() -> None:
    mesh = car()
    fit = fit_camera(mesh, render_mask(mesh, KNOWN))
    assert fit.iou >= 0.97
    assert abs(fit.camera.azimuth_deg - KNOWN.azimuth_deg) <= 6
    assert abs(fit.camera.roll_deg - KNOWN.roll_deg) <= 3
    assert not fit.roll_at_bound


def test_fit_camera_flags_a_roll_at_the_bound() -> None:
    mesh = car()
    tilted = Camera(33.0, 12.0, 9.0, 50.0, 14.0)
    fit = fit_camera(mesh, render_mask(mesh, tilted))
    assert fit.roll_at_bound
    assert fit.camera.roll_deg == pytest.approx(10.0, abs=1.0)
    assert abs(fit.camera.roll_deg) <= 10.0


def test_fit_camera_keeps_every_parameter_inside_its_bounds() -> None:
    mesh = car()
    photo = render_mask(mesh, Camera(200.0, 55.0, 25.0, 150.0, -9.0))
    cam = fit_camera(mesh, photo).camera
    assert 0 <= cam.azimuth_deg < 360
    assert -10 <= cam.elevation_deg <= 60
    assert 3 <= cam.distance_m <= 30
    assert cam.focal_mm == FIT_FOCAL_MM
    assert -10 <= cam.roll_deg <= 10


def test_fit_camera_uses_at_most_600_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ruling R90: the schedule's worst case, repeats not counted, is under the cap of 600, and
    # a fit never renders more than that.
    assert MAX_FIT_RENDERS <= RENDER_CAP == 600
    mesh = car()
    photo = render_mask(mesh, KNOWN)
    real = projection.render_mask
    calls: list[Camera] = []

    def counting(mesh: Mesh, cam: Camera, size: int = 256) -> NDArray[np.bool_]:
        calls.append(cam)
        return real(mesh, cam, size)

    monkeypatch.setattr(projection, "render_mask", counting)
    fit_camera(mesh, photo)
    assert 400 < len(calls) <= MAX_FIT_RENDERS  # this fit uses 483; the worst case is 540


def test_fit_camera_never_renders_one_camera_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    # The brief's schedule rendered every focal of a cell, and the mask is the same at any focal.
    mesh = car()
    photo = render_mask(mesh, KNOWN)
    real = projection.render_mask
    seen: list[tuple[float, float, float, float]] = []

    def recording(mesh: Mesh, cam: Camera, size: int = 256) -> NDArray[np.bool_]:
        seen.append((cam.azimuth_deg, cam.elevation_deg, cam.distance_m, cam.roll_deg))
        return real(mesh, cam, size)

    monkeypatch.setattr(projection, "render_mask", recording)
    fit_camera(mesh, photo)
    assert len(seen) == len(set(seen))


def test_the_mask_does_not_depend_on_the_focal_length() -> None:
    # The premise of leaving focal out of the search: at one distance a longer lens is a uniform
    # scale, which the framing takes out.
    mesh = car()
    reference = render_mask(mesh, Camera(40.0, 8.0, 7.0, 24.0, 2.0))
    for focal in (35.0, 50.0, 85.0, 200.0):
        assert np.array_equal(reference, render_mask(mesh, Camera(40.0, 8.0, 7.0, focal, 2.0)))


def test_fit_camera_handles_a_mirrored_photo() -> None:
    mesh = car()
    photo = render_mask(mesh, KNOWN)
    mirrored_photo = np.ascontiguousarray(photo[:, ::-1])
    fit = fit_camera(mesh, mirrored_photo, mirrored=True)
    # The flag undoes the flip before anything is compared, so the answer is the unflipped one.
    assert fit == fit_camera(mesh, photo)
    assert fit.iou >= 0.97


def test_fit_camera_is_deterministic_for_a_seed() -> None:
    mesh = car()
    photo = render_mask(mesh, KNOWN)
    assert fit_camera(mesh, photo, seed=7) == fit_camera(mesh, photo, seed=7)


def test_fit_camera_records_the_seed_it_ran_with() -> None:
    mesh = car()
    photo = render_mask(mesh, KNOWN)
    assert fit_camera(mesh, photo, seed=7).seed == 7
    assert fit_camera(mesh, photo).seed == 0


def test_the_seed_changes_the_search_not_just_the_record() -> None:
    # The seed sets the order the parameters are visited in, and on a hard photo that lands the
    # descent on different cameras. If the seed were ignored, every seed would agree on every
    # photo and this would fail.
    mesh = car()
    outcomes: set[tuple[Camera, float]] = set()
    for camera in random_cameras(31, 5, -9.0, 9.0):
        photo = render_mask(mesh, camera)
        for seed in range(4):
            fit = fit_camera(mesh, photo, seed=seed)
            outcomes.add((fit.camera, fit.iou))
    assert len(outcomes) > 5  # five photos: one outcome each if every seed agreed


def test_wrong_proportions_score_lower() -> None:
    mesh = car()
    # A side view, where the length against the height is what the silhouette shows.
    photo = render_mask(mesh, Camera(90.0, 0.0, 9.0, 50.0))
    right = fit_camera(mesh, photo)
    longer = fit_camera(stretched(mesh, 1.06), photo)
    assert right.iou - longer.iou >= 0.02


def test_fit_camera_refuses_an_empty_photo() -> None:
    with pytest.raises(ValueError, match="photo mask"):
        fit_camera(car(), np.zeros((64, 64), dtype=np.bool_))


def test_fit_camera_scores_a_camera_inside_the_mesh_as_no_match_not_an_error() -> None:
    # A car 2.2 times as long is about 10 m: the grid's 5 m cells are inside it and score 0, and
    # the 8 and 14 m ones still see it.
    big = Mesh(car().vertices * 2.2, car().faces)
    photo = render_mask(big, Camera(33.0, 12.0, 20.0, 50.0, 4.0))
    assert fit_camera(big, photo).iou > 0.95


def random_cameras(
    seed: int, count: int, roll_low: float, roll_high: float, signed: bool = False
) -> list[Camera]:
    """Cameras spread over the whole circle, 0 to 25 degrees up and 6 to 14 m out, each with a roll
    between `roll_low` and `roll_high` degrees (and, with `signed`, either way)."""
    rng = np.random.default_rng(seed)
    cameras: list[Camera] = []
    for _ in range(count):
        roll = float(rng.uniform(roll_low, roll_high))
        if signed and rng.random() < 0.5:
            roll = -roll
        cameras.append(
            Camera(
                float(rng.uniform(0, 360)),
                float(rng.uniform(0, 25)),
                float(rng.uniform(6, 14)),
                50.0,
                roll,
            )
        )
    return cameras


def test_the_fit_is_good_on_random_cameras_not_only_on_the_pinned_one() -> None:
    # The photos are renders of the mesh itself, so the true camera scores 1.0 and every shortfall
    # is the search stalling. The cameras come from two seeds that no tuning run ever used (the
    # schedule was tuned on 12345, 4242 and 2024), and the assertions are population statistics,
    # not golden values, so a change to the schedule, the visiting order or this mesh fails them
    # only when the fit gets worse. Measured on these 40: mean 0.984, 10th percentile 0.957, min
    # 0.930. Over 30 other held-out groups of 40 the new search passed all three assertions every
    # time, and the brief's schedule failed the mean and the 10th percentile every time (mean
    # 0.957, 10th percentile 0.917, worst single score 0.806). The minimum is only a guard against
    # a catastrophic stall: one stalled photo in 40 is not a regression.
    mesh = car()
    cameras = random_cameras(5000, 20, -9.0, 9.0) + random_cameras(5001, 20, -9.0, 9.0)
    scores = np.array([fit_camera(mesh, render_mask(mesh, camera)).iou for camera in cameras])
    assert float(scores.mean()) >= 0.975
    assert float(np.percentile(scores, 10)) >= 0.95
    assert float(scores.min()) >= 0.88


def test_roll_at_the_bound_is_flagged_for_most_tilted_photos_and_rarely_for_level_ones() -> None:
    # Task 14 treats the flag as advisory: it catches most, not all, photos taken with a tilted
    # camera, and it rarely flags a level one. Over 36 tilted photos (|roll| 12 to 20 degrees)
    # this set flags 28 (78%; 16 of 40 under the brief's schedule). On 30 other 36-photo sets the
    # count ranged from 24 to 33, so the floor of 22 sits below the lowest of them. Of 720 level
    # photos (|roll| under 5) from those held-out sets 2 were flagged, so one false flag in 24 is
    # allowed here.
    mesh = car()
    tilted = random_cameras(9, 36, 12.0, 20.0, signed=True)
    flagged = sum(fit_camera(mesh, render_mask(mesh, c)).roll_at_bound for c in tilted)
    assert flagged >= 22
    level = random_cameras(109, 24, 0.0, 5.0, signed=True)
    falsely_flagged = sum(fit_camera(mesh, render_mask(mesh, c)).roll_at_bound for c in level)
    assert falsely_flagged <= 1


def test_a_mesh_without_vertices_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one vertex"):
        Mesh(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))


def test_fit_camera_refuses_a_mesh_without_triangles() -> None:
    mesh = Mesh(car().vertices, np.zeros((0, 3), dtype=np.int64))
    with pytest.raises(ValueError, match="no triangles"):
        fit_camera(mesh, render_mask(car(), KNOWN))


def test_fit_camera_does_not_swallow_an_error_that_is_not_a_camera_inside_the_mesh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mesh = car()
    photo = render_mask(mesh, KNOWN)

    def failing(mesh: Mesh, cam: Camera, size: int = 256) -> NDArray[np.bool_]:
        raise ValueError("something else is wrong")

    monkeypatch.setattr(projection, "render_mask", failing)
    with pytest.raises(ValueError, match="something else"):
        fit_camera(mesh, photo)


def test_a_camera_inside_the_mesh_has_its_own_error() -> None:
    cube = box((-5.0, -5.0, -5.0), (5.0, 5.0, 5.0))
    with pytest.raises(CameraInsideMeshError):
        render_mask(cube, Camera(0.0, 0.0, 3.0, 50.0))


# ---------------------------------------------------------------------------------------------
# Wheels and the orthographic side view
# ---------------------------------------------------------------------------------------------

ANCHORS: dict[str, Vec] = {
    "wheel_FL": (-0.75, 0.33, -1.3655),
    "wheel_FR": (0.75, 0.33, -1.3655),
    "wheel_RL": (-0.76, 0.33, 1.3655),
    "wheel_RR": (0.76, 0.33, 1.3655),
}
RADII: dict[str, float] = dict.fromkeys(WHEEL_ANCHORS, 0.33)
WIDTHS: dict[str, float] = dict.fromkeys(WHEEL_ANCHORS, 0.225)


def test_wheel_proxies_add_tire_silhouettes_at_the_anchors() -> None:
    body = car()
    with_wheels = add_wheel_proxies(body, ANCHORS, RADII, WIDTHS)
    bare = render_ortho_side(body)
    wheeled = render_ortho_side(with_wheels)

    def pixel(side: projection.OrthoMask, z: float, y: float) -> tuple[int, int]:
        col = side.origin_px[0] - z * side.px_per_m
        row = side.origin_px[1] - y * side.px_per_m
        return round(row), round(col)

    for z in (-1.3655, 1.3655):
        # 6 cm up is below the sill (0.12 m) and inside the tire, at the anchor's position along
        # the car.
        assert not bare.mask[pixel(bare, z, 0.06)]
        assert wheeled.mask[pixel(wheeled, z, 0.06)]
    # Between the wheels the space under the sill is still open.
    assert not wheeled.mask[pixel(wheeled, 0.0, 0.06)]
    # The wheels reach the ground, and only they do.
    ground_row = round(wheeled.origin_px[1])
    assert wheeled.mask[ground_row - 1].any()
    assert not wheeled.mask[ground_row + 2].any()


def test_wheel_proxies_are_four_closed_prisms_wound_outward() -> None:
    body = car()
    with_wheels = add_wheel_proxies(body, ANCHORS, RADII, WIDTHS)
    prism_faces = len(with_wheels.faces) - len(body.faces)
    assert prism_faces == 4 * (2 * 24 + 2 * 24)
    assert len(with_wheels.vertices) - len(body.vertices) == 4 * (2 * 24 + 2)
    wheels = Mesh(
        with_wheels.vertices[len(body.vertices) :],
        with_wheels.faces[len(body.faces) :] - len(body.vertices),
    )
    # A 24-gon of radius r has area (n / 2) r^2 sin(2 pi / n); four wheels of width w.
    area = 12 * 0.33**2 * math.sin(2 * math.pi / 24)
    assert signed_volume(wheels) == pytest.approx(4 * area * 0.225, rel=1e-9)
    # The body is untouched.
    assert np.array_equal(with_wheels.vertices[: len(body.vertices)], body.vertices)
    assert np.array_equal(with_wheels.faces[: len(body.faces)], body.faces)


def test_wheel_proxies_are_centered_on_their_anchors_with_the_axis_along_x() -> None:
    wheels = add_wheel_proxies(car(), ANCHORS, RADII, {**WIDTHS, "wheel_FL": 0.30})
    body_count = len(car().vertices)
    first = wheels.vertices[body_count : body_count + 50]  # wheel_FL: two rings and two centers
    low, high = first.min(axis=0), first.max(axis=0)
    assert (low + high)[0] / 2 == pytest.approx(-0.75)
    assert high[0] - low[0] == pytest.approx(0.30)
    assert (low + high)[1] / 2 == pytest.approx(0.33, abs=0.01)
    assert high[1] - low[1] == pytest.approx(0.66, abs=0.01)


def test_wheel_proxies_use_anchor_names_as_keys() -> None:
    axles = {"front": 0.33, "rear": 0.34}
    with pytest.raises(ValueError, match="radii_m"):
        add_wheel_proxies(car(), ANCHORS, axles, WIDTHS)
    with pytest.raises(ValueError, match="widths_m"):
        add_wheel_proxies(car(), ANCHORS, RADII, {"front": 0.225, "rear": 0.255})
    with pytest.raises(ValueError, match="anchors"):
        add_wheel_proxies(
            car(), {"front": (0.0, 0.33, -1.3655), "rear": (0.0, 0.33, 1.3655)}, RADII, WIDTHS
        )


def test_wheel_proxies_accept_a_whole_node_positions_mapping_for_the_anchors() -> None:
    everything: dict[str, Vec] = {
        **ANCHORS,
        "body": (0.0, 0.7, 0.0),
        "mount_trunk": (0.0, 0.9, 2.0),
    }
    assert len(add_wheel_proxies(car(), everything, RADII, WIDTHS).faces) == len(car().faces) + 384


def test_wheel_proxies_refuse_a_radius_that_is_not_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        add_wheel_proxies(car(), ANCHORS, {**RADII, "wheel_RR": 0.0}, WIDTHS)


def test_render_ortho_side_reports_its_scale_and_origin() -> None:
    ground_box = box((-0.9, 0.0, -2.0), (0.9, 1.4, 2.0))  # 4.0 x 1.4 m, on the ground
    side = render_ortho_side(ground_box)
    top, bottom, left, right = bounding_box(side.mask)
    assert (right - left + 1) / side.px_per_m == pytest.approx(4.0, rel=0.01)
    assert (bottom - top + 1) / side.px_per_m == pytest.approx(1.4, rel=0.01)
    # The bottom edge is the ground, y = 0, which is the origin's row.
    assert bottom == pytest.approx(side.origin_px[1], abs=1)
    # z = 0 is the middle of the box, so the origin's column is the middle of the mask.
    assert (left + right) / 2 == pytest.approx(side.origin_px[0], abs=1)


def test_render_ortho_side_puts_the_nose_on_the_right() -> None:
    # A cabin toward the tail (+Z) puts the high part of the silhouette on the left.
    side = render_ortho_side(car())
    columns = np.flatnonzero(side.mask.any(axis=0))
    top_rows = np.flatnonzero(side.mask[: int(side.origin_px[1] - 1.2 * side.px_per_m)].any(axis=0))
    assert top_rows.mean() < columns.mean()


# ---------------------------------------------------------------------------------------------
# Loading proxies
# ---------------------------------------------------------------------------------------------


def test_load_proxy_names_the_missing_array(tmp_path: Path) -> None:
    path = tmp_path / "proxy.npz"
    np.savez(path, vertices=np.zeros((3, 3)))
    with pytest.raises(ValueError, match="faces"):
        load_proxy(path)
    np.savez(path, faces=np.zeros((1, 3), dtype=np.int64))
    with pytest.raises(ValueError, match="vertices"):
        load_proxy(path)


def test_load_proxy_converts_the_blender_frame_to_the_contract_frame(tmp_path: Path) -> None:
    path = tmp_path / "proxy.npz"
    vertices = np.array([[0.0, 1.0, 0.0], [1.0, 2.0, 3.0], [0.0, 0.0, 1.0]])
    np.savez(path, vertices=vertices, faces=np.array([[0, 1, 2]], dtype=np.int32))
    contract = load_proxy(path)
    # A vertex 1 m toward the Blender nose (+Y) is 1 m toward the contract nose (-Z).
    assert contract.vertices[0].tolist() == [0.0, 0.0, -1.0]
    assert contract.vertices[1].tolist() == [1.0, 3.0, -2.0]
    assert contract.vertices[2].tolist() == [0.0, 1.0, 0.0]
    assert contract.faces.dtype == np.int64
    assert contract.faces.tolist() == [[0, 1, 2]]
    blender = load_proxy(path, frame="blender")
    assert blender.vertices.tolist() == vertices.tolist()


def test_load_proxy_refuses_a_single_array_file(tmp_path: Path) -> None:
    path = tmp_path / "proxy.npy"
    np.save(path, np.zeros((3, 3)))
    with pytest.raises(ValueError, match="npz"):
        load_proxy(path)


def write_export_proxy(path: Path, count: int, **overrides: object) -> None:
    rng = np.random.default_rng(1)
    vertices = rng.random((200, 3)) * [1.8, 1.4, 4.5]
    document: dict[str, object] = {
        "sha256": hashlib.sha256(b"the exported glb").hexdigest(),
        "bbox_min": [-0.9, 0.1, -2.25],
        "bbox_max": [0.9, 1.5, 2.25],
        "triangles": 152_340,
        "node_positions": {"wheel_FL": [-0.75, 0.33, -1.3655], "body": [0.0, 0.0, 0.0]},
        "vertices": vertices.tolist(),
        "faces": rng.integers(0, 200, size=(count, 3)).tolist(),
    }
    document.update(overrides)
    path.write_text(json.dumps(document), "utf-8")


def test_load_export_proxy_returns_the_glb_sha256_and_the_full_mesh_facts(tmp_path: Path) -> None:
    path = tmp_path / "car.proxy.json"
    write_export_proxy(path, 30_000)
    mesh, meta = load_export_proxy(path)
    assert meta.sha256 == hashlib.sha256(b"the exported glb").hexdigest()
    assert meta.bbox_min == (-0.9, 0.1, -2.25)
    assert meta.bbox_max == (0.9, 1.5, 2.25)
    # The full mesh's count and box, not the decimated proxy's.
    assert meta.triangles == 152_340
    assert len(mesh.faces) == 30_000
    assert meta.node_positions == {"wheel_FL": (-0.75, 0.33, -1.3655), "body": (0.0, 0.0, 0.0)}
    assert mesh.vertices.shape == (200, 3)
    # Already in the contract frame: nothing is converted.
    first = json.loads(path.read_text("utf-8"))["vertices"][0]
    assert mesh.vertices[0].tolist() == first


def test_load_export_proxy_accepts_a_proxy_of_30081_triangles(tmp_path: Path) -> None:
    path = tmp_path / "car.proxy.json"
    write_export_proxy(path, 30_081)
    mesh, _ = load_export_proxy(path)
    assert len(mesh.faces) == 30_081


def test_load_export_proxy_stops_at_the_exports_cap_of_31000(tmp_path: Path) -> None:
    path = tmp_path / "car.proxy.json"
    assert PROXY_MAX_TRIANGLES == 31_000
    write_export_proxy(path, 31_000)
    assert len(load_export_proxy(path)[0].faces) == 31_000
    write_export_proxy(path, 31_001)
    with pytest.raises(ValueError, match="31,000"):
        load_export_proxy(path)


def test_the_31000_cap_is_the_one_in_the_export_script() -> None:
    # The export fails rather than write a proxy over its cap, and the loader refuses one over the
    # same number. Two copies of a number drift, so read the script's.
    script = Path(__file__).resolve().parents[2] / "tools" / "export-glb.ts"
    match = re.search(r"^const PROXY_MAX_TRIANGLES = ([0-9_]+)$", script.read_text("utf-8"), re.M)
    assert match is not None, "tools/export-glb.ts has no `const PROXY_MAX_TRIANGLES = <number>`"
    assert int(match.group(1).replace("_", "")) == PROXY_MAX_TRIANGLES


@pytest.mark.parametrize(
    ("overrides", "named"),
    [
        ({"sha256": "abc"}, "sha256"),
        ({"triangles": "many"}, "triangles"),
        ({"triangles": True}, "triangles"),
        ({"bbox_min": [0.0, 1.0]}, "bbox_min"),
        ({"bbox_max": "tall"}, "bbox_max"),
        ({"node_positions": []}, "node_positions"),
        ({"node_positions": {"wheel_FL": [1, 2]}}, "wheel_FL"),
        ({"vertices": [[0.0, 1.0]]}, "vertices"),
        ({"vertices": "none"}, "vertices"),
        ({"faces": [[0, 1, 2.5]]}, "faces"),
        ({"faces": [[0, 1, 500]]}, "outside"),
    ],
)
def test_load_export_proxy_names_what_is_malformed(
    tmp_path: Path, overrides: dict[str, object], named: str
) -> None:
    path = tmp_path / "car.proxy.json"
    write_export_proxy(path, 100, **overrides)
    with pytest.raises(ValueError, match=named):
        load_export_proxy(path)


def test_load_export_proxy_names_a_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "car.proxy.json"
    write_export_proxy(path, 100)
    document = json.loads(path.read_text("utf-8"))
    del document["bbox_max"]
    path.write_text(json.dumps(document), "utf-8")
    with pytest.raises(ValueError, match="bbox_max is missing"):
        load_export_proxy(path)


def test_load_export_proxy_refuses_a_file_that_is_not_json(tmp_path: Path) -> None:
    path = tmp_path / "car.proxy.json"
    path.write_text("not json", "utf-8")
    with pytest.raises(ValueError, match="could not read"):
        load_export_proxy(path)
    path.write_text("[1, 2]", "utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_export_proxy(path)


# ---------------------------------------------------------------------------------------------
# camera_to_blender
# ---------------------------------------------------------------------------------------------


def blender_pinhole(
    location: Vec, look_at: Vec, roll_deg: float, focal_mm: float, points: NDArray[np.float64]
) -> NDArray[np.float64]:
    """A pinhole as Blender builds one: -Z toward `look_at`, Y up (world up is +Z), then rotated
    about its own Z by `roll_deg`, sensor 36 mm wide. Image points in units of the sensor width."""
    eye = np.array(location)
    z_axis = eye - np.array(look_at)
    z_axis /= np.linalg.norm(z_axis)
    x_axis = np.cross([0.0, 0.0, 1.0], z_axis)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    roll = math.radians(roll_deg)
    rotation = np.array(
        [
            [math.cos(roll), -math.sin(roll), 0.0],
            [math.sin(roll), math.cos(roll), 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    camera_to_world = np.column_stack([x_axis, y_axis, z_axis]) @ rotation
    local = (points - eye) @ camera_to_world  # rows: the point in the camera's own axes
    depth = -local[:, 2]
    scale = focal_mm / 36.0
    return np.column_stack([scale * local[:, 0] / depth, scale * local[:, 1] / depth])


@pytest.mark.parametrize(
    "cam",
    [
        Camera(0.0, 0.0, 10.0, 50.0),
        Camera(33.0, 12.0, 9.0, 50.0, 6.0),
        Camera(145.0, 25.0, 6.5, 85.0, -8.0),
        Camera(300.0, -4.0, 14.0, 35.0, 10.0),
    ],
)
def test_camera_to_blender_agrees_with_project_points(cam: Camera) -> None:
    cube = box((0.3, -0.2, 1.0), (1.7, 0.9, 2.1))
    target = tuple(float(c) for c in (cube.vertices.min(axis=0) + cube.vertices.max(axis=0)) / 2)
    placed = camera_to_blender(cam, (target[0], target[1], target[2]))
    assert set(placed) == {"location_blender", "look_at_blender", "roll_deg", "focal_mm"}
    assert placed["roll_deg"] == cam.roll_deg
    assert placed["focal_mm"] == cam.focal_mm
    location = cast("Vec", placed["location_blender"])
    look_at = cast("Vec", placed["look_at_blender"])
    assert isinstance(location, tuple)
    assert isinstance(look_at, tuple)
    assert look_at == contract_to_blender((target[0], target[1], target[2]))
    corners_blender = np.array(
        [contract_to_blender((x, y, z)) for x, y, z in cube.vertices.tolist()]
    )
    in_blender = blender_pinhole(location, look_at, cam.roll_deg, cam.focal_mm, corners_blender)
    assert in_blender == pytest.approx(project_points(cube.vertices, cam), abs=1e-6)


def test_camera_to_blender_places_the_camera_at_its_distance_from_the_target() -> None:
    placed = camera_to_blender(Camera(90.0, 0.0, 8.0, 50.0), (0.0, 0.7, 0.0))
    # Azimuth 90 is the car's right side (+X), and the contract's +X is Blender's +X.
    assert placed["location_blender"] == pytest.approx((8.0, 0.0, 0.7))
    assert placed["look_at_blender"] == (0.0, 0.0, 0.7)


def test_importing_the_cli_with_these_modules_loads_no_heavy_dependencies() -> None:
    # A stage module imports `projection` and `scoring`, and every stage loads with the CLI, so
    # numpy and Pillow must come in only when a function that needs them runs. Same check as
    # test_importing_the_cli_loads_no_heavy_dependencies, with the two modules imported too.
    code = (
        "import sys, m3_pipeline.cli, m3_pipeline.stages.lib.projection, "
        "m3_pipeline.stages.lib.scoring; "
        "print(','.join(sorted(m for m in "
        "('playwright', 'PIL', 'imagehash', 'numpy', 'scipy', 'boto3', 'rembg') "
        "if m in sys.modules)))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""
