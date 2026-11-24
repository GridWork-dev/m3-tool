"""Side-view silhouette measures, for the `proportion` check of a synthesized side view.

A synthesized side view is a car on a plain light background. `mask_from_image` cuts the car
out, `measure_side` reads its length, height and wheel positions off the mask, and
`check_proportions` compares the ratios with the real car's dimensions. The scale of the image is
unknown, so everything is a ratio and nothing here converts to meters.

Pixel coordinates count a pixel's center at its integer index: the lowest filled pixel of a column
at row `y` ends at `y + 0.5`, and a silhouette that fills columns `x0..x1` is `x1 - x0 + 1` wide.
numpy and Pillow only (no scipy), and no network. Both are imported inside the functions that use
them, so importing this module (the `proportion` stage registers when the CLI loads) stays cheap:
`test_importing_the_cli_loads_no_heavy_dependencies` holds the CLI to that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from m3_pipeline.stages.lib.dims import Dimensions

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray
    from PIL import Image

# The corner patches and the border strip are this many pixels deep.
_STRIP = 4
# A side of the border may differ from the background over at most this share of its strip.
# A silhouette that runs off an edge covers a stretch of it; a vignette, a gradient or a floor
# shadow along the edge covers most of it.
_MAX_STRIP_SHARE = 0.5
# The opening drops specks and hairlines narrower than this many pixels.
_OPENING_PX = 5
# A wheel is a bump of the bottom contour at least this many columns wide.
_MIN_WHEEL_COLUMNS = 5
# The sill line is the median of the bottom contour. A column counts as part of a wheel when its
# bottom lies more than this share of the silhouette's height below the sill line.
_SILL_MARGIN_SHARE = 0.01


class SilhouetteError(ValueError):
    """The picture cannot be measured: no clean background, no car, or no two wheels."""


def mask_from_image(img: Image.Image, *, tolerance: int = 24) -> NDArray[np.bool_]:
    """The car's silhouette: True where the picture differs from its plain background.

    The background color is the mean of the four corner patches. The corners must agree within
    `tolerance` (a color distance in RGB), and so must a 4-px strip along the whole border: a
    gradient, a vignette or a floor shadow has no single background color to subtract. The
    mask is the pixels farther than `tolerance` from that color, opened to drop specks.

    Raises SilhouetteError("background not uniform"), SilhouetteError("touches the image border")
    or SilhouetteError("empty"). An image too small to hold a car and a border is "empty".
    """
    import numpy as np

    rgb = np.asarray(img.convert("RGB"), dtype=np.float64)
    height, width = rgb.shape[0], rgb.shape[1]
    if min(height, width) < 4 * _STRIP:
        raise SilhouetteError("empty")

    corners = np.stack(
        [
            rgb[:_STRIP, :_STRIP].mean(axis=(0, 1)),
            rgb[:_STRIP, -_STRIP:].mean(axis=(0, 1)),
            rgb[-_STRIP:, :_STRIP].mean(axis=(0, 1)),
            rgb[-_STRIP:, -_STRIP:].mean(axis=(0, 1)),
        ]
    )
    spread = np.linalg.norm(corners[:, None, :] - corners[None, :, :], axis=-1).max()
    if spread > tolerance:
        raise SilhouetteError("background not uniform")
    background = corners.mean(axis=0)

    differs = np.linalg.norm(rgb - background, axis=-1) > tolerance
    strips = (
        differs[:_STRIP, :],
        differs[-_STRIP:, :],
        differs[:, :_STRIP],
        differs[:, -_STRIP:],
    )
    if any(float(strip.mean()) > _MAX_STRIP_SHARE for strip in strips):
        raise SilhouetteError("background not uniform")

    mask = _open(differs)
    if not mask.any():
        raise SilhouetteError("empty")
    if mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any():
        raise SilhouetteError("touches the image border")
    return mask


def _open(mask: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """Morphological opening with a square window: erode (min filter), then dilate (max)."""
    import numpy as np
    from PIL import Image, ImageFilter

    image = Image.fromarray(mask.astype(np.uint8) * 255)
    opened = image.filter(ImageFilter.MinFilter(_OPENING_PX)).filter(
        ImageFilter.MaxFilter(_OPENING_PX)
    )
    return np.asarray(opened) > 127


@dataclass(frozen=True)
class SideMeasure:
    """What a side silhouette says, in pixels. `front_center` and `rear_center` are `(x, y)`.

    The synthesized side view has the nose toward the left of the image, so the left wheel is the
    front one. A mask that faces right swaps the two names; the wheelbase and radius don't care.
    """

    length_px: float
    height_px: float
    wheelbase_px: float
    wheel_radius_px: float
    front_center: tuple[float, float]
    rear_center: tuple[float, float]


def measure_side(mask: NDArray[np.bool_]) -> SideMeasure:
    """Length and height from the bounding box, wheels from a circle fit.

    Take the lowest filled pixel of every column (the bottom contour). Its median is the sill
    line, because the body's underside is most of the car's length. The wheels are the two
    widest runs of columns that reach below that line, and each wheel is the circle fitted to the
    contour points of its run, so a tire the arch hides in part still gives its true center and
    radius. `wheelbase_px` is the distance between the two centers, `wheel_radius_px` the mean
    radius.

    Raises SilhouetteError for an empty mask, for fewer than two wheel bumps, or for a bump that
    is not an arc of a circle.
    """
    import numpy as np

    rows, cols = np.nonzero(mask)
    if rows.size == 0:
        raise SilhouetteError("empty")
    top, bottom_row = int(rows.min()), int(rows.max())
    left, right = int(cols.min()), int(cols.max())
    length_px = float(right - left + 1)
    height_px = float(bottom_row - top + 1)

    window = mask[:, left : right + 1]
    filled = window.any(axis=0)
    # Index of the last True per column; the value for an empty column is masked out below.
    lowest = (mask.shape[0] - 1) - np.argmax(window[::-1, :], axis=0)
    sill = float(np.median(lowest[filled]))
    below = filled & (lowest > sill + _SILL_MARGIN_SHARE * height_px)

    padded = np.concatenate(([0], below.astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(padded))
    starts, stops = edges[0::2], edges[1::2]  # a run is columns start..stop-1
    wide = np.flatnonzero(stops - starts >= _MIN_WHEEL_COLUMNS)
    if wide.size < 2:
        raise SilhouetteError("fewer than two wheel bumps below the sill line")
    widest = wide[np.argsort(-(stops - starts)[wide], kind="stable")[:2]]
    runs = sorted((int(starts[i]), int(stops[i])) for i in widest)

    fits = [
        _fit_circle(
            (np.arange(start, stop) + left).astype(np.float64),
            lowest[start:stop].astype(np.float64) + 0.5,  # the edge under the lowest pixel
            limit=height_px,
        )
        for start, stop in runs
    ]
    (front_x, front_y, front_r), (rear_x, rear_y, rear_r) = fits
    return SideMeasure(
        length_px=length_px,
        height_px=height_px,
        wheelbase_px=float(np.hypot(rear_x - front_x, rear_y - front_y)),
        wheel_radius_px=(front_r + rear_r) / 2,
        front_center=(front_x, front_y),
        rear_center=(rear_x, rear_y),
    )


def _fit_circle(
    xs: NDArray[np.float64], ys: NDArray[np.float64], *, limit: float
) -> tuple[float, float, float]:
    """Algebraic least-squares circle (Kasa): the `(x, y, radius)` that minimizes the squared
    error of `x^2 + y^2 + D x + E y + F = 0` over the points. The points are centered first, so
    pixel coordinates in the thousands don't cost precision.

    Raises SilhouetteError when the points are collinear or the radius is not in `(0, limit]`.
    """
    import numpy as np

    cx, cy = float(xs.mean()), float(ys.mean())
    u, v = xs - cx, ys - cy
    design = np.column_stack([u, v, np.ones_like(u)])
    solution, _, rank, _ = np.linalg.lstsq(design, -(u * u + v * v), rcond=None)
    if rank < 3:
        raise SilhouetteError("a wheel bump is not an arc of a circle")
    center_u, center_v = -float(solution[0]) / 2, -float(solution[1]) / 2
    radius_squared = center_u**2 + center_v**2 - float(solution[2])
    if radius_squared <= 0 or radius_squared > limit**2:
        raise SilhouetteError("a wheel bump is not an arc of a circle")
    return center_u + cx, center_v + cy, float(np.sqrt(radius_squared))


@dataclass(frozen=True)
class ProportionReport:
    """Measured ratios against the real car's. An error is relative to the expected ratio."""

    wheelbase_over_length: float
    height_over_length: float
    expected_wheelbase_over_length: float
    expected_height_over_length: float
    wheelbase_error: float
    height_error: float
    ok: bool


def check_proportions(
    measure: SideMeasure, expected: Dimensions, tol: float = 0.02
) -> ProportionReport:
    """Compare wheelbase/length and height/length with the data's. `ok` when each relative error
    is at most `tol` (spec 9.1a guard 1: 2%). Ratios, because the image scale is unknown."""
    wheelbase = measure.wheelbase_px / measure.length_px
    height = measure.height_px / measure.length_px
    expected_wheelbase = expected.wheelbase_mm / expected.length_mm
    expected_height = expected.height_mm / expected.length_mm
    wheelbase_error = abs(wheelbase - expected_wheelbase) / expected_wheelbase
    height_error = abs(height - expected_height) / expected_height
    return ProportionReport(
        wheelbase_over_length=wheelbase,
        height_over_length=height,
        expected_wheelbase_over_length=expected_wheelbase,
        expected_height_over_length=expected_height,
        wheelbase_error=wheelbase_error,
        height_error=height_error,
        ok=wheelbase_error <= tol and height_error <= tol,
    )
