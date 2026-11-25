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
# The underside is the straight line most of the bottom contour lies along (a level sill, or a
# raked one). A column belongs to a wheel bump when its contour lies more than this share of the
# silhouette's height below that line, and never less than 2 px: the contour of a drawn or opened
# mask wanders by a pixel.
_SILL_MARGIN_SHARE = 0.01
_SILL_MARGIN_MIN_PX = 2.0
# The line search tries every pair of this many evenly spaced contour points whose two ends are at
# least a quarter of the car's length apart, and keeps the line with the most points near it.
_UNDERSIDE_POINTS = 160
_UNDERSIDE_BASELINE = 0.25
# A bump has to be at least this share of the car's length wide to be looked at, and at most this
# many of the widest are (a wheel bump is about 12% of an E46's length).
_MIN_RUN_SHARE = 0.02
_MAX_RUNS = 6
# Every bump gets a RANSAC circle: this many random triples of its contour points, from a fixed
# seed so a picture always gives the same answer.
_TRIALS = 300
_REFINED = 5  # how many of the best random circles are refined
_SEED = 0
# A wheel's radius is this share of the silhouette's height: an E46's tire is 24% of its height,
# an SUV's about 20%. Outside 10% to 40% a circle is a bolt head or a belly pan, not a wheel.
_MIN_RADIUS_SHARE = 0.10
_MAX_RADIUS_SHARE = 0.40
# A contour point is on a circle when it is within this share of the radius of it (and never
# closer than 1.5 px, which covers pixel rounding and the opening). It is tight on purpose: a
# floor shadow that merges with a tire's bottom deviates from the arc by about 5% of the radius, and
# a wide band would count it as part of the wheel and fit a bigger, wrong circle.
_BAND_SHARE = 0.03
_BAND_MIN_PX = 1.5
# The gates a circle must pass, each a share of the radius or of the arc:
# - Residual, the RMS distance of the points on the circle from it: at most 1% of the radius.
#   Pixel rounding alone is 0.3 px (0.4% of an 80 px radius) and blur, noise and JPEG add up to
#   0.5% at that size. The wrong circles that shadows shifted under the tires produce measure
#   1.2% to 2.6% (the check against the shadow repros is in the tests). A caller that measures a
#   trusted, shadow-free render may put a floor under the gate in pixels (`min_residual_px`):
#   `_MIN_RESIDUAL_PX`, twice the 0.3 px of rounding. At a radius under 60 px (a 512 px render of
#   a car) 1% would ask for less error than rounding and a 24-sided tire make. It is opt-in
#   because the same floor lets a contact shadow through on a small photo (a 3% long wheelbase
#   reads as 1.3% at 0.4 scale), and photos and synthesized views are where shadows are.
# - Coverage, the share of the arc below the underside that lies on the circle: at least 85%. A
#   clean tire is 100%, and a splitter that runs into the bump takes about 6%. Over 300 floor
#   shadows of every size and offset that passed, the wheelbase was within 0.3% of the truth at
#   85% coverage or more, and off by up to 1.5% between 80% and 85%.
# - Arc, the angle the points on the circle span seen from its center: at least 60 degrees. A tire
#   under a sill 100 to 250 mm above the ground shows 90 to 150; a shorter arc fixes a center
#   too loosely.
# - Radii: the two wheels differ by at most 10% of their mean (staggered fitments are within 3%).
_MAX_RESIDUAL = 0.01
_MIN_RESIDUAL_PX = 0.6
# What a caller passes as `min_residual_px` for a trusted, shadow-free render (Task 14's meshes).
RENDER_MIN_RESIDUAL_PX = _MIN_RESIDUAL_PX
_MIN_COVERAGE = 0.85
_MIN_ARC_DEG = 60.0
_MAX_RADIUS_SPREAD = 0.10


# The usual reason no bump is usable: generators add a contact shadow, and any shadow darker than
# the mask tolerance joins the silhouette, fills the gap under the car or merges with the tires.
_SHADOW_HINT = "a floor or contact shadow may have merged into the silhouette"


class SilhouetteError(ValueError):
    """The picture cannot be measured: no clean background, no car, or no two wheels."""


def _require_connected(mask: NDArray[np.bool_]) -> None:
    """Require one outer silhouette, allowing detached detail wholly enclosed by it.

    Fill only the largest original component's enclosed background for this check. Detached
    detail must lie wholly inside that contour; an exterior halo cannot enclose the car and
    become its outline. Exterior marks are rejected even inside the car's bounding box. The
    original mask still supplies all measurements. Foreground uses 8-connectivity and exterior
    background uses the complementary 4-connectivity, preserving diagonal foreground contact.
    """
    import numpy as np
    from PIL import Image, ImageDraw

    # Most masks are already connected; floodfill is only needed for detached detail.
    anchor = _dominant_component(mask)
    if anchor is None:
        return

    # Padding guarantees an exterior seed even for masks touching an image edge.
    padded = np.pad(anchor, 1).astype(np.uint8) * 255
    exterior = Image.fromarray(padded).copy()
    ImageDraw.floodfill(exterior, (0, 0), 128)
    outline = np.asarray(exterior)[1:-1, 1:-1] != 128
    if np.any(mask & ~outline):
        raise SilhouetteError("disconnected foreground: expected one car silhouette")


def _dominant_component(mask: NDArray[np.bool_]) -> NDArray[np.bool_] | None:
    """Return the largest 8-connected component, or None for an already connected mask."""
    import numpy as np

    parents: list[int] = []

    def root(label: int) -> int:
        while parents[label] != label:
            parents[label] = parents[parents[label]]
            label = parents[label]
        return label

    runs: list[tuple[int, int, int, int]] = []
    previous: list[tuple[int, int, int]] = []
    for y, row in enumerate(mask):
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
        current: list[tuple[int, int, int]] = []
        for start, stop in zip(edges[::2], edges[1::2], strict=True):
            left, right = int(start), int(stop)  # right is exclusive
            neighbors = [root(label) for a, b, label in previous if a <= right and b >= left]
            if neighbors:
                label = neighbors[0]
                for neighbor in neighbors[1:]:
                    parents[root(neighbor)] = root(label)
            else:
                label = len(parents)
                parents.append(label)
            current.append((left, right, label))
            runs.append((y, left, right, label))
        previous = current
    sizes: dict[int, int] = {}
    for _, left, right, label in runs:
        component = root(label)
        sizes[component] = sizes.get(component, 0) + right - left
    if len(sizes) <= 1:
        return None
    largest = max(sizes, key=lambda component: sizes[component])
    anchor = np.zeros_like(mask)
    for y, left, right, label in runs:
        if root(label) == largest:
            anchor[y, left:right] = True
    return anchor


def mask_from_image(img: Image.Image, *, tolerance: int = 24) -> NDArray[np.bool_]:
    """The car's silhouette: True where the picture differs from its plain background.

    The background color is the mean of the four corner patches. The corners must agree within
    `tolerance` (a color distance in RGB). So must the 4-px strip along each side of the border,
    for at least half of its length: a gradient, a vignette or a floor shadow along an edge
    differs over most of it and has no single background color to subtract, while a car that runs
    off an edge covers a stretch of it and is reported as touching the border instead. The mask
    is the pixels farther than `tolerance` from that color, opened to drop specks.

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
class WheelFit:
    """One wheel's circle and the evidence for it, for diagnosis.

    `residual` is the RMS distance of the contour points on the circle from it, as a share of
    `radius_px`. `coverage` is the share of the arc below the underside that lies on the circle,
    `arc_deg` the angle those points span seen from the center, `inliers` how many columns they
    are, and `columns` the first and last column of the bump the circle was fitted to.
    """

    center: tuple[float, float]
    radius_px: float
    residual: float
    coverage: float
    arc_deg: float
    inliers: int
    columns: tuple[int, int]


@dataclass(frozen=True)
class SideMeasure:
    """What a side silhouette says, in pixels. `front_center` and `rear_center` are `(x, y)`.

    `measure_side` decides which wheel is the front one from its `nose_left` argument (the
    synthesized side view has the nose toward the left, `render_ortho_side` toward the right); the
    wheelbase and radius don't care. `wheels` is the evidence, front first; the brief's six fields
    don't depend on it.
    """

    length_px: float
    height_px: float
    wheelbase_px: float
    wheel_radius_px: float
    front_center: tuple[float, float]
    rear_center: tuple[float, float]
    wheels: tuple[WheelFit, ...] = ()


def measure_side(
    mask: NDArray[np.bool_], *, nose_left: bool = True, min_residual_px: float = 0.0
) -> SideMeasure:
    """Length and height from the bounding box, wheels from circle fits.

    Take the lowest filled pixel of every column (the bottom contour). The body's underside is the
    straight line most of that contour lies along (found by a robust line fit, so a rake, a
    splitter or a wide lip doesn't move it). The wheels are the bumps of contour below that line:
    each bump gets a RANSAC circle of wheel size, refined on the points that lie on it, and the
    circle is kept only if it passes the residual, coverage and arc gates (the constants above
    give each threshold and the reason for it). The two best-supported circles must agree in
    radius. `wheelbase_px` is the distance
    between their centers and `wheel_radius_px` their mean radius.

    The nose direction is not detected: `nose_left` (the synthesized side view's convention) makes
    the left-hand wheel the front one, and `nose_left=False` the right-hand one, as in
    `render_ortho_side`'s mask. `front_center`, `rear_center` and `wheels` follow it.

    `min_residual_px` is a floor under the residual gate (1% of the radius), in pixels, and it
    defaults to none. Pass `RENDER_MIN_RESIDUAL_PX` for trusted, shadow-free renders only: a mesh
    render at 512 px has tires about 35 px in radius, where 1% of the radius is less than the
    rounding of the picture. Never pass it for a photo or a synthesized view: the floor loosens
    the very gate that refuses a contact shadow merged into a tire, and a shadowed car then passes
    with a wheelbase error that is not its own.

    Never measures off a contour that isn't a circle: raises SilhouetteError("wheels not found:
    ...") with the reason for every bump it turned down, and also for an empty mask.
    """
    import numpy as np

    rows, cols = np.nonzero(mask)
    if rows.size == 0:
        raise SilhouetteError("empty")
    _require_connected(mask)
    top, bottom_row = int(rows.min()), int(rows.max())
    left, right = int(cols.min()), int(cols.max())
    length_px = float(right - left + 1)
    height_px = float(bottom_row - top + 1)

    window = mask[:, left : right + 1]
    filled = window.any(axis=0)
    # Index of the last True per column; the value for an empty column is dropped below.
    lowest = (mask.shape[0] - 1) - np.argmax(window[::-1, :], axis=0)
    xs = np.arange(left, right + 1, dtype=np.float64)[filled]
    edge = lowest[filled].astype(np.float64) + 0.5  # the edge under the lowest pixel
    margin = max(_SILL_MARGIN_MIN_PX, _SILL_MARGIN_SHARE * height_px)
    slope, intercept = _underside_line(xs, edge, margin)
    depth = edge - (slope * xs + intercept)

    padded = np.concatenate(([0], (depth > margin).astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(padded))
    bumps = [(int(a), int(b)) for a, b in zip(edges[0::2], edges[1::2], strict=True)]  # a..b-1
    bumps = [(a, b) for a, b in bumps if xs[b - 1] - xs[a] + 1 >= _MIN_RUN_SHARE * length_px]
    bumps = sorted(bumps, key=lambda run: run[0] - run[1])[:_MAX_RUNS]  # the widest

    rng = np.random.default_rng(_SEED)
    fits: list[WheelFit] = []
    reasons: list[str] = []
    for a, b in sorted(bumps):
        outcome = _fit_wheel(
            xs, edge, (a, b), (slope, intercept), height_px, margin, min_residual_px, rng
        )
        if isinstance(outcome, WheelFit):
            fits.append(outcome)
        else:
            reasons.append(outcome)
    if len(fits) < 2:
        found = f"{len(fits)} usable of {len(bumps)} bump(s) below the underside"
        hint = [_SHADOW_HINT] if not fits else []
        raise SilhouetteError("wheels not found: " + "; ".join([found, *reasons, *hint]))

    best = sorted(fits, key=lambda fit: -fit.inliers)[:2]
    left, right = sorted(best, key=lambda fit: fit.center[0])
    front, rear = (left, right) if nose_left else (right, left)
    mean_radius = (front.radius_px + rear.radius_px) / 2
    if abs(front.radius_px - rear.radius_px) > _MAX_RADIUS_SPREAD * mean_radius:
        raise SilhouetteError(
            f"wheels not found: the two best circles have radii {front.radius_px:.1f} and "
            f"{rear.radius_px:.1f} px, more than {_MAX_RADIUS_SPREAD:.0%} apart"
        )
    return SideMeasure(
        length_px=length_px,
        height_px=height_px,
        wheelbase_px=float(
            np.hypot(rear.center[0] - front.center[0], rear.center[1] - front.center[1])
        ),
        wheel_radius_px=mean_radius,
        front_center=front.center,
        rear_center=rear.center,
        wheels=(front, rear),
    )


def _underside_line(
    xs: NDArray[np.float64], ys: NDArray[np.float64], tol: float
) -> tuple[float, float]:
    """The `(slope, intercept)` of the straight line that most contour points lie within `tol` of.

    A wheel bump, a splitter or a bumper corner is a minority of the columns, so it can't pull
    this line the way it pulls a median or a mean. Every pair of a subsample of the points, far
    enough apart to give a steady slope, is a candidate; the best is refined on its inliers.
    """
    import numpy as np

    if xs.size < 8:
        raise SilhouetteError("wheels not found: the silhouette is too narrow to have an underside")
    pick = np.linspace(0, xs.size - 1, min(xs.size, _UNDERSIDE_POINTS)).astype(np.intp)
    sx, sy = xs[pick], ys[pick]
    first, second = np.triu_indices(sx.size, k=1)
    span = sx[second] - sx[first]
    far = span >= _UNDERSIDE_BASELINE * (xs[-1] - xs[0])
    if not far.any():
        raise SilhouetteError("wheels not found: the bottom contour has no underside to fit")
    first, second, span = first[far], second[far], span[far]
    slopes = (sy[second] - sy[first]) / span
    heights = sy[first] - slopes * sx[first]
    gap = np.abs(sy[None, :] - (slopes[:, None] * sx[None, :] + heights[:, None]))
    best = int(np.argmax((gap <= tol).sum(axis=1)))
    slope, intercept = float(slopes[best]), float(heights[best])
    for _ in range(3):
        near = np.abs(ys - (slope * xs + intercept)) <= tol
        if int(near.sum()) < 2:
            break
        fit = np.polyfit(xs[near], ys[near], 1)
        slope, intercept = float(fit[0]), float(fit[1])
    return slope, intercept


def _fit_wheel(
    xs: NDArray[np.float64],
    edge: NDArray[np.float64],
    bump: tuple[int, int],
    line: tuple[float, float],
    height_px: float,
    margin: float,
    min_residual_px: float,
    rng: np.random.Generator,
) -> WheelFit | str:
    """The wheel circle of one bump (columns `bump[0]..bump[1]-1` of `xs`), or the reason it is
    not one. Judged against the whole contour, not only the bump's: the arc is where the circle
    dips below the underside, and the contour there has to follow it."""
    import numpy as np

    a, b = bump
    first, last = int(xs[a]), int(xs[b - 1])
    label = f"bump {first}-{last} ({last - first + 1} columns wide)"
    circle = _ransac_circle(
        xs[a:b], edge[a:b], _MIN_RADIUS_SHARE * height_px, _MAX_RADIUS_SHARE * height_px, rng
    )
    if circle is None:
        return (
            f"{label}: no circle of wheel radius ({_MIN_RADIUS_SHARE * height_px:.0f} to "
            f"{_MAX_RADIUS_SHARE * height_px:.0f} px) fits its contour"
        )
    cx, cy, radius = circle

    slope, intercept = line
    offset = xs - cx
    arc = cy + np.sqrt(np.maximum(radius * radius - offset * offset, 0.0))
    zone = (np.abs(offset) < radius) & (arc - (slope * xs + intercept) > margin)
    if int(zone.sum()) < 3:
        return f"{label}: the circle barely leaves the underside"
    band = max(_BAND_MIN_PX, _BAND_SHARE * radius)
    error = edge - arc
    on = zone & (np.abs(error) <= band)
    if not on.any():
        return f"{label}: the contour is nowhere on the circle (coverage 0%)"
    coverage = float(on.sum()) / float(zone.sum())
    rms_px = float(np.sqrt(np.mean(error[on] ** 2)))
    residual = rms_px / radius
    residual_limit_px = max(_MAX_RESIDUAL * radius, min_residual_px)
    angles = np.degrees(np.arctan2(xs[on] - cx, edge[on] - cy))  # 0 at the bottom of the circle
    arc_deg = float(angles.max() - angles.min())

    failed: list[str] = []
    if rms_px > residual_limit_px:
        failed.append(
            f"residual {residual:.1%} of the radius ({rms_px:.2f} px), over "
            f"{residual_limit_px:.2f} px"
        )
    if coverage < _MIN_COVERAGE:
        failed.append(f"coverage {coverage:.0%} of the arc, under {_MIN_COVERAGE:.0%}")
    if arc_deg < _MIN_ARC_DEG:
        failed.append(f"arc of {arc_deg:.0f} degrees, under {_MIN_ARC_DEG:.0f}")
    if failed:
        return f"{label}: circle r={radius:.1f} px rejected: " + ", ".join(failed)
    return WheelFit(
        center=(cx, cy),
        radius_px=radius,
        residual=residual,
        coverage=coverage,
        arc_deg=arc_deg,
        inliers=int(on.sum()),
        columns=(first, last),
    )


def _ransac_circle(
    xs: NDArray[np.float64],
    ys: NDArray[np.float64],
    min_radius: float,
    max_radius: float,
    rng: np.random.Generator,
) -> tuple[float, float, float] | None:
    """The circle of a wheel-sized radius that most of the contour points lie on, as `(x, y,
    radius)`, or None. Candidates are the circles through random triples of points whose center
    is above them (image y grows downward: a wheel's contour is the arc under its center). The few
    with the most points within the band are each refined by a least-squares fit on their points,
    repeated until the point set stops changing."""
    import numpy as np

    count = xs.size
    if count < 8:
        return None
    ox, oy = float(xs.mean()), float(ys.mean())  # work around the mean, for precision
    u, v = xs - ox, ys - oy
    picks = rng.integers(0, count, size=(_TRIALS, 3))
    ax, ay, bx, by, cx, cy = (
        u[picks[:, 0]],
        v[picks[:, 0]],
        u[picks[:, 1]],
        v[picks[:, 1]],
        u[picks[:, 2]],
        v[picks[:, 2]],
    )
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    with np.errstate(divide="ignore", invalid="ignore"):
        ux = (
            (ax**2 + ay**2) * (by - cy) + (bx**2 + by**2) * (cy - ay) + (cx**2 + cy**2) * (ay - by)
        ) / d
        uy = (
            (ax**2 + ay**2) * (cx - bx) + (bx**2 + by**2) * (ax - cx) + (cx**2 + cy**2) * (bx - ax)
        ) / d
        radius = np.hypot(ax - ux, ay - uy)
    valid = (
        (np.abs(d) > 1e-9)
        & (radius >= min_radius)
        & (radius <= max_radius)
        & (uy < np.minimum(np.minimum(ay, by), cy))
    )
    if not valid.any():
        return None
    ux, uy, radius = ux[valid], uy[valid], radius[valid]
    distance = np.hypot(u[None, :] - ux[:, None], v[None, :] - uy[:, None])
    band = np.maximum(_BAND_MIN_PX, _BAND_SHARE * radius)[:, None]
    members = (np.abs(distance - radius[:, None]) <= band) & (v[None, :] > uy[:, None])
    # The hypotheses with the most points are each refined, and the one that keeps the most points
    # after refinement wins: the very best raw hypothesis may be a circle that the flat part of the
    # contour (a splitter, a shadow) pulled out of wheel size once it is fitted to its points.
    best: tuple[float, float, float] | None = None
    best_count = 0
    for index in np.argsort(-members.sum(axis=1), kind="stable")[:_REFINED]:
        if int(members[index].sum()) < 3:
            break
        refined = _refine(u, v, members[index], min_radius, max_radius)
        if refined is not None and refined[1] > best_count:
            best, best_count = refined
    if best is None:
        return None
    return best[0] + ox, best[1] + oy, best[2]


def _refine(
    u: NDArray[np.float64],
    v: NDArray[np.float64],
    chosen: NDArray[np.bool_],
    min_radius: float,
    max_radius: float,
) -> tuple[tuple[float, float, float], int] | None:
    """Least-squares circle on the points in `chosen`, then on the points within the band of that
    circle, until the set stops changing. Returns the circle and its point count, or None when a
    fit is collinear or leaves the radius range."""
    import numpy as np

    circle: tuple[float, float, float] | None = None
    for _ in range(5):
        circle = _kasa(u[chosen], v[chosen])
        if circle is None or not min_radius <= circle[2] <= max_radius:
            return None
        gap = np.abs(np.hypot(u - circle[0], v - circle[1]) - circle[2])
        again = (gap <= max(_BAND_MIN_PX, _BAND_SHARE * circle[2])) & (v > circle[1])
        if np.array_equal(again, chosen) or int(again.sum()) < 3:
            break
        chosen = again
    if circle is None:
        return None
    return circle, int(chosen.sum())


def _kasa(u: NDArray[np.float64], v: NDArray[np.float64]) -> tuple[float, float, float] | None:
    """Algebraic least-squares circle: the `(x, y, radius)` that minimizes the squared error of
    `x^2 + y^2 + D x + E y + F = 0` over the points, or None for collinear points."""
    import numpy as np

    design = np.column_stack([u, v, np.ones_like(u)])
    solution, _, rank, _ = np.linalg.lstsq(design, -(u * u + v * v), rcond=None)
    if rank < 3:
        return None
    center_u, center_v = -float(solution[0]) / 2, -float(solution[1]) / 2
    radius_squared = center_u**2 + center_v**2 - float(solution[2])
    if radius_squared <= 0:
        return None
    return center_u, center_v, float(np.sqrt(radius_squared))


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
