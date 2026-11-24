import math
import subprocess
import sys

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image, ImageDraw
from silhouette_helpers import BACKGROUND, draw_car

from m3_pipeline.stages.lib.dims import Dimensions
from m3_pipeline.stages.lib.silhouette import (
    ProportionReport,
    SideMeasure,
    SilhouetteError,
    check_proportions,
    mask_from_image,
    measure_side,
)

E46 = Dimensions(
    length_mm=4492,
    width_mm=1780,
    height_mm=1372,
    wheelbase_mm=2731,
    track_front_mm=1508,
    track_rear_mm=1525,
)


def _measure_of(scale: float = 1.0) -> SideMeasure:
    image, _ = draw_car(scale)
    return measure_side(mask_from_image(image))


def _synthetic_measure(
    length: float = 1000.0, *, wheelbase_error: float = 0.0, height_error: float = 0.0
) -> SideMeasure:
    """A SideMeasure with the data's ratios, off by the given relative errors."""
    wheelbase = length * E46.wheelbase_mm / E46.length_mm * (1 + wheelbase_error)
    height = length * E46.height_mm / E46.length_mm * (1 + height_error)
    return SideMeasure(
        length_px=length,
        height_px=height,
        wheelbase_px=wheelbase,
        wheel_radius_px=length * 0.073,
        front_center=(length * 0.2, length * 0.3),
        rear_center=(length * 0.2 + wheelbase, length * 0.3),
    )


def _near(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


# --- mask_from_image ----------------------------------------------------------------------


def test_mask_from_image_finds_the_car_on_a_plain_light_gray_background() -> None:
    image, truth = draw_car()
    mask = mask_from_image(image)
    assert mask.dtype == np.bool_
    assert mask.shape == (image.height, image.width)
    assert not mask[0, 0]
    assert not mask[-1, -1]
    cx, cy = truth.front_center
    assert mask[round(cy), round(cx)]  # inside the front tire
    rows, cols = np.nonzero(mask)
    assert cols.max() - cols.min() + 1 == pytest.approx(truth.length_px, abs=2)
    assert rows.max() - rows.min() + 1 == pytest.approx(truth.height_px, abs=2)


def test_a_speck_away_from_the_car_does_not_enter_the_mask() -> None:
    image, _ = draw_car()
    clean = mask_from_image(image)
    ImageDraw.Draw(image).rectangle((40, 40, 41, 41), fill=(0, 0, 0))  # a 2 px speck
    specked = mask_from_image(image)
    assert not specked[40, 40]
    assert np.array_equal(specked, clean)


def test_non_uniform_background_is_rejected() -> None:
    image, _ = draw_car()
    # A left-to-right gradient behind the car: the left and right corners differ.
    pixels = np.asarray(image).copy()
    is_car = (pixels != np.array(BACKGROUND, dtype=np.uint8)).any(axis=2)
    ramp = np.linspace(0xD9, 0x60, image.width).astype(np.uint8)
    gradient = np.repeat(np.tile(ramp, (image.height, 1))[:, :, None], 3, axis=2)
    gradient[is_car] = pixels[is_car]
    with pytest.raises(SilhouetteError, match="background not uniform"):
        mask_from_image(Image.fromarray(gradient))


def test_a_vignette_with_equal_corners_is_rejected() -> None:
    image, _ = draw_car()
    draw = ImageDraw.Draw(image)
    w, h = image.size
    draw.rectangle((0, 0, w - 1, h - 1), outline=(150, 150, 150), width=12)
    for x, y in ((0, 0), (w - 12, 0), (0, h - 12), (w - 12, h - 12)):
        draw.rectangle((x, y, x + 11, y + 11), fill=BACKGROUND)  # corners untouched
    assert image.getpixel((0, 0)) == image.getpixel((w - 1, h - 1)) == BACKGROUND
    with pytest.raises(SilhouetteError, match="background not uniform"):
        mask_from_image(image)


def test_silhouette_touching_the_border_is_rejected() -> None:
    image, _ = draw_car(margin_px=0)  # the nose, the roof and the tires reach the edges
    with pytest.raises(SilhouetteError, match="touches the image border"):
        mask_from_image(image)


def test_a_car_cut_off_by_one_edge_is_rejected() -> None:
    image = Image.new("RGB", (400, 300), BACKGROUND)
    ImageDraw.Draw(image).rectangle((-30, 100, 200, 200), fill=(30, 30, 40))
    with pytest.raises(SilhouetteError, match="touches the image border"):
        mask_from_image(image)


def test_empty_image_is_rejected() -> None:
    with pytest.raises(SilhouetteError, match="empty"):
        mask_from_image(Image.new("RGB", (400, 300), BACKGROUND))


def test_a_lone_speck_is_an_empty_picture() -> None:
    image = Image.new("RGB", (400, 300), BACKGROUND)
    image.putpixel((200, 150), (0, 0, 0))
    with pytest.raises(SilhouetteError, match="empty"):
        mask_from_image(image)


def test_an_image_too_small_for_a_border_is_empty() -> None:
    with pytest.raises(SilhouetteError, match="empty"):
        mask_from_image(Image.new("RGB", (10, 10), BACKGROUND))


def test_a_tolerance_wide_enough_to_swallow_the_car_is_empty() -> None:
    image, _ = draw_car()
    with pytest.raises(SilhouetteError, match="empty"):
        mask_from_image(image, tolerance=400)


# --- measure_side -------------------------------------------------------------------------


def test_measure_side_recovers_length_height_and_wheelbase_of_a_synthetic_car() -> None:
    image, truth = draw_car()
    measure = measure_side(mask_from_image(image))
    assert measure.length_px == pytest.approx(truth.length_px, rel=0.005)
    assert measure.height_px == pytest.approx(truth.height_px, rel=0.005)
    assert measure.wheelbase_px == pytest.approx(truth.wheelbase_px, rel=0.005)


def test_wheel_centers_come_from_a_circle_fit_not_a_bounding_box() -> None:
    image, truth = draw_car()
    measure = measure_side(mask_from_image(image))
    # The bump of a tire below the sill is 0.84 of its diameter wide, so half the bump's width
    # as a radius would be 16% short. Only a fit gets within 3%.
    assert measure.wheel_radius_px == pytest.approx(truth.tire_radius_px, rel=0.03)
    assert _near(measure.front_center, truth.front_center) <= 0.01 * truth.length_px
    assert _near(measure.rear_center, truth.rear_center) <= 0.01 * truth.length_px


def test_the_left_wheel_is_the_front_one() -> None:
    measure = _measure_of()
    assert measure.front_center[0] < measure.rear_center[0]


def test_measure_side_follows_a_stretched_wheelbase() -> None:
    image, truth = draw_car(wheelbase_scale=1.05)
    measure = measure_side(mask_from_image(image))
    assert measure.wheelbase_px == pytest.approx(truth.wheelbase_px, rel=0.005)


def test_measure_side_rejects_an_empty_mask() -> None:
    with pytest.raises(SilhouetteError, match="empty"):
        measure_side(np.zeros((50, 80), dtype=np.bool_))


def test_measure_side_rejects_a_silhouette_without_wheel_bumps() -> None:
    mask: NDArray[np.bool_] = np.zeros((100, 300), dtype=np.bool_)
    mask[20:80, 10:290] = True  # a plain box: a flat bottom contour
    with pytest.raises(SilhouetteError, match="wheel"):
        measure_side(mask)


def test_measure_side_rejects_a_bump_that_is_not_a_circle_arc() -> None:
    mask: NDArray[np.bool_] = np.zeros((100, 300), dtype=np.bool_)
    mask[20:70, 10:290] = True
    for x0 in (40, 200):
        mask[70:80, x0 : x0 + 40] = True  # flat-bottomed feet, not tires
    with pytest.raises(SilhouetteError, match="not an arc of a circle"):
        measure_side(mask)


# --- check_proportions --------------------------------------------------------------------


def test_check_proportions_passes_at_1_9_percent_wheelbase_error() -> None:
    report = check_proportions(_synthetic_measure(wheelbase_error=0.019), E46)
    assert report.ok
    assert report.wheelbase_error == pytest.approx(0.019)
    assert report.height_error == pytest.approx(0.0, abs=1e-12)


def test_check_proportions_fails_at_2_1_percent_wheelbase_error() -> None:
    report = check_proportions(_synthetic_measure(wheelbase_error=0.021), E46)
    assert not report.ok
    assert report.wheelbase_error == pytest.approx(0.021)


def test_check_proportions_fails_at_2_1_percent_wheelbase_error_the_other_way() -> None:
    report = check_proportions(_synthetic_measure(wheelbase_error=-0.021), E46)
    assert not report.ok
    assert report.wheelbase_error == pytest.approx(0.021)


def test_check_proportions_fails_when_height_is_3_percent_off() -> None:
    report = check_proportions(_synthetic_measure(height_error=0.03), E46)
    assert not report.ok
    assert report.height_error == pytest.approx(0.03)
    assert report.wheelbase_error == pytest.approx(0.0, abs=1e-12)


def test_check_proportions_reports_the_ratios_and_the_data_ratios() -> None:
    report = check_proportions(_synthetic_measure(), E46)
    assert report.expected_wheelbase_over_length == pytest.approx(2731 / 4492)
    assert report.expected_height_over_length == pytest.approx(1372 / 4492)
    assert report.wheelbase_over_length == pytest.approx(2731 / 4492)
    assert report.height_over_length == pytest.approx(1372 / 4492)
    assert report.ok


def test_check_proportions_takes_the_tolerance_as_an_argument() -> None:
    measure = _synthetic_measure(height_error=0.03)
    assert check_proportions(measure, E46, tol=0.05).ok
    assert not check_proportions(measure, E46, tol=0.02).ok


def test_check_is_scale_free() -> None:
    small = check_proportions(_measure_of(0.5), E46)
    large = check_proportions(_measure_of(2.0), E46)
    assert small.ok and large.ok
    # Pixel rounding moves a ratio by about 1% at half scale (the car is 170 px tall there); the
    # errors are small numbers, so they are compared by difference.
    assert small.wheelbase_over_length == pytest.approx(large.wheelbase_over_length, rel=0.01)
    assert small.height_over_length == pytest.approx(large.height_over_length, rel=0.01)
    assert small.wheelbase_error == pytest.approx(large.wheelbase_error, abs=0.01)
    assert small.height_error == pytest.approx(large.height_error, abs=0.01)
    assert small.expected_wheelbase_over_length == large.expected_wheelbase_over_length


def test_the_same_measure_at_two_scales_gives_the_same_report() -> None:
    half = check_proportions(_synthetic_measure(500.0, wheelbase_error=0.01), E46)
    double = check_proportions(_synthetic_measure(2000.0, wheelbase_error=0.01), E46)
    for field in ProportionReport.__dataclass_fields__:
        assert getattr(half, field) == pytest.approx(getattr(double, field), rel=1e-9), field


def test_importing_the_silhouette_module_loads_neither_numpy_nor_pillow() -> None:
    code = (
        "import sys, m3_pipeline.stages.lib.silhouette, m3_pipeline.stages.proportion; "
        "print(','.join(m for m in ('numpy', 'PIL') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""
