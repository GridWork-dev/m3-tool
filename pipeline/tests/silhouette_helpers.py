"""A side-view car drawn with Pillow, for the silhouette and `proportion` tests.

The car has the real E46 coupe's length, height and wheelbase (4492, 1372 and 2731 mm), a
blocky body, a cabin and two tires of a known radius, nose toward the left, on `#d9d9d9`. The
body's underside is 150 mm above the ground (or raked between two heights) and the tires reach the
ground, so each tire shows below the underside as a bump of a known circle. Nothing is
antialiased, so the truth is exact to a pixel.
"""

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

BACKGROUND = (0xD9, 0xD9, 0xD9)
BODY = (30, 30, 40)
TIRE = (20, 20, 20)

LENGTH_MM = 4492.0
HEIGHT_MM = 1372.0
WHEELBASE_MM = 2731.0
TIRE_RADIUS_MM = 330.0
SILL_MM = 150.0
_PX_PER_MM = 0.25


@dataclass(frozen=True)
class CarTruth:
    """What the drawing contains, in pixels of the image it came with."""

    length_px: float
    height_px: float
    wheelbase_px: float
    tire_radius_px: float
    front_center: tuple[float, float]
    rear_center: tuple[float, float]


def draw_car(
    scale: float = 1.0,
    *,
    wheelbase_scale: float = 1.0,
    height_scale: float = 1.0,
    margin_px: int | None = None,
    underside_mm: tuple[float, float] = (SILL_MM, SILL_MM),
    splitter_mm: tuple[float, float] | None = None,
) -> tuple[Image.Image, CarTruth]:
    """The car at `scale` (1.0 is 0.25 px per mm), with its wheelbase and height optionally
    stretched, on a background margin of `margin_px` (default: 100 px at scale 1).

    `underside_mm` is the height of the body's underside at the nose and at the tail (a rake when
    they differ). `splitter_mm` is `(width, drop)`: a flat splitter under the nose, that wide and
    reaching that far below the underside."""
    s = _PX_PER_MM * scale
    margin = round(100 * scale) if margin_px is None else margin_px
    height_mm = HEIGHT_MM * height_scale
    wheelbase_mm = WHEELBASE_MM * wheelbase_scale
    width = round(LENGTH_MM * s) + 2 * margin
    canvas_height = round(max(height_mm, HEIGHT_MM) * s) + 2 * margin
    ground = canvas_height - margin

    def at(x_mm: float, y_mm: float) -> tuple[float, float]:
        return margin + x_mm * s, ground - y_mm * s

    image = Image.new("RGB", (width, canvas_height), BACKGROUND)
    draw = ImageDraw.Draw(image)
    nose_sill, tail_sill = underside_mm
    body = [
        (0, nose_sill),
        (0, 520),
        (300, 600),
        (1100, 780),
        (1750, height_mm),
        (2800, height_mm),
        (3500, 830),
        (4300, 800),
        (LENGTH_MM, 700),
        (LENGTH_MM, tail_sill),
    ]
    draw.polygon([at(x, y) for x, y in body], fill=BODY)
    if splitter_mm is not None:
        width_mm, drop_mm = splitter_mm
        lip = [(0, nose_sill), (width_mm, nose_sill), (width_mm, nose_sill - drop_mm)]
        draw.polygon([at(x, y) for x, y in [*lip, (0, nose_sill - drop_mm)]], fill=BODY)
    front_x = (LENGTH_MM - wheelbase_mm) / 2
    centers = [at(front_x, TIRE_RADIUS_MM), at(front_x + wheelbase_mm, TIRE_RADIUS_MM)]
    radius = TIRE_RADIUS_MM * s
    for cx, cy in centers:
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=TIRE)
    truth = CarTruth(
        length_px=LENGTH_MM * s,
        height_px=height_mm * s,
        wheelbase_px=wheelbase_mm * s,
        tire_radius_px=radius,
        front_center=centers[0],
        rear_center=centers[1],
    )
    return image, truth


def add_contact_shadows(
    image: Image.Image,
    truth: CarTruth,
    *,
    size: tuple[int, int] = (120, 14),
    inward_px: int = 20,
    lift_px: int = 0,
    color: tuple[int, int, int] = (128, 128, 128),
) -> None:
    """Gray ellipses of `size` pixels on the ground under each tire, each shifted `inward_px`
    toward the middle of the car and `lift_px` above the ground. They are part of the picture the
    way a floor shadow is, and not of the car."""
    draw = ImageDraw.Draw(image)
    width, height = size
    for (cx, cy), shift in ((truth.front_center, inward_px), (truth.rear_center, -inward_px)):
        bottom = cy + truth.tire_radius_px - lift_px
        x = cx + shift
        draw.ellipse((x - width / 2, bottom - height, x + width / 2, bottom), fill=color)


@dataclass(frozen=True)
class ProxyRender:
    """Task 9's side render of a car-profile mesh with its real wheel proxies, and the truth in
    its pixels: the columns of the wheel centers, the tire radius, and the scale."""

    mask: NDArray[np.bool_]
    px_per_m: float
    front_column: float
    rear_column: float
    tire_radius_px: float


def render_proxy_car(size: int, underside_m: tuple[float, float] = (0.15, 0.15)) -> ProxyRender:
    """The E46 coupe's side plates (4.492 m long, 1.372 m tall, wheelbase 2.731 m, underside at
    `underside_m` nose and tail) plus `add_wheel_proxies`' 24-sided tires of the stock 225/45ZR18,
    seen by `render_ortho_side` on a `size` px canvas: nose toward the right."""
    from m3_pipeline.stages.lib.dims import tire_radius_m, tire_width_m
    from m3_pipeline.stages.lib.projection import Mesh, add_wheel_proxies, render_ortho_side

    half = LENGTH_MM / 2000
    nose_sill, tail_sill = underside_m
    pieces = [
        [(-half, nose_sill), (half, tail_sill), (half, 0.80), (-half, 0.80)],  # (z, y)
        [(-0.55, 0.80), (1.65, 0.80), (1.15, 1.372), (0.05, 1.372)],  # the cabin, toward the tail
    ]
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for x in (-0.89, 0.89):
        for piece in pieces:
            base = len(vertices)
            vertices += [(x, y, z) for z, y in piece]
            faces += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    body = Mesh(np.array(vertices, dtype=np.float64), np.array(faces, dtype=np.int64))

    radius, width = tire_radius_m("225/45ZR18"), tire_width_m("225/45ZR18")
    front_z, rear_z = -WHEELBASE_MM / 2000, WHEELBASE_MM / 2000
    anchors = {
        "wheel_FL": (0.75, radius, front_z),
        "wheel_FR": (-0.75, radius, front_z),
        "wheel_RL": (0.75, radius, rear_z),
        "wheel_RR": (-0.75, radius, rear_z),
    }
    mesh = add_wheel_proxies(
        body, anchors, dict.fromkeys(anchors, radius), dict.fromkeys(anchors, width)
    )
    ortho = render_ortho_side(mesh, size)
    origin_column = ortho.origin_px[0]
    # A pixel's z is -(column - origin) / px_per_m, so a wheel at z sits at origin - z * px_per_m.
    return ProxyRender(
        mask=ortho.mask,
        px_per_m=ortho.px_per_m,
        front_column=origin_column - front_z * ortho.px_per_m,
        rear_column=origin_column - rear_z * ortho.px_per_m,
        tire_radius_px=radius * ortho.px_per_m,
    )
