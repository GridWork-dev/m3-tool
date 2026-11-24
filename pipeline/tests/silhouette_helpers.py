"""A side-view car drawn with Pillow, for the silhouette and `proportion` tests.

The car has the real E46 coupe's length, height and wheelbase (4492, 1372 and 2731 mm), a
blocky body, a cabin and two tires of a known radius, nose toward the left, on `#d9d9d9`. The
body's underside is 150 mm above the ground and the tires reach the ground, so each tire shows
below the sill line as a bump of a known circle. Nothing is antialiased, so the truth is exact
to a pixel.
"""

from dataclasses import dataclass

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
) -> tuple[Image.Image, CarTruth]:
    """The car at `scale` (1.0 is 0.25 px per mm), with its wheelbase and height optionally
    stretched, on a background margin of `margin_px` (default: 100 px at scale 1)."""
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
    body = [
        (0, SILL_MM),
        (0, 520),
        (300, 600),
        (1100, 780),
        (1750, height_mm),
        (2800, height_mm),
        (3500, 830),
        (4300, 800),
        (LENGTH_MM, 700),
        (LENGTH_MM, SILL_MM),
    ]
    draw.polygon([at(x, y) for x, y in body], fill=BODY)
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
