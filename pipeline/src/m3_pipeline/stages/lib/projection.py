"""Projection math: a candidate's proxy mesh as a silhouette, and the camera that fits a photo.

Meshes are in the contract frame (meters, +Y up, nose toward -Z, the driver at -X). The camera
looks at the bbox center of the mesh it is given and sits `distance_m` away at an azimuth and an
elevation. Azimuth 0 is the view from the front, nose toward the camera, and it grows toward the
car's right side (+X): 90 is the right side, 180 the rear, 270 the driver's side. Elevation is
degrees above the horizon.

`roll_deg` rolls the camera about its view axis the way Blender's `rotation_euler.z` does: a
positive angle tilts the camera counter-clockwise as seen along the view direction, so the scene
turns clockwise in the image. `camera_to_blender` hands that angle to `render_views.py` as it is.

Focal lengths are 35 mm equivalents (sensor width 36 mm). `project_points` returns image-plane
points in units of the sensor width, so a point at the right edge of the sensor has x = 0.5, and
the focal length is already in them. Rasterizing is Pillow's polygon fill over integer pixel
coordinates, which includes a polygon's boundary, so shared edges overlap and never leave a crack.

numpy and Pillow, plus `frames` for the one frame conversion and `scoring` for the fit's score.
Both are imported inside the functions that use them, so importing this module (the `score` stage
registers when the CLI loads) stays cheap: `test_importing_the_cli_loads_no_heavy_dependencies`
holds the CLI to that.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from m3_pipeline.stages.lib.frames import Vec, blender_to_contract, contract_to_blender
from m3_pipeline.stages.lib.scoring import aligned_iou

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# The empty border `render_mask` and `render_ortho_side` leave around the projected box.
FRAME_MARGIN_PX = 2
# The widest a proxy may be: the export's cap (PROXY_MAX_TRIANGLES in tools/export-glb.ts), which
# is a little above the 30,000 it aims at. Never compare against 30,000.
PROXY_MAX_TRIANGLES = 31_000
# The four wheel anchors of the contract, in the order `add_wheel_proxies` adds their prisms.
WHEEL_ANCHORS = ("wheel_FL", "wheel_FR", "wheel_RL", "wheel_RR")
WHEEL_SIDES = 24
SENSOR_WIDTH_MM = 36.0
# A vertex nearer to the camera plane than this is behind the camera, as far as a pinhole goes.
_NEAR_M = 1e-3

# fit_camera: the search space (ruling R90, amending the brief's schedule). Focal length is not
# searched: at a fixed distance a longer lens is a uniform scale, and the framing and the width
# match take that out, so the mask, and with it every score, is identical at any focal. The brief's
# grid and descent spent 246 of their 474 renders on that duplicate. The schedule spends the
# saving on more starts and a finer second pass, all inside the cap of 600 renders:
#
# 1. A grid of 12 azimuths x 3 elevations x 3 distances = 108 renders, at roll 0.
# 2. The best `_PRESCREEN_CELLS` cells are also rendered at roll plus and minus
#    `_PRESCREEN_ROLL_DEG`, and each keeps the best of its three rolls. The grid cannot see roll,
#    and a photo that is tilted ranks its right cell far down at roll 0 (rank 15 to 25 of 108).
# 3. Coordinate descent over azimuth, elevation, distance and roll, both directions of each, in
#    stages: the best 10 cells walk levels 0 to 2, the best 4 of those walk levels 2 to 4, and the
#    best 2 of those walk levels 4 to 6. A level's step is its parameter's first step halved that
#    many times, so every later stage is a second pass at a smaller step.
_GRID_AZIMUTHS_DEG = tuple(float(azimuth) for azimuth in range(0, 360, 30))
_GRID_ELEVATIONS_DEG = (0.0, 10.0, 20.0)
_GRID_DISTANCES_M = (5.0, 8.0, 14.0)
_PRESCREEN_CELLS = 24
_PRESCREEN_ROLL_DEG = 5.0
# Each stage: how many of the best candidates it refines, and the levels it walks.
_STAGES = ((10, (0, 1, 2)), (4, (2, 3, 4)), (2, (4, 5, 6)))
# The first step of each parameter: azimuth, elevation, distance, roll. The azimuth step is half
# the grid's spacing, so every azimuth is within reach of a cell, and roll starts with 5 degrees.
_FIRST_STEPS = (15.0, 5.0, 3.0, 5.0)
# The renders the schedule can use at most, repeats not counted, and the cap it must stay under.
MAX_FIT_RENDERS = (
    len(_GRID_AZIMUTHS_DEG) * len(_GRID_ELEVATIONS_DEG) * len(_GRID_DISTANCES_M)
    + 2 * _PRESCREEN_CELLS
    + sum(keep * 2 * len(_FIRST_STEPS) * len(levels) for keep, levels in _STAGES)
)
RENDER_CAP = 600
# The focal every fitted camera carries: it cannot change the score, so it is not searched, and a
# 50 mm lens is the normal one.
FIT_FOCAL_MM = 50.0
# What a fit may not leave. Roll is at most 10 degrees: a photo that needs more was taken with a
# tilted camera, and `roll_at_bound` says so from 9 degrees on.
ROLL_LIMIT_DEG = 10.0
ROLL_AT_BOUND_DEG = 9.0
_ELEVATION_RANGE_DEG = (-10.0, 60.0)
_DISTANCE_RANGE_M = (3.0, 30.0)

_Params = tuple[float, float, float, float]  # azimuth, elevation, distance, roll


@dataclass(frozen=True, eq=False)
class Mesh:
    """Vertices and triangles in the contract frame: `(N, 3)` floats and `(M, 3)` indices."""

    vertices: NDArray[np.float64]
    faces: NDArray[np.int64]

    def __post_init__(self) -> None:
        import numpy as np

        if self.vertices.ndim != 2 or self.vertices.shape[1] != 3:
            raise ValueError(f"vertices must be (N, 3), not {self.vertices.shape}")
        if len(self.vertices) == 0:
            raise ValueError("a mesh needs at least one vertex")
        if self.vertices.dtype != np.float64:
            raise ValueError(f"vertices must be float64, not {self.vertices.dtype}")
        if self.faces.ndim != 2 or self.faces.shape[1] != 3:
            raise ValueError(f"faces must be (M, 3), not {self.faces.shape}")
        if self.faces.dtype.kind not in "iu":
            raise ValueError(f"faces must be integer indices, not {self.faces.dtype}")
        if not np.isfinite(self.vertices).all():
            raise ValueError("a vertex is not a finite number")
        if self.faces.size > 0 and (
            int(self.faces.min()) < 0 or int(self.faces.max()) >= len(self.vertices)
        ):
            raise ValueError(f"a face points outside the {len(self.vertices)} vertices")


def _linear(convert: Callable[[Vec], Vec]) -> NDArray[np.float64]:
    """The matrix of a linear frame conversion, so many points convert in one product while the
    conversion itself stays in `frames.py`: row i is where the i-th axis goes, and a point `p`
    becomes `p @ matrix`."""
    import numpy as np

    axes: tuple[Vec, Vec, Vec] = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    return np.array([convert(axis) for axis in axes], dtype=np.float64)


def load_proxy(path: Path, *, frame: Literal["contract", "blender"] = "contract") -> Mesh:
    """A proxy `.npz` with arrays `vertices` and `faces`, as Blender writes it.

    Blender writes its own frame (Z up, nose toward +Y), so the vertices are converted to the
    contract frame unless `frame="blender"` says to leave them. A missing array raises
    `ValueError` naming it.
    """
    import numpy as np

    archive: Any = np.load(path, allow_pickle=False)
    if not hasattr(archive, "files"):  # a bare .npy loads as the array itself
        raise ValueError(f"{path}: expected an .npz with 'vertices' and 'faces' arrays")
    with archive as data:
        names = list(data.files)
        missing = [name for name in ("vertices", "faces") if name not in names]
        if missing:
            raise ValueError(
                f"{path}: the proxy has no {' or '.join(repr(name) for name in missing)} array "
                f"(it has {names})"
            )
        vertices = np.asarray(data["vertices"], dtype=np.float64)
        faces = np.asarray(data["faces"], dtype=np.int64)
    if frame == "contract":
        vertices = vertices @ _linear(blender_to_contract)
    return Mesh(vertices, faces)


@dataclass(frozen=True)
class ExportProxyMeta:
    """What `tools/export-glb.ts` records about the whole GLB, not about its decimated proxy:
    `bbox_min` and `bbox_max` bound the full mesh, `triangles` is its full count, and
    `node_positions` holds the world position of every named node, anchors included. `sha256` is
    the digest of the exported GLB's bytes."""

    sha256: str
    bbox_min: Vec
    bbox_max: Vec
    triangles: int
    node_positions: dict[str, Vec]


def load_export_proxy(path: Path) -> tuple[Mesh, ExportProxyMeta]:
    """A `<id>.proxy.json` from `tools/export-glb.ts`: the proxy mesh, already in the contract
    frame, and the facts about the full mesh.

    The proxy is about 30,000 triangles and at most `PROXY_MAX_TRIANGLES`, the export's cap: the
    simplifier lands a little over its target, and the fixtures give 29,999 to 30,081. A proxy
    above the cap is refused, because the export itself would not have written it. Anything
    malformed raises `ValueError` naming the key.
    """
    try:
        parsed: object = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: could not read the proxy: {error}") from error
    if not isinstance(parsed, dict):
        raise ValueError(f"{path}: expected a JSON object at the top level")
    fields = cast("dict[str, object]", parsed)
    vertices = _float_table(fields, "vertices", path)
    faces = _index_table(fields, "faces", path)
    try:
        mesh = Mesh(vertices, faces)
    except ValueError as error:
        raise ValueError(f"{path}: {error}") from error
    if len(mesh.faces) > PROXY_MAX_TRIANGLES:
        raise ValueError(
            f"{path}: the proxy has {len(mesh.faces):,} triangles, over the export's cap of "
            f"{PROXY_MAX_TRIANGLES:,}"
        )
    sha256 = _field(fields, "sha256", path)
    if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-f]{64}", sha256) is None:
        raise ValueError(f"{path}: sha256 is not a lowercase hex digest of 64 characters")
    triangles = _field(fields, "triangles", path)
    if isinstance(triangles, bool) or not isinstance(triangles, int) or triangles < 0:
        raise ValueError(f"{path}: triangles is not a count")
    positions = _field(fields, "node_positions", path)
    if not isinstance(positions, dict):
        raise ValueError(f"{path}: node_positions is not an object")
    node_positions = {
        str(name): _vec(position, f"node_positions[{name!r}]", path)
        for name, position in cast("dict[object, object]", positions).items()
    }
    meta = ExportProxyMeta(
        sha256=sha256,
        bbox_min=_vec(_field(fields, "bbox_min", path), "bbox_min", path),
        bbox_max=_vec(_field(fields, "bbox_max", path), "bbox_max", path),
        triangles=triangles,
        node_positions=node_positions,
    )
    return mesh, meta


def _field(fields: dict[str, object], key: str, path: Path) -> object:
    if key not in fields:
        raise ValueError(f"{path}: {key} is missing")
    return fields[key]


def _vec(value: object, where: str, path: Path) -> Vec:
    if (
        not isinstance(value, list)
        or len(cast("list[object]", value)) != 3
        or not all(
            isinstance(part, int | float) and not isinstance(part, bool)
            for part in cast("list[object]", value)
        )
    ):
        raise ValueError(f"{path}: {where} is not three numbers")
    x, y, z = cast("list[float]", value)
    return (float(x), float(y), float(z))


def _table(fields: dict[str, object], key: str, path: Path) -> NDArray[np.generic]:
    """The `(N, 3)` table of numbers at `key`, as numpy read it."""
    import numpy as np

    value = _field(fields, key, path)
    if not isinstance(value, list):
        raise ValueError(f"{path}: {key} is not a list")
    try:
        array = np.array(cast("list[object]", value))
    except ValueError as error:
        raise ValueError(f"{path}: {key} is not a table of numbers: {error}") from error
    if array.ndim != 2 or array.shape[1] != 3 or array.dtype.kind not in {"i", "f"}:
        raise ValueError(f"{path}: {key} is not a table of rows of 3 numbers")
    return array


def _float_table(fields: dict[str, object], key: str, path: Path) -> NDArray[np.float64]:
    import numpy as np

    return _table(fields, key, path).astype(np.float64)


def _index_table(fields: dict[str, object], key: str, path: Path) -> NDArray[np.int64]:
    import numpy as np

    table = _table(fields, key, path)
    # A face index of 1.5 must be refused, not truncated into a different triangle.
    if table.dtype.kind != "i":
        raise ValueError(f"{path}: {key} holds numbers that are not whole")
    return table.astype(np.int64)


def add_wheel_proxies(
    mesh: Mesh,
    anchors: Mapping[str, Vec],
    radii_m: Mapping[str, float],
    widths_m: Mapping[str, float],
) -> Mesh:
    """The mesh plus four 24-sided prisms for the tires: the photos show wheels, and the base
    car has none.

    Each prism is centered on its anchor, with its axis along X, so seen from the side it is a
    24-gon of the tire's radius. All three mappings are keyed by anchor name: `wheel_FL`,
    `wheel_FR`, `wheel_RL` and `wheel_RR`. `anchors` may hold other names too (a GLB's
    `node_positions` does), but `radii_m` and `widths_m` hold those four and nothing else, so an
    axle-keyed mapping (`front`, `rear`) raises `ValueError` instead of being half-used.
    """
    import numpy as np

    for label, mapping, strict in (
        ("anchors", anchors, False),
        ("radii_m", radii_m, True),
        ("widths_m", widths_m, True),
    ):
        missing = [name for name in WHEEL_ANCHORS if name not in mapping]
        extra = [name for name in mapping if name not in WHEEL_ANCHORS] if strict else []
        if missing or extra:
            raise ValueError(
                f"{label} must be keyed by the anchor names {list(WHEEL_ANCHORS)}"
                f" (missing {missing}, unexpected {extra})"
            )
    vertices = [mesh.vertices]
    faces = [mesh.faces]
    count = len(mesh.vertices)
    for name in WHEEL_ANCHORS:
        radius, width = radii_m[name], widths_m[name]
        if not (radius > 0 and width > 0):
            raise ValueError(f"{name}: radius and width must be positive, not {radius} and {width}")
        prism_vertices, prism_faces = _prism(anchors[name], radius, width)
        vertices.append(prism_vertices)
        faces.append(prism_faces + count)
        count += len(prism_vertices)
    return Mesh(np.concatenate(vertices), np.concatenate(faces))


def _prism(
    center: Vec, radius: float, width: float
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """A `WHEEL_SIDES`-gon prism along X: two rings of vertices, then the two cap centers.
    Triangles wind outward."""
    import numpy as np

    n = WHEEL_SIDES
    angle = np.arange(n) * (2 * math.pi / n)
    cx, cy, cz = center
    ring_y = cy + radius * np.cos(angle)
    ring_z = cz + radius * np.sin(angle)
    near, far = cx - width / 2, cx + width / 2
    vertices = np.concatenate(
        [
            np.column_stack([np.full(n, near), ring_y, ring_z]),
            np.column_stack([np.full(n, far), ring_y, ring_z]),
            [[near, cy, cz], [far, cy, cz]],
        ]
    )
    k = np.arange(n, dtype=np.int64)
    k_next = (k + 1) % n
    near_ring, far_ring = k, k + n
    near_next, far_next = k_next, k_next + n
    near_center = np.full(n, 2 * n, dtype=np.int64)
    far_center = np.full(n, 2 * n + 1, dtype=np.int64)
    faces = np.concatenate(
        [
            np.column_stack([near_ring, near_next, far_next]),
            np.column_stack([near_ring, far_next, far_ring]),
            np.column_stack([far_center, far_ring, far_next]),
            np.column_stack([near_center, near_next, near_ring]),
        ]
    )
    return vertices, faces


class CameraInsideMeshError(ValueError):
    """The camera is at or behind part of the mesh, so a pinhole cannot project it."""


@dataclass(frozen=True)
class Camera:
    """A pinhole looking at the bbox center of the mesh it renders. See the module notes for the
    angles. `focal_mm` is the 35 mm equivalent."""

    azimuth_deg: float
    elevation_deg: float
    distance_m: float
    focal_mm: float
    roll_deg: float = 0.0


def _basis(cam: Camera) -> tuple[NDArray[np.float64], ...]:
    """`(x, y, forward, away)` of the camera, as unit vectors in the contract frame: image right,
    image up, the view direction, and from the target toward the camera."""
    import numpy as np

    azimuth = math.radians(cam.azimuth_deg)
    elevation = math.radians(cam.elevation_deg)
    away = np.array(
        [
            math.sin(azimuth) * math.cos(elevation),
            math.sin(elevation),
            -math.cos(azimuth) * math.cos(elevation),
        ]
    )
    forward = -away
    horizontal = math.hypot(forward[0], forward[2])
    if horizontal < 1e-9:
        raise ValueError(f"the camera looks straight up or down (elevation {cam.elevation_deg})")
    right = np.array([-forward[2] / horizontal, 0.0, forward[0] / horizontal])
    up = np.cross(right, forward)
    roll = math.radians(cam.roll_deg)
    cos, sin = math.cos(roll), math.sin(roll)
    return (right * cos + up * sin, up * cos - right * sin, forward, away)


def project_points(vertices: NDArray[np.float64], cam: Camera) -> NDArray[np.float64]:
    """Image-plane points `(N, 2)`, x to the right and y up, in units of the sensor width, before
    any framing. This is what `render_mask` rasterizes.

    The camera looks at the bbox center of `vertices`, so pass the whole mesh. A vertex at or
    behind the camera plane raises `CameraInsideMeshError`, a `ValueError`.
    """
    import numpy as np

    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise ValueError(f"vertices must be (N, 3) with N above 0, not {vertices.shape}")
    if not (cam.distance_m > 0 and cam.focal_mm > 0):
        raise ValueError("the camera's distance and focal length must be positive")
    center = (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    x_axis, y_axis, forward, away = _basis(cam)
    offsets = vertices - (center + cam.distance_m * away)
    depth = offsets @ forward
    if float(depth.min()) <= _NEAR_M:
        raise CameraInsideMeshError(
            f"the camera, {cam.distance_m} m from the bbox center, is inside or behind the mesh"
        )
    scale = cam.focal_mm / SENSOR_WIDTH_MM
    return np.column_stack([scale * (offsets @ x_axis) / depth, scale * (offsets @ y_axis) / depth])


def camera_to_blender(cam: Camera, target: Vec) -> dict[str, object]:
    """What `render_views.py` needs to place a Blender camera where `project_points` puts its
    pinhole: `{location_blender, look_at_blender, roll_deg, focal_mm}`.

    `target` is the mesh's bbox center in the contract frame. Both points go through `frames`.
    In Blender, aim the camera's -Z at `look_at_blender` with Y up (`to_track_quat('-Z', 'Y')`),
    rotate it by `roll_deg` about its own Z, set the sensor width to 36 mm with horizontal fit,
    and `focal_mm` is the lens: it is the 35 mm equivalent.
    """
    import numpy as np

    away = _basis(cam)[3]
    location = cast("Vec", tuple(float(c) for c in np.array(target) + cam.distance_m * away))
    return {
        "location_blender": contract_to_blender(location),
        "look_at_blender": contract_to_blender(target),
        "roll_deg": cam.roll_deg,
        "focal_mm": cam.focal_mm,
    }


def _fit_to_canvas(
    points: NDArray[np.float64], size: int
) -> tuple[NDArray[np.float64], float, float, float]:
    """Frame `(N, 2)` points `(u, v)`, v up, on a `size` x `size` canvas: the scale is uniform and
    the box of the points is centered, `FRAME_MARGIN_PX` from the edge at its longer side.
    Returns the pixels `(col, row)`, the scale in pixels per unit, and the pixel `(col, row)` of
    `(u, v) = (0, 0)`."""
    import numpy as np

    low = points.min(axis=0)
    high = points.max(axis=0)
    span = float((high - low).max())
    available = size - 1 - 2 * FRAME_MARGIN_PX
    scale = available / span if span > 0 else 1.0
    left = FRAME_MARGIN_PX + (available - scale * (high[0] - low[0])) / 2
    top = FRAME_MARGIN_PX + (available - scale * (high[1] - low[1])) / 2
    origin_col = left - scale * low[0]
    origin_row = top + scale * high[1]
    pixels = np.column_stack([origin_col + scale * points[:, 0], origin_row - scale * points[:, 1]])
    return pixels, scale, float(origin_col), float(origin_row)


def _fill(pixels: NDArray[np.float64], faces: NDArray[np.int64], size: int) -> NDArray[np.bool_]:
    """The union of the triangles, filled. Vertices are rounded to whole pixels first, because
    Pillow truncates the floats it is given, and that would shift every edge by half a pixel."""
    import numpy as np
    from PIL import Image, ImageDraw

    image = Image.new("L", (size, size), 0)
    if len(faces) > 0:
        corners = np.rint(pixels).astype(np.int64)[faces].reshape(len(faces), 6).tolist()
        draw = ImageDraw.Draw(image)
        for corner in corners:
            draw.polygon(corner, fill=255)
    return np.asarray(image) > 0


def render_mask(mesh: Mesh, cam: Camera, size: int = 256) -> NDArray[np.bool_]:
    """The silhouette of the mesh from `cam`: its projected triangles, filled, on a `size` x
    `size` canvas. The canvas is framed on the projected bbox, not on a photo, and
    `align_to_photo` brings the two together."""
    pixels, _scale, _col, _row = _fit_to_canvas(project_points(mesh.vertices, cam), size)
    return _fill(pixels, mesh.faces, size)


@dataclass(frozen=True, eq=False)
class OrthoMask:
    """A side silhouette and how to read it in meters. The image is the car seen from its right
    side (+X) with the nose to the right, so a pixel `(col, row)` is at
    `z = -(col - origin_px[0]) / px_per_m` and `y = (origin_px[1] - row) / px_per_m`. A pixel is
    at its index, so `origin_px` is the column and row of contract `(z = 0, y = 0)`."""

    mask: NDArray[np.bool_]
    px_per_m: float
    origin_px: tuple[float, float]


def render_ortho_side(mesh: Mesh, size: int = 512) -> OrthoMask:
    """The silhouette along X, orthographic, framed on its own bbox. `px_per_m` and `origin_px`
    let `measure_side` (Task 13) turn pixel centers back into meters."""
    import numpy as np

    points = np.column_stack([-mesh.vertices[:, 2], mesh.vertices[:, 1]])
    pixels, scale, origin_col, origin_row = _fit_to_canvas(points, size)
    return OrthoMask(_fill(pixels, mesh.faces, size), scale, (origin_col, origin_row))


@dataclass(frozen=True)
class CameraFit:
    """The best camera found, its IoU (`aligned_iou`, after aligning the render to the photo), and
    whether its roll ended at the bound (9 degrees or more of the 10 allowed): such a photo is
    probably an unusable reference, a tilted camera, and says nothing about the mesh, but the
    search misses some tilted photos, so the flag is advisory. `seed` is the seed the search ran
    with, so a stage can log it. `camera.focal_mm` is `FIT_FOCAL_MM`: focal is not searched.
    """

    camera: Camera
    iou: float
    roll_at_bound: bool
    seed: int = 0


def _clamped(params: _Params) -> _Params:
    azimuth, elevation, distance, roll = params
    return (
        azimuth % 360.0,
        min(max(elevation, _ELEVATION_RANGE_DEG[0]), _ELEVATION_RANGE_DEG[1]),
        min(max(distance, _DISTANCE_RANGE_M[0]), _DISTANCE_RANGE_M[1]),
        min(max(roll, -ROLL_LIMIT_DEG), ROLL_LIMIT_DEG),
    )


def _nudged(params: _Params, index: int, delta: float) -> _Params:
    values = list(params)
    values[index] += delta
    azimuth, elevation, distance, roll = values
    return _clamped((azimuth, elevation, distance, roll))


def fit_camera(
    mesh: Mesh,
    photo_mask: NDArray[np.bool_],
    *,
    mirrored: bool = False,
    seed: int = 0,
    size: int = 256,
) -> CameraFit:
    """The camera whose render of `mesh` best matches `photo_mask`, by `aligned_iou`.

    Searches azimuth, elevation, distance and roll in at most `MAX_FIT_RENDERS` renders, under
    the cap of 600 (ruling R90): a grid at roll 0, a roll prescreen of the best cells, then staged
    coordinate descent that narrows to the best candidates at ever smaller steps (the schedule is
    set out at `_GRID_AZIMUTHS_DEG`). Roll stays within 10 degrees either way. Focal length is not
    searched, because it cannot change the score; the camera carries `FIT_FOCAL_MM`. A score is
    never computed twice for one camera. The seed sets the order the four parameters are visited
    in, and is recorded in the result. `mirrored` flips the photo mask left to right first. A
    camera that puts a vertex behind it scores 0.0.
    """
    import numpy as np

    photo = np.asarray(photo_mask, dtype=np.bool_)
    if photo.ndim != 2 or not photo.any():
        raise ValueError("the photo mask must be a 2-D mask with at least one pixel set")
    if len(mesh.faces) == 0:
        raise ValueError("the mesh has no triangles to render")
    if mirrored:
        photo = np.ascontiguousarray(photo[:, ::-1])
    order_source = np.random.default_rng(seed)
    scores: dict[_Params, float] = {}

    def score(params: _Params) -> float:
        known = scores.get(params)
        if known is not None:
            return known
        azimuth, elevation, distance, roll = params
        try:
            rendered = render_mask(
                mesh, Camera(azimuth, elevation, distance, FIT_FOCAL_MM, roll), size
            )
        except CameraInsideMeshError:
            value = 0.0
        else:
            value = aligned_iou(rendered, photo)
        scores[params] = value
        return value

    grid: list[_Params] = [
        (azimuth, elevation, distance, 0.0)
        for azimuth in _GRID_AZIMUTHS_DEG
        for elevation in _GRID_ELEVATIONS_DEG
        for distance in _GRID_DISTANCES_M
    ]
    # `sorted` is stable, so cells with equal IoU keep the grid's order.
    ranked = sorted(grid, key=lambda params: -score(params))[:_PRESCREEN_CELLS]
    pool: list[tuple[float, _Params]] = []
    for cell in ranked:
        tilted = [_nudged(cell, 3, sign * _PRESCREEN_ROLL_DEG) for sign in (1.0, -1.0)]
        best_roll = max([cell, *tilted], key=score)
        pool.append((score(best_roll), best_roll))
    for keep, levels in _STAGES:
        refined: list[tuple[float, _Params]] = []
        for current_iou, current in sorted(pool, key=lambda entry: -entry[0])[:keep]:
            for level in levels:
                for index in (int(i) for i in order_source.permutation(len(_FIRST_STEPS))):
                    step = _FIRST_STEPS[index] / 2**level
                    # Both directions are tried from where the parameter stands, and the better
                    # one is kept only if it beats it.
                    moved, moved_iou = current, current_iou
                    for delta in (-step, step):
                        candidate = _nudged(current, index, delta)
                        candidate_iou = score(candidate)
                        if candidate_iou > moved_iou:
                            moved, moved_iou = candidate, candidate_iou
                    current, current_iou = moved, moved_iou
            refined.append((current_iou, current))
        pool = refined
    best_iou, best_params = max(pool, key=lambda entry: entry[0])
    azimuth, elevation, distance, roll = best_params
    return CameraFit(
        camera=Camera(azimuth, elevation, distance, FIT_FOCAL_MM, roll),
        iou=best_iou,
        roll_at_bound=abs(roll) >= ROLL_AT_BOUND_DEG,
        seed=seed,
    )
