"""Scoring math: how well a rendered silhouette matches a photo, and what a score means.

`iou` and `align_to_photo` compare two masks. `dimensions_within` compares a mesh's measured size
with the data. `recommend_threshold` turns the scores of accepted and control photos into the one
number the stage accepts a candidate by. Every function is pure, so each is tested on masks and
numbers built in the test. numpy and Pillow are imported inside the functions that use them, so
importing this module (the `score` stage registers when the CLI loads) stays cheap:
`test_importing_the_cli_loads_no_heavy_dependencies` holds the CLI to that.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from m3_pipeline.stages.lib.dims import Dimensions

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray

# A threshold is reported to this resolution, and rounded down to it.
_THRESHOLD_STEP = 0.01
# Added before rounding down, so a midpoint that is 0.90 on paper (0.9000000000000001 or
# 0.8999999999999999 as a float) does not land a step low.
_ROUNDING_SLACK = 1e-9
# `dimensions_within` compares errors with the tolerance, and a value exactly on it passes. The
# slack keeps a float error in the ratio from failing a value that is on the line.
_TOLERANCE_SLACK = 1e-12


def iou(a: NDArray[np.bool_], b: NDArray[np.bool_]) -> float:
    """Intersection over union of two masks of the same shape.

    Two empty masks score 0.0, never 1.0: nothing matched nothing is no evidence of a match, and a
    render that missed the frame entirely must not pass against a photo that has no subject.
    """
    import numpy as np

    if a.shape != b.shape:
        raise ValueError(f"the masks differ in shape: {a.shape} and {b.shape}")
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 0.0
    return int(np.count_nonzero(a & b)) / union


def align_to_photo(rendered: NDArray[np.bool_], photo: NDArray[np.bool_]) -> NDArray[np.bool_]:
    """The render, scaled uniformly until its bounding box is as wide as the photo's, and moved
    until the two boxes share a center, drawn on a canvas of the photo's shape.

    A render is framed on its own projected box, and a photo on whatever the photographer chose,
    so their scale and offset say nothing about the car. Matching the width removes both, and the
    height is left to be compared: that is the proportion the score measures. Either mask being
    empty gives an empty result.

    The canvas is the photo's, so a render that reaches past it is cut off. Do not score the result
    with `iou`: the cut-off pixels would leave the union and reward a render that is too tall.
    `aligned_iou` scores on a canvas that holds both.
    """
    import numpy as np

    aligned = np.zeros(photo.shape, dtype=np.bool_)
    placed = _place(rendered, photo)
    if placed is None:
        return aligned
    scaled, start_row, start_column = placed
    rows, columns = aligned.shape
    row_from = max(0, start_row)
    row_to = min(rows, start_row + scaled.shape[0])
    column_from = max(0, start_column)
    column_to = min(columns, start_column + scaled.shape[1])
    if row_from < row_to and column_from < column_to:
        aligned[row_from:row_to, column_from:column_to] = scaled[
            row_from - start_row : row_to - start_row,
            column_from - start_column : column_to - start_column,
        ]
    return aligned


def aligned_iou(rendered: NDArray[np.bool_], photo: NDArray[np.bool_]) -> float:
    """IoU of the render, aligned as `align_to_photo` aligns it, against the photo, on a canvas
    that holds both masks.

    No foreground pixel of either mask is cut out of the union, so a render that overflows the
    photo's frame is charged for the overflow, and blank padding around the photo, which only
    moves the frame, cannot change the score. Either mask being empty scores 0.0.
    """
    import numpy as np

    placed = _place(rendered, photo)
    if placed is None:
        return 0.0
    scaled, start_row, start_column = placed
    rows, columns = photo.shape
    row_from = max(0, start_row)
    row_to = min(rows, start_row + scaled.shape[0])
    column_from = max(0, start_column)
    column_to = min(columns, start_column + scaled.shape[1])
    intersection = 0
    if row_from < row_to and column_from < column_to:
        intersection = int(
            np.count_nonzero(
                scaled[
                    row_from - start_row : row_to - start_row,
                    column_from - start_column : column_to - start_column,
                ]
                & photo[row_from:row_to, column_from:column_to]
            )
        )
    union = int(np.count_nonzero(scaled)) + int(np.count_nonzero(photo)) - intersection
    return intersection / union


def _place(
    rendered: NDArray[np.bool_], photo: NDArray[np.bool_]
) -> tuple[NDArray[np.bool_], int, int] | None:
    """The render scaled to the photo box's width, and where its top-left pixel falls in the
    photo's pixel coordinates (negative, or past the photo's edge, when it overflows). None when
    either mask is empty."""
    import numpy as np
    from PIL import Image

    rendered_box = _bounding_box(rendered)
    photo_box = _bounding_box(photo)
    if rendered_box is None or photo_box is None:
        return None
    top, bottom, left, right = rendered_box
    photo_top, photo_bottom, photo_left, photo_right = photo_box
    width = right - left + 1
    height = bottom - top + 1
    photo_width = photo_right - photo_left + 1
    scaled_height = max(1, round(height * photo_width / width))
    crop = np.ascontiguousarray(rendered[top : bottom + 1, left : right + 1])
    # Pillow scales a bilinear image by area when it shrinks one, so thresholding at half keeps a
    # shrunk mask's edge where the mean of the covered pixels says it is.
    image = Image.fromarray(crop.astype(np.uint8) * 255)
    scaled = np.asarray(image.resize((photo_width, scaled_height), Image.Resampling.BILINEAR))
    # Box centers match: the scaled box is as wide as the photo's, so it starts at the photo's
    # left edge, and its rows are centered on the photo box's rows.
    start_row = math.floor((photo_top + photo_bottom) / 2 - (scaled_height - 1) / 2 + 0.5)
    return scaled >= 128, start_row, photo_left


def _bounding_box(mask: NDArray[np.bool_]) -> tuple[int, int, int, int] | None:
    """`(top, bottom, left, right)`, inclusive, of the True pixels, or None for an empty mask."""
    import numpy as np

    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    columns = np.flatnonzero(mask.any(axis=0))
    return int(rows[0]), int(rows[-1]), int(columns[0]), int(columns[-1])


@dataclass(frozen=True)
class DimensionReport:
    """Relative errors of a measured size against the data, as absolute fractions (0.01 is 1%).

    An error is never signed, so `report.length_error <= tol` means what it says for a mesh that
    is too short as well as one that is too long. `ok` is every axis within the tolerance.
    """

    length_error: float
    height_error: float
    width_error: float
    ok: bool


def dimensions_within(
    length_m: float,
    top_m: float,
    width_m: float,
    expected: Dimensions,
    tol: float = 0.01,
) -> DimensionReport:
    """Compare a mesh's length, roof height and width with the published ones.

    `top_m` is the roof above the ground line (y = 0), not the mesh's own height: a wheel-less
    body floats above the ground, so its height would read short by the wheels' share.
    """
    length_error = _relative_error(length_m, expected.length_mm / 1000)
    height_error = _relative_error(top_m, expected.height_mm / 1000)
    width_error = _relative_error(width_m, expected.width_mm / 1000)
    ok = all(error <= tol + _TOLERANCE_SLACK for error in (length_error, height_error, width_error))
    return DimensionReport(length_error, height_error, width_error, ok)


def _relative_error(measured: float, expected: float) -> float:
    return abs(measured - expected) / expected


def recommend_threshold(accepted: Sequence[float], controls: Sequence[float]) -> float:
    """The score to accept a candidate at: halfway between the lowest accepted photo's score and
    the highest control's, rounded down to 0.01.

    `accepted` are the scores of photos known to show the car, and `controls` the scores of
    photos that must be rejected. A threshold exists only when every accepted score is above
    every control score, and it must itself lie above the highest control: a gap narrower than
    0.01 can round the midpoint down onto a control, which would then pass. Both cases raise
    `ValueError`, because no number separates the two groups.
    """
    if not accepted or not controls:
        raise ValueError("a threshold needs at least one accepted score and one control score")
    lowest_accepted = min(accepted)
    highest_control = max(controls)
    if lowest_accepted <= highest_control:
        raise ValueError(
            f"the scores overlap: the lowest accepted score {lowest_accepted:.3f} is not above "
            f"the highest control score {highest_control:.3f}"
        )
    midpoint = (lowest_accepted + highest_control) / 2
    threshold = math.floor(midpoint / _THRESHOLD_STEP + _ROUNDING_SLACK) * _THRESHOLD_STEP
    threshold = round(threshold, 2)
    if threshold <= highest_control:
        raise ValueError(
            f"the gap between the lowest accepted score {lowest_accepted:.3f} and the highest "
            f"control score {highest_control:.3f} is too narrow for a threshold at "
            f"{_THRESHOLD_STEP}: {threshold:.2f} would accept that control"
        )
    return threshold
