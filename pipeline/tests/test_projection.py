import hashlib
import json
import math
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
    FRAME_MARGIN_PX,
    PROXY_MAX_TRIANGLES,
    WHEEL_ANCHORS,
    Camera,
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
    assert 24 <= cam.focal_mm <= 200
    assert -10 <= cam.roll_deg <= 10


def test_fit_camera_uses_at_most_474_renders(monkeypatch: pytest.MonkeyPatch) -> None:
    mesh = car()
    photo = render_mask(mesh, KNOWN)
    real = projection.render_mask
    calls: list[Camera] = []

    def counting(mesh: Mesh, cam: Camera, size: int = 256) -> NDArray[np.bool_]:
        calls.append(cam)
        return real(mesh, cam, size)

    monkeypatch.setattr(projection, "render_mask", counting)
    fit_camera(mesh, photo)
    assert 324 < len(calls) <= 474


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
