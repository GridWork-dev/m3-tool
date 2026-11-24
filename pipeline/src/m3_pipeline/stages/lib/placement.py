"""Placement math: where a generated car's parts go, from the data and from the mesh.

Everything here is plain geometry on tuples. Names say their frame; without one, a function works
in the contract frame (meters, +Y up, nose toward -Z, the driver at -X, the origin on the ground
under the middle of the wheelbase). `propose_orientation` and `apply_orientation` are the
exception: they work on a freshly imported mesh in the Blender frame, whose orientation is not yet
known. Standard library plus `dims` and `frames`, so it imports before numpy does.

The wheel anchors come from the data (track, wheelbase, stock tires), never from the mesh. The
mount anchors, the module cut planes and the interior fit are ESTIMATES: each number is a named
constant below, and the driver's-seat review (Task 16) tunes them.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from m3_pipeline.stages.lib.dims import Dimensions
from m3_pipeline.stages.lib.frames import CutBox, Vec

# propose_orientation: the outer slab of the up axis that is compared, and the top share of the
# vertices whose centroid shows where the roof sits.
_SLAB_FRACTION = 0.15
_ROOF_FRACTION = 0.10

# axis_scales: the divergence from the data that is a wrong mesh, not a slightly wrong one.
_MAX_DIVERGENCE = 0.05

# body_width_m: the band above the lowest point that sits below the door mirrors.
_BODY_BAND_M = (0.30, 0.90)

# wheel_cylinders: the cut radius as a multiple of the tire radius, and the margin past the tire's
# section width on each side. A tread quad of an n-sided tire has its center at r * cos(pi / n),
# just under its radius r, so the cut must reach past the data radius to take the tread, and a
# generated tire runs a little large. The factor is a plan value that the calibration tasks tune.
_WHEEL_CUT_RADIUS_FACTOR = 1.04
_WHEEL_CUT_AXIAL_MARGIN_M = 0.010

# mount_anchor_positions (estimates).
_FRONT_LIP_Y_M = 0.18
_DECK_HEIGHT_FRACTION = 0.72  # the trunk deck, as a share of the car's height
_TRUNK_MOUNT_FROM_TAIL_M = 0.50
_WING_RISE_M = 0.14  # above the deck
_WING_FROM_TAIL_M = 0.25
_EXHAUST_X_M = 0.52
_EXHAUST_Y_M = 0.30

# module_cut_planes (estimates). Boxes reach `_CUT_MARGIN_M` past the car, so a cut along a box
# face never leaves a sliver of the part behind.
_CUT_MARGIN_M = 0.05
_BUMPER_DEPTH_M = 0.45
_FRONT_BUMPER_TOP_Y_M = 0.70
_REAR_BUMPER_TOP_Y_M = 0.80
_TRUNK_LID_FROM_TAIL_M = (0.45, 1.00)  # nearest and farthest distance from the tail
_TRUNK_LID_Y_M = (0.80, 1.10)
_ROOF_MIN_Y_FRACTION = 0.85  # of the car's height
_ROOF_Z_FRACTION = (-0.13, 0.17)  # of the car's length: the roof sits rearward

# interior_fit (estimates).
_SEAT_BELOW_EYE_M = 0.60
_SEAT_BEHIND_EYE_M = 0.25
_STEERING_BELOW_EYE_M = 0.25
_STEERING_FORWARD_OF_EYE_M = 0.60
_STEERING_DIAMETER_M = 0.365
_DASH_INSET_M = 0.30  # the dash is this much narrower than the car
_CABIN_FLOOR_Y_M = 0.22
_CABIN_ROOF_CLEARANCE_M = 0.03
_CABIN_WALL_INSET_M = 0.12
_CABIN_FRONT_FROM_FRONT_AXLE_M = 0.45
_CABIN_REAR_FROM_REAR_AXLE_M = 0.30

_AXIS = re.compile(r"^(?P<sign>[+-])(?P<axis>[xyz])$")


class ScaleRefused(ValueError):
    """A mesh differs from the data by more than the allowed share on some axis."""


@dataclass(frozen=True)
class Orientation:
    """Which axes of the imported mesh are up and toward the nose, like `+z` and `-y`."""

    up: str
    nose: str


@dataclass(frozen=True)
class InteriorFit:
    eye: Vec
    seat_driver: Vec
    mount_seat_L: Vec
    mount_seat_R: Vec
    mount_steering: Vec
    dash_target_width_m: float
    steering_diameter_m: float
    cabin_box: CutBox


def propose_orientation(vertices: Sequence[Vec]) -> Orientation:
    """Up and nose axes of a freshly imported car, from its shape alone.

    The shortest extent is up (a coupe is 4.49 x 1.78 x 1.37 m) and the longest is the length.
    Up points to the end of the up axis whose outer 15% slab has the smaller footprint (a
    greenhouse is narrower than the sills). The nose points to the end of the length axis that
    is farther from the centroid of the top 10% of the vertices by height (a coupe's roof sits
    rearward). A mirrored mesh cannot be told from a mirrored car: this is a rotation only.
    """
    if len(vertices) < 4:
        raise ValueError(f"need at least 4 vertices to orient a car, got {len(vertices)}")
    lows = [min(v[a] for v in vertices) for a in range(3)]
    highs = [max(v[a] for v in vertices) for a in range(3)]
    extents = [highs[a] - lows[a] for a in range(3)]
    up_axis, _, length_axis = sorted(range(3), key=lambda a: extents[a])
    if extents[length_axis] <= 0:
        raise ValueError("all vertices are at one point, so there is no car to orient")

    across = [a for a in range(3) if a != up_axis]
    slab = _SLAB_FRACTION * extents[up_axis]
    top = [v for v in vertices if v[up_axis] >= highs[up_axis] - slab]
    bottom = [v for v in vertices if v[up_axis] <= lows[up_axis] + slab]
    up_sign = 1 if _footprint(top, across) <= _footprint(bottom, across) else -1

    count = max(1, math.ceil(_ROOF_FRACTION * len(vertices)))
    highest = sorted(vertices, key=lambda v: up_sign * v[up_axis], reverse=True)[:count]
    centroid = sum(v[length_axis] for v in highest) / count
    nose_sign = 1 if highs[length_axis] - centroid >= centroid - lows[length_axis] else -1
    return Orientation(up=_label(up_sign, up_axis), nose=_label(nose_sign, length_axis))


def apply_orientation(vertices: Sequence[Vec], o: Orientation) -> list[Vec]:
    """The vertices rotated to Z up with the nose toward +Y. A proper rotation: no mirroring."""
    up_axis, up_sign = _parse_axis(o.up)
    nose_axis, nose_sign = _parse_axis(o.nose)
    if up_axis == nose_axis:
        raise ValueError(f"up {o.up!r} and nose {o.nose!r} are on the same axis")
    side_axis = 3 - up_axis - nose_axis
    # x' = nose x up, so the new frame is right-handed. e_a x e_b is +e_c when (a, b, c) is a
    # cyclic permutation of (x, y, z), and -e_c otherwise.
    cyclic = 1 if (up_axis - nose_axis) % 3 == 1 else -1
    side_sign = nose_sign * up_sign * cyclic
    return [
        (side_sign * v[side_axis], nose_sign * v[nose_axis], up_sign * v[up_axis]) for v in vertices
    ]


def body_width_m(vertices: Sequence[Vec], y_band: tuple[float, float] = _BODY_BAND_M) -> float:
    """Width of the car's body in meters, from contract-frame vertices already scaled to the
    data's length.

    Only vertices inside `y_band`, measured upward from the lowest point (so a mesh that sits
    anywhere in y gives the same answer), count: the band is below the door mirrors, which the
    data's width leaves out. The width is the x extent of those vertices, which for a mesh
    centered on x = 0 is 2 * max|x| and for an off-center one does not depend on the offset.
    """
    if not vertices:
        raise ValueError("no vertices to measure a width from")
    lowest = min(v[1] for v in vertices)
    low, high = y_band
    xs = [v[0] for v in vertices if low <= v[1] - lowest <= high]
    if not xs:
        raise ValueError(f"no vertex lies in the height band {low} to {high} m above the lowest")
    return max(xs) - min(xs)


def axis_scales(
    measured_lhw: Vec, expected: Dimensions, max_divergence: float = _MAX_DIVERGENCE
) -> Vec:
    """Per-axis factors `(length, height, width)` that make a measured mesh the data's size.

    `measured_lhw` is read from the oriented mesh after uniform scaling to the data's length: the
    bounding-box length, the top above the lowest point, and `body_width_m`. The factors are
    near 1.0. Raises ScaleRefused when any is outside 1 +- `max_divergence`: a mesh that far off
    is the wrong shape, and stretching it would hide that.
    """
    wanted = (expected.length_mm / 1000, expected.height_mm / 1000, expected.width_mm / 1000)
    labels = ("length", "height", "width")
    factors: list[float] = []
    for label, measured, target in zip(labels, measured_lhw, wanted, strict=True):
        if not measured > 0:
            raise ValueError(f"measured {label} {measured} m must be positive")
        factors.append(target / measured)
    refused = [
        f"{label} x{factor:.4f} (measured {measured:.4f} m, data {target:.4f} m)"
        for label, factor, measured, target in zip(
            labels, factors, measured_lhw, wanted, strict=True
        )
        if abs(factor - 1.0) > max_divergence
    ]
    if refused:
        raise ScaleRefused(
            f"the mesh differs from the data by more than {max_divergence:.0%}: "
            + "; ".join(refused)
        )
    return (factors[0], factors[1], factors[2])


def compose_scales(uniform: float, factors_lhw: Vec) -> Vec:
    """Total `(length, height, width)` factors from the uniform step to the data's length and the
    near-1.0 factors of `axis_scales`, which are measured after that step.

    A plan carries only these totals, in `scales_blender` (through `lhw_to_blender_xyz`), so the
    uniform step is never applied twice or left out.
    """
    if not uniform > 0:
        raise ValueError(f"uniform scale {uniform} must be positive")
    length, height, width = factors_lhw
    return (uniform * length, uniform * height, uniform * width)


def wheel_anchor_positions(
    dims: Dimensions, front_radius_m: float, rear_radius_m: float
) -> dict[str, Vec]:
    """Wheel centers from the data: x = -+track/2, y = the tire radius, z = -+wheelbase/2, the
    front axle at -z and the left side at -x."""
    front_x, rear_x = dims.track_front_mm / 2000, dims.track_rear_mm / 2000
    half_base = dims.wheelbase_mm / 2000
    return {
        "wheel_FL": (-front_x, front_radius_m, -half_base),
        "wheel_FR": (front_x, front_radius_m, -half_base),
        "wheel_RL": (-rear_x, rear_radius_m, half_base),
        "wheel_RR": (rear_x, rear_radius_m, half_base),
    }


def mount_anchor_positions(dims: Dimensions) -> dict[str, Vec]:
    """Where parts attach to the base car. Estimates (see the constants), named as the asset
    contract names them."""
    half_length = dims.length_mm / 2000
    deck = _DECK_HEIGHT_FRACTION * dims.height_mm / 1000
    return {
        "mount_front_lip": (0.0, _FRONT_LIP_Y_M, -half_length),
        "mount_trunk": (0.0, deck, half_length - _TRUNK_MOUNT_FROM_TAIL_M),
        "mount_wing": (0.0, deck + _WING_RISE_M, half_length - _WING_FROM_TAIL_M),
        "mount_exhaust_L": (-_EXHAUST_X_M, _EXHAUST_Y_M, half_length),
        "mount_exhaust_R": (_EXHAUST_X_M, _EXHAUST_Y_M, half_length),
        # The interior is authored in the car's frame, so its mount is the car's origin.
        "mount_interior": (0.0, 0.0, 0.0),
    }


def module_cut_planes(dims: Dimensions) -> dict[str, CutBox]:
    """The box around each swappable body module, in the contract frame. Estimates."""
    length, width, height = dims.length_mm / 1000, dims.width_mm / 1000, dims.height_mm / 1000
    half_length = length / 2
    x = width / 2 + _CUT_MARGIN_M
    ground = -_CUT_MARGIN_M
    lid_near, lid_far = _TRUNK_LID_FROM_TAIL_M
    roof_z_front, roof_z_rear = _ROOF_Z_FRACTION
    return {
        "bumper_front": CutBox(
            (-x, ground, -half_length - _CUT_MARGIN_M),
            (x, _FRONT_BUMPER_TOP_Y_M, -half_length + _BUMPER_DEPTH_M),
        ),
        "bumper_rear": CutBox(
            (-x, ground, half_length - _BUMPER_DEPTH_M),
            (x, _REAR_BUMPER_TOP_Y_M, half_length + _CUT_MARGIN_M),
        ),
        "trunk_lid": CutBox(
            (-x, _TRUNK_LID_Y_M[0], half_length - lid_far),
            (x, _TRUNK_LID_Y_M[1], half_length - lid_near),
        ),
        "roof": CutBox(
            (-x, _ROOF_MIN_Y_FRACTION * height, roof_z_front * length),
            (x, height + _CUT_MARGIN_M, roof_z_rear * length),
        ),
    }


def decimate_ratio(triangles: int, target: int = 150_000) -> float:
    """The share of triangles to keep to reach `target`, in (0, 1]: 1.0 when already under it."""
    if triangles <= 0:
        raise ValueError(f"triangles must be positive, got {triangles}")
    return min(1.0, target / triangles)


def wheel_cylinders(
    dims: Dimensions,
    front_radius_m: float,
    rear_radius_m: float,
    front_width_m: float,
    rear_width_m: float,
    wheel_cut_radius_factor: float = _WHEEL_CUT_RADIUS_FACTOR,
) -> list[dict[str, float]]:
    """The four cylinders that mark the generated wheels for removal, in the order FL, FR, RL, RR.

    Each is `{cx, cy, cz, radius, x_min, x_max}` in the contract frame: its axis runs along x
    through the wheel anchor, its radius is `wheel_cut_radius_factor` times the tire radius, and
    it spans the tire's section width plus 10 mm on each side, centered on the anchor because the
    tire is centered on the hub.
    """
    if not wheel_cut_radius_factor > 0:
        raise ValueError(f"wheel_cut_radius_factor {wheel_cut_radius_factor} must be positive")
    anchors = wheel_anchor_positions(dims, front_radius_m, rear_radius_m)
    sizes = {
        "wheel_FL": (front_radius_m, front_width_m),
        "wheel_FR": (front_radius_m, front_width_m),
        "wheel_RL": (rear_radius_m, rear_width_m),
        "wheel_RR": (rear_radius_m, rear_width_m),
    }
    cylinders: list[dict[str, float]] = []
    for name, (cx, cy, cz) in anchors.items():
        radius, width = sizes[name]
        half_span = width / 2 + _WHEEL_CUT_AXIAL_MARGIN_M
        cylinders.append(
            {
                "cx": cx,
                "cy": cy,
                "cz": cz,
                "radius": wheel_cut_radius_factor * radius,
                "x_min": cx - half_span,
                "x_max": cx + half_span,
            }
        )
    return cylinders


def interior_fit(dims: Dimensions, eye_m: Vec) -> InteriorFit:
    """Where the interior's parts go, in the contract frame, from the data's driver eye point.
    Estimates, tuned by the driver's-seat review."""
    ex, ey, ez = eye_m
    seat_y = ey - _SEAT_BELOW_EYE_M
    seat_z = ez + _SEAT_BEHIND_EYE_M
    half_wheelbase = dims.wheelbase_mm / 2000
    half_width = dims.width_mm / 2000 - _CABIN_WALL_INSET_M
    return InteriorFit(
        eye=eye_m,
        seat_driver=(ex, seat_y, seat_z),
        # The seats sit as far from the centerline as the driver does, left at -x.
        mount_seat_L=(-abs(ex), seat_y, seat_z),
        mount_seat_R=(abs(ex), seat_y, seat_z),
        mount_steering=(ex, ey - _STEERING_BELOW_EYE_M, ez - _STEERING_FORWARD_OF_EYE_M),
        dash_target_width_m=dims.width_mm / 1000 - _DASH_INSET_M,
        steering_diameter_m=_STEERING_DIAMETER_M,
        cabin_box=CutBox(
            (-half_width, _CABIN_FLOOR_Y_M, -half_wheelbase + _CABIN_FRONT_FROM_FRONT_AXLE_M),
            (
                half_width,
                dims.height_mm / 1000 - _CABIN_ROOF_CLEARANCE_M,
                half_wheelbase - _CABIN_REAR_FROM_REAR_AXLE_M,
            ),
        ),
    )


def _label(sign: int, axis: int) -> str:
    return f"{'+' if sign > 0 else '-'}{'xyz'[axis]}"


def _parse_axis(label: str) -> tuple[int, int]:
    """`+z` as (2, +1)."""
    match = _AXIS.match(label)
    if match is None:
        raise ValueError(f"axis label {label!r} must be a sign and one of 'x', 'y', 'z'")
    return "xyz".index(match["axis"]), 1 if match["sign"] == "+" else -1


def _footprint(points: Sequence[Vec], axes: Sequence[int]) -> float:
    """Area of the bounding rectangle of `points` along two axes."""
    area = 1.0
    for axis in axes:
        values = [p[axis] for p in points]
        area *= max(values) - min(values)
    return area
