import numpy as np
import pytest
from numpy.typing import NDArray

from m3_pipeline.stages.lib.dims import Dimensions
from m3_pipeline.stages.lib.scoring import (
    align_to_photo,
    dimensions_within,
    iou,
    recommend_threshold,
)

# The published E46 coupe: 4492 x 1780 x 1370 mm.
EXPECTED = Dimensions(
    length_mm=4492,
    width_mm=1780,
    height_mm=1370,
    wheelbase_mm=2731,
    track_front_mm=1510,
    track_rear_mm=1526,
)


def rectangle(
    shape: tuple[int, int], rows: tuple[int, int], columns: tuple[int, int]
) -> NDArray[np.bool_]:
    """A mask with the rectangle `rows` x `columns` (inclusive ends) set."""
    mask = np.zeros(shape, dtype=np.bool_)
    mask[rows[0] : rows[1] + 1, columns[0] : columns[1] + 1] = True
    return mask


def bounding_box(mask: NDArray[np.bool_]) -> tuple[int, int, int, int]:
    rows = np.flatnonzero(mask.any(axis=1))
    columns = np.flatnonzero(mask.any(axis=0))
    return int(rows[0]), int(rows[-1]), int(columns[0]), int(columns[-1])


def test_iou_identical_masks_is_one() -> None:
    mask = rectangle((32, 32), (4, 20), (6, 25))
    assert iou(mask, mask.copy()) == 1.0


def test_iou_disjoint_masks_is_zero() -> None:
    a = rectangle((32, 32), (0, 9), (0, 9))
    b = rectangle((32, 32), (20, 29), (20, 29))
    assert iou(a, b) == 0.0


def test_iou_of_two_empty_masks_is_zero_not_one() -> None:
    empty = np.zeros((16, 16), dtype=np.bool_)
    assert iou(empty, empty.copy()) == 0.0


def test_iou_of_overlapping_masks_is_intersection_over_union() -> None:
    a = rectangle((20, 20), (0, 9), (0, 9))  # 100 pixels
    b = rectangle((20, 20), (0, 9), (5, 14))  # 100 pixels, 50 shared
    assert iou(a, b) == pytest.approx(50 / 150)


def test_iou_refuses_masks_of_different_shapes() -> None:
    with pytest.raises(ValueError, match="shape"):
        iou(np.zeros((8, 8), dtype=np.bool_), np.zeros((8, 9), dtype=np.bool_))


def test_align_to_photo_scales_to_the_photo_width_and_matches_the_box_centers() -> None:
    rendered = rectangle((64, 64), (10, 29), (5, 44))  # 40 wide, 20 tall
    photo = rectangle((200, 300), (50, 89), (100, 179))  # 80 wide, 40 tall, same proportion
    aligned = align_to_photo(rendered, photo)
    assert aligned.shape == photo.shape
    assert bounding_box(aligned) == bounding_box(photo)
    assert iou(aligned, photo) == 1.0


def test_align_to_photo_keeps_the_proportion_it_is_scored_on() -> None:
    rendered = rectangle((64, 64), (10, 29), (5, 44))  # 40 x 20: twice as wide as tall
    photo = rectangle((200, 300), (50, 99), (100, 179))  # 80 x 50: not twice as wide as tall
    aligned = align_to_photo(rendered, photo)
    top, bottom, left, right = bounding_box(aligned)
    # Width is matched exactly, height follows the render's own proportion, and the two boxes
    # share a center row.
    assert (left, right) == (100, 179)
    assert bottom - top + 1 == 40
    assert (top + bottom) / 2 == pytest.approx((50 + 99) / 2, abs=0.5)
    assert iou(aligned, photo) == pytest.approx(40 / 50, abs=0.02)


def test_align_to_photo_shrinks_a_render_too() -> None:
    rendered = rectangle((256, 256), (30, 129), (10, 209))  # 200 wide, 100 tall
    photo = rectangle((64, 64), (20, 29), (22, 41))  # 20 wide, 10 tall
    aligned = align_to_photo(rendered, photo)
    assert iou(aligned, photo) == pytest.approx(1.0, abs=0.05)


def test_align_to_photo_with_an_empty_mask_is_empty() -> None:
    photo = rectangle((32, 32), (4, 20), (6, 25))
    empty = np.zeros((32, 32), dtype=np.bool_)
    assert not align_to_photo(empty, photo).any()
    aligned = align_to_photo(photo, empty)
    assert aligned.shape == empty.shape
    assert not aligned.any()


def test_dimensions_within_one_percent() -> None:
    inside = dimensions_within(4.492 * 1.0099, 1.370 * 0.9901, 1.780 * 1.0099, EXPECTED)
    assert inside.ok
    assert inside.length_error == pytest.approx(0.0099)
    assert inside.height_error == pytest.approx(0.0099)
    assert inside.width_error == pytest.approx(0.0099)

    # One axis at a time at 1.01%, high and low: only that axis is named by its error.
    too_long = dimensions_within(4.492 * 1.0101, 1.370, 1.780, EXPECTED)
    assert not too_long.ok
    assert too_long.length_error == pytest.approx(0.0101)
    assert too_long.height_error == pytest.approx(0.0)
    assert too_long.width_error == pytest.approx(0.0)

    too_low = dimensions_within(4.492, 1.370 * 0.9899, 1.780, EXPECTED)
    assert not too_low.ok
    assert too_low.height_error == pytest.approx(0.0101)
    assert too_low.length_error == pytest.approx(0.0)

    too_wide = dimensions_within(4.492, 1.370, 1.780 * 1.0101, EXPECTED)
    assert not too_wide.ok
    assert too_wide.width_error == pytest.approx(0.0101)
    assert too_wide.length_error == pytest.approx(0.0)


def test_dimensions_within_passes_a_value_exactly_on_the_tolerance() -> None:
    report = dimensions_within(4.492 * 1.01, 1.370 * 0.99, 1.780, EXPECTED)
    assert report.ok


def test_dimensions_within_reports_an_error_as_a_size_never_a_sign() -> None:
    short = dimensions_within(4.492 * 0.95, 1.370, 1.780, EXPECTED)
    assert short.length_error == pytest.approx(0.05)
    assert not short.ok


def test_dimensions_within_takes_a_tolerance() -> None:
    assert not dimensions_within(4.492 * 1.03, 1.370, 1.780, EXPECTED).ok
    assert dimensions_within(4.492 * 1.03, 1.370, 1.780, EXPECTED, tol=0.05).ok


def test_recommend_threshold_sits_between_accepted_and_control_scores() -> None:
    assert recommend_threshold([0.93, 0.95], [0.84, 0.88]) == 0.90


def test_recommend_threshold_rounds_down_and_does_not_lose_a_step_to_float_error() -> None:
    # The midpoint is 0.90 on paper; as floats it is not exactly 0.9.
    assert recommend_threshold([0.92], [0.88]) == 0.90
    assert recommend_threshold([0.97], [0.80]) == 0.88  # 0.885 rounds down


def test_recommend_threshold_refuses_overlapping_distributions() -> None:
    with pytest.raises(ValueError, match="overlap"):
        recommend_threshold([0.80, 0.95], [0.85, 0.70])
    with pytest.raises(ValueError, match="overlap"):
        recommend_threshold([0.85], [0.85])


def test_recommend_threshold_refuses_a_gap_that_rounds_onto_a_control() -> None:
    # Midpoint 0.895 rounds down to 0.89, which is the control's own score: it would pass.
    with pytest.raises(ValueError, match="too narrow"):
        recommend_threshold([0.90], [0.89])


def test_recommend_threshold_needs_scores_on_both_sides() -> None:
    with pytest.raises(ValueError, match="at least one"):
        recommend_threshold([], [0.5])
    with pytest.raises(ValueError, match="at least one"):
        recommend_threshold([0.9], [])
