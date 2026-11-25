import io
import math
from collections.abc import Callable

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFilter
from silhouette_helpers import (
    BACKGROUND,
    add_contact_shadows,
    draw_car,
    render_proxy_car,
)

from m3_pipeline.stages.lib.dims import Dimensions
from m3_pipeline.stages.lib.silhouette import (
    RENDER_MIN_RESIDUAL_PX,
    ProportionReport,
    SideMeasure,
    SilhouetteError,
    WheelFit,
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


def test_disconnected_mark_cannot_turn_incorrect_height_into_a_pass() -> None:
    image, _ = draw_car(height_scale=0.94)
    clean = check_proportions(measure_side(mask_from_image(image)), E46)
    assert not clean.ok
    ImageDraw.Draw(image).rectangle((600, 100, 604, 104), fill=(0, 0, 0))
    with pytest.raises(SilhouetteError, match="disconnected foreground"):
        measure_side(mask_from_image(image))


def test_detached_enclosing_halo_cannot_turn_incorrect_height_into_a_pass() -> None:
    image, _ = draw_car(height_scale=0.94)
    clean = mask_from_image(image)
    assert not check_proportions(measure_side(clean), E46).ok
    silhouette = Image.fromarray(clean.astype(np.uint8) * 255)
    outer = np.asarray(silhouette.filter(ImageFilter.MaxFilter(21))) != 0
    inner = np.asarray(silhouette.filter(ImageFilter.MaxFilter(11))) != 0
    halo = outer & ~inner  # 10-pixel dilation minus 5-pixel dilation, detached from car
    pixels = np.asarray(image).copy()
    pixels[halo] = 0
    marked = mask_from_image(Image.fromarray(pixels))
    # This enclosing mark previously enlarged the bounds enough to pass both ratios.
    rows, cols = np.nonzero(marked)
    assert cols.max() - cols.min() + 1 == 1144
    assert rows.max() - rows.min() + 1 == 344
    with pytest.raises(SilhouetteError, match="disconnected foreground"):
        measure_side(marked)


@pytest.mark.parametrize("islands", [False, True])
def test_enclosed_background_and_foreground_detail_preserve_measurements(islands: bool) -> None:
    image, _ = draw_car()
    mask = mask_from_image(image)
    clean = measure_side(mask)
    # A window-like hole wholly inside the body, optionally with three detached details.
    assert mask[220:281, 600:721].all()
    mask[220:281, 600:721] = False
    if islands:
        for x in (610, 650, 690):
            mask[240:251, x : x + 11] = True
    original = mask.copy()
    assert measure_side(mask) == clean
    assert np.array_equal(mask, original)


@pytest.mark.parametrize("size", [1, 5])
def test_exterior_mark_inside_bounding_box_is_rejected(size: int) -> None:
    image, _ = draw_car()
    mask = mask_from_image(image)
    rows, cols = np.nonzero(mask)
    y, x = 150, 150  # above the hood, below the roof, inside the car's bounding box
    assert rows.min() < y < y + size < rows.max()
    assert cols.min() < x < x + size < cols.max()
    assert not mask[y - 1 : y + size + 1, x - 1 : x + size + 1].any()
    mask[y : y + size, x : x + size] = True
    with pytest.raises(SilhouetteError, match="disconnected foreground"):
        measure_side(mask)


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


def _cut_by_edge(rect: tuple[int, int, int, int]) -> Image.Image:
    image = Image.new("RGB", (400, 300), BACKGROUND)
    ImageDraw.Draw(image).rectangle(rect, fill=(30, 30, 40))
    return image


@pytest.mark.parametrize(
    "rect",
    [
        (-30, 100, 200, 200),  # runs off the left edge
        (200, 100, 429, 200),  # the right edge
        (120, -30, 280, 100),  # the top edge
        (120, 200, 280, 329),  # the bottom edge
    ],
    ids=["left", "right", "top", "bottom"],
)
def test_a_car_cut_off_by_any_one_edge_is_rejected(rect: tuple[int, int, int, int]) -> None:
    with pytest.raises(SilhouetteError, match="touches the image border"):
        mask_from_image(_cut_by_edge(rect))


def test_an_edge_cut_over_45_percent_of_its_length_is_a_crop() -> None:
    # 136 of the 300 rows: the strip differs over 45% of the edge, so it is a car running off it.
    with pytest.raises(SilhouetteError, match="touches the image border"):
        mask_from_image(_cut_by_edge((-30, 80, 200, 215)))


def test_an_edge_cut_over_55_percent_of_its_length_is_not_a_background() -> None:
    # 166 of the 300 rows: most of the edge differs, so there is no background along it.
    with pytest.raises(SilhouetteError, match="background not uniform"):
        mask_from_image(_cut_by_edge((-30, 60, 200, 225)))


def test_corners_that_differ_by_more_than_the_tolerance_are_not_one_background() -> None:
    # Two tones, 16 apart per channel (a distance of 27.7 against the tolerance of 24). Each is
    # within the tolerance of their mean, so only the corner comparison can reject this.
    image = Image.new("RGB", (400, 300), (217, 217, 217))
    ImageDraw.Draw(image).rectangle((200, 0, 399, 299), fill=(201, 201, 201))
    ImageDraw.Draw(image).rectangle((150, 100, 250, 200), fill=(30, 30, 40))
    with pytest.raises(SilhouetteError, match="background not uniform"):
        mask_from_image(image)


def test_corners_within_the_tolerance_are_one_background() -> None:
    image = Image.new("RGB", (400, 300), (217, 217, 217))
    ImageDraw.Draw(image).rectangle((200, 0, 399, 299), fill=(207, 207, 207))  # 17.3 apart
    ImageDraw.Draw(image).rectangle((150, 100, 250, 200), fill=(30, 30, 40))
    assert mask_from_image(image)[150, 200]


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


def test_nose_left_is_the_default_and_makes_the_left_wheel_the_front_one() -> None:
    image, truth = draw_car()
    mask = mask_from_image(image)
    default, explicit = measure_side(mask), measure_side(mask, nose_left=True)
    assert default == explicit
    assert _near(default.front_center, truth.front_center) <= 0.01 * truth.length_px
    assert default.wheels[0].center == default.front_center  # `wheels` is front first


def test_with_the_nose_to_the_right_the_right_wheel_is_the_front_one() -> None:
    image, truth = draw_car()
    mask = mask_from_image(image)
    mirrored = np.ascontiguousarray(mask[:, ::-1])  # the same car, facing right
    measure = measure_side(mirrored, nose_left=False)
    last_column = mask.shape[1] - 1
    expected_front = (last_column - truth.front_center[0], truth.front_center[1])
    expected_rear = (last_column - truth.rear_center[0], truth.rear_center[1])
    assert _near(measure.front_center, expected_front) <= 0.01 * truth.length_px
    assert _near(measure.rear_center, expected_rear) <= 0.01 * truth.length_px
    assert measure.front_center[0] > measure.rear_center[0]
    assert measure.wheels[0].center == measure.front_center  # still front first
    assert measure.wheels[1].center == measure.rear_center
    # The measure is the mirror image of the left-facing one, wheelbase and radius included.
    facing_left = measure_side(mask)
    assert measure.wheelbase_px == pytest.approx(facing_left.wheelbase_px)
    assert measure.wheel_radius_px == pytest.approx(facing_left.wheel_radius_px)


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
    with pytest.raises(SilhouetteError, match="wheels not found") as refused:
        measure_side(mask)
    assert "0 usable of 0 bump(s)" in str(refused.value)
    assert "a floor or contact shadow may have merged into the silhouette" in str(refused.value)


def test_measure_side_rejects_a_bump_that_is_not_a_circle_arc() -> None:
    mask: NDArray[np.bool_] = np.zeros((100, 300), dtype=np.bool_)
    mask[20:70, 10:290] = True
    for x0 in (40, 200):
        mask[70:80, x0 : x0 + 40] = True  # flat-bottomed feet, not tires
    with pytest.raises(SilhouetteError, match="wheels not found.*radius"):
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


# --- wheels: the underside, the splitter, the shadow and the gates ------------------------


def _assert_the_true_wheels(
    measure: SideMeasure, truth_wheelbase: float, truth_radius: float
) -> None:
    assert measure.wheelbase_px == pytest.approx(truth_wheelbase, rel=0.01)
    assert measure.wheel_radius_px == pytest.approx(truth_radius, rel=0.03)


@pytest.mark.parametrize(
    ("underside_mm", "splitter_mm"),
    [
        ((120.0, 200.0), None),  # a raked underside, 80 mm over the length
        ((100.0, 250.0), None),  # a steeper rake
        ((150.0, 150.0), (700.0, 60.0)),  # a splitter wider than a tire bump, running into one
    ],
    ids=["rake-120-200", "rake-100-250", "splitter-700x60"],
)
def test_the_wheelbase_survives_a_raked_underside_and_a_wide_front_splitter(
    underside_mm: tuple[float, float], splitter_mm: tuple[float, float] | None
) -> None:
    image, truth = draw_car(underside_mm=underside_mm, splitter_mm=splitter_mm)
    measure = measure_side(mask_from_image(image))
    report = check_proportions(measure, E46)
    assert report.ok
    assert report.wheelbase_error < 0.01
    _assert_the_true_wheels(measure, truth.wheelbase_px, truth.tire_radius_px)
    assert _near(measure.front_center, truth.front_center) <= 0.01 * truth.length_px
    assert _near(measure.rear_center, truth.rear_center) <= 0.01 * truth.length_px


@pytest.mark.parametrize("underside_mm", [(120.0, 200.0), (100.0, 250.0)])
def test_on_a_raked_car_a_wheels_bump_is_the_tires_and_not_the_underside(
    underside_mm: tuple[float, float],
) -> None:
    # A tire bump is about 12% of the length. Measured from a level line through the car instead
    # of the raked underside, the lower end of the underside would join the bump and widen it.
    image, truth = draw_car(underside_mm=underside_mm)
    for wheel in measure_side(mask_from_image(image)).wheels:
        assert wheel.columns[1] - wheel.columns[0] < 0.2 * truth.length_px


@pytest.mark.parametrize("underside_m", [(0.15, 0.15), (0.12, 0.20)], ids=["flat", "raked"])
def test_task_9_wheel_proxies_on_a_512_px_side_render_are_measured_with_the_render_floor(
    underside_m: tuple[float, float],
) -> None:
    """`render_ortho_side`'s default canvas: the 24-sided tire proxies are about 35 px in radius,
    where 1% of the radius is less than the rounding of the picture. A caller that measures a
    trusted, shadow-free render passes the pixel floor. The render has the nose to the right."""
    render = render_proxy_car(512, underside_m)
    measure = measure_side(render.mask, nose_left=False, min_residual_px=RENDER_MIN_RESIDUAL_PX)
    report = check_proportions(measure, E46)
    assert report.ok
    assert report.wheelbase_error < 0.01
    assert measure.front_center[0] == pytest.approx(
        render.front_column, abs=0.01 * measure.length_px
    )
    assert measure.rear_center[0] == pytest.approx(render.rear_column, abs=0.01 * measure.length_px)
    assert measure.wheel_radius_px == pytest.approx(render.tire_radius_px, rel=0.08)
    assert 30 < measure.wheel_radius_px < 40  # the size at which a bare 1% gate refuses it
    assert measure.wheelbase_px / render.px_per_m == pytest.approx(2.731, rel=0.01)


@pytest.mark.parametrize("underside_m", [(0.15, 0.15), (0.12, 0.20)], ids=["flat", "raked"])
def test_task_9_wheel_proxies_on_a_512_px_side_render_are_refused_by_the_default_gate(
    underside_m: tuple[float, float],
) -> None:
    # The default gate has no pixel floor: 1% of a 35 px radius is under the rim error of a
    # 24-sided tire plus rounding, so the tires are refused, for their residual.
    render = render_proxy_car(512, underside_m)
    with pytest.raises(SilhouetteError, match="wheels not found.*residual"):
        measure_side(render.mask, nose_left=False)


def test_the_pixel_floor_is_off_unless_asked_for() -> None:
    # The wavy small wheel that the floor lets through (0.54 px, 1.3% of its radius) is refused
    # by default.
    with pytest.raises(SilhouetteError, match="wheels not found.*residual"):
        measure_side(_two_wobbly_wheels(40, 0.01))
    measure = measure_side(_two_wobbly_wheels(40, 0.01), min_residual_px=RENDER_MIN_RESIDUAL_PX)
    assert measure.wheelbase_px == pytest.approx(500, rel=0.01)


@pytest.mark.parametrize("scale", [1.0, 2.0])
def test_a_blurred_noisy_jpeg_car_is_still_measured(scale: float) -> None:
    image, truth = draw_car(scale, underside_mm=(120.0, 200.0))
    pixels = np.asarray(image.filter(ImageFilter.GaussianBlur(1.2)), dtype=np.float64)
    noise = np.random.default_rng(1).normal(0, 4, pixels.shape)
    noisy = Image.fromarray(np.clip(pixels + noise, 0, 255).astype(np.uint8))
    jpeg = io.BytesIO()
    noisy.save(jpeg, "JPEG", quality=75)
    measure = measure_side(mask_from_image(Image.open(io.BytesIO(jpeg.getvalue()))))
    _assert_the_true_wheels(measure, truth.wheelbase_px, truth.tire_radius_px)
    assert check_proportions(measure, E46).ok


def test_a_narrow_splitter_changes_nothing() -> None:
    image, truth = draw_car(splitter_mm=(400.0, 60.0))
    measure = measure_side(mask_from_image(image))
    _assert_the_true_wheels(measure, truth.wheelbase_px, truth.tire_radius_px)


@pytest.mark.parametrize(
    ("size", "inward_px", "lift_px"),
    [
        ((120, 14), 20, 0),  # Codex's reproduction
        ((120, 14), 20, 4),
        ((80, 10), 20, 0),  # each of these fooled a looser circle gate
        ((100, 12), 20, 0),
        ((60, 8), 30, 0),
    ],
)
def test_contact_shadows_never_turn_a_wrong_wheelbase_into_an_ok(
    size: tuple[int, int], inward_px: int, lift_px: int
) -> None:
    """A 6% long wheelbase, and gray shadows under the tires, shifted inward. The shadows hide the
    bottom of each tire, and a fit that trusts them puts the wheels 6% closer than they are. A
    measurement here is right, or there is none."""
    image, truth = draw_car(wheelbase_scale=1.06)
    add_contact_shadows(image, truth, size=size, inward_px=inward_px, lift_px=lift_px)
    try:
        measure = measure_side(mask_from_image(image))
    except SilhouetteError as error:
        assert "wheels not found" in str(error)
        return
    report = check_proportions(measure, E46)
    assert not report.ok
    assert report.wheelbase_error > 0.04
    assert measure.wheelbase_px == pytest.approx(truth.wheelbase_px, rel=0.02)


# A fixed slice of a wide sweep of shadow placements (size, inward shift, lift), each on a car with
# a wheelbase 6% and 3% too long and too short. Some are refused, some measured.
_SHADOW_SLICE = [
    ((40, 20), 30, 3),  # small and tall, shifted well inward: it once passed a loose gate
    ((100, 20), 10, 6),
    ((120, 14), 20, 0),  # Codex's reproduction
    ((30, 6), 0, 0),  # small, under the middle of the tire
    ((60, 8), 10, 0),
    ((50, 10), -20, 2),  # shifted outward
]


def test_a_fixed_slice_of_shadow_placements_never_passes_a_wrong_wheelbase() -> None:
    refused = measured = 0
    for size, inward_px, lift_px in _SHADOW_SLICE:
        for scale in (1.06, 0.94, 1.03, 0.97):
            image, truth = draw_car(wheelbase_scale=scale)
            add_contact_shadows(image, truth, size=size, inward_px=inward_px, lift_px=lift_px)
            case = f"shadow {size} inward {inward_px} lift {lift_px}, wheelbase x{scale}"
            try:
                measure = measure_side(mask_from_image(image))
            except SilhouetteError as error:
                assert "wheels not found" in str(error), case
                refused += 1
                continue
            measured += 1
            # Every one of these cars is 3% or more off the data, so none may be ok.
            assert not check_proportions(measure, E46).ok, case
            deviation = abs(measure.wheelbase_px / truth.wheelbase_px - 1)
            assert deviation < 0.01, f"{case}: measured {deviation:.2%} off the truth"
    assert refused + measured == 24
    assert refused >= 8 and measured >= 8  # the slice keeps both outcomes


def test_a_3_percent_long_wheelbase_with_a_small_shadow_is_never_ok_at_0_4_scale() -> None:
    """Codex's case: the floor on the residual gate once let this picture through with a wheelbase
    error of 1.27%, against the true 3%. The default gate has no floor."""
    image, truth = draw_car(0.4, wheelbase_scale=1.03)
    add_contact_shadows(image, truth, size=(30, 10), inward_px=10, lift_px=2)
    try:
        measure = measure_side(mask_from_image(image))
    except SilhouetteError as error:
        assert "wheels not found" in str(error)
        return
    assert not check_proportions(measure, E46).ok


# Shadow placements at 0.4 and 0.5 scale, where the pictures are 529 and 661 px wide and a tire is
# 33 and 41 px in radius. Sizes are in pixels at 0.4 scale, and grow with the scale.
_SMALL_SHADOW_SLICE = [
    ((30, 10), 10, 2),  # Codex's case
    ((40, 12), 6, 0),
    ((24, 8), 0, 0),  # small, under the middle of the tire
    ((20, 6), 6, 2),
]


def test_a_slice_of_small_pictures_with_shadows_never_passes_a_wrong_wheelbase() -> None:
    refused = measured = 0
    for scale in (0.4, 0.5):
        grow = scale / 0.4
        for size, inward_px, lift_px in _SMALL_SHADOW_SLICE:
            for wheelbase_scale in (1.06, 0.94, 1.03, 0.97):
                image, truth = draw_car(scale, wheelbase_scale=wheelbase_scale)
                add_contact_shadows(
                    image,
                    truth,
                    size=(round(size[0] * grow), round(size[1] * grow)),
                    inward_px=round(inward_px * grow),
                    lift_px=round(lift_px * grow),
                )
                case = (
                    f"x{scale} shadow {size} inward {inward_px} lift {lift_px}, "
                    f"wheelbase x{wheelbase_scale}"
                )
                try:
                    measure = measure_side(mask_from_image(image))
                except SilhouetteError as error:
                    assert "wheels not found" in str(error), case
                    refused += 1
                    continue
                measured += 1
                assert not check_proportions(measure, E46).ok, case  # all are 3% or more off
                deviation = abs(measure.wheelbase_px / truth.wheelbase_px - 1)
                assert deviation < 0.01, f"{case}: measured {deviation:.2%} off the truth"
    assert refused + measured == 32
    assert refused >= 12 and measured >= 12  # the slice keeps both outcomes


def test_a_shadow_that_fills_the_gap_under_the_car_names_the_likely_cause() -> None:
    image, truth = draw_car()
    ground = truth.front_center[1] + truth.tire_radius_px
    left = truth.front_center[0] - (truth.length_px - truth.wheelbase_px) / 2
    right = left + truth.length_px
    ImageDraw.Draw(image).rectangle((left, ground - 40, right, ground), fill=(128, 128, 128))
    with pytest.raises(SilhouetteError, match="wheels not found") as refused:
        measure_side(mask_from_image(image))
    assert "0 usable of 0 bump(s)" in str(refused.value)
    assert "a floor or contact shadow may have merged into the silhouette" in str(refused.value)


def test_a_shadow_under_the_whole_tire_is_not_measured() -> None:
    image, truth = draw_car()
    add_contact_shadows(image, truth, inward_px=0)  # 120 px of the 138 px under the sill
    with pytest.raises(SilhouetteError, match="wheels not found"):
        measure_side(mask_from_image(image))


def test_a_small_shadow_under_each_tire_is_tolerated() -> None:
    image, truth = draw_car()
    add_contact_shadows(image, truth, size=(30, 6), inward_px=0)
    measure = measure_side(mask_from_image(image))
    _assert_the_true_wheels(measure, truth.wheelbase_px, truth.tire_radius_px)
    assert _near(measure.front_center, truth.front_center) <= 0.01 * truth.length_px


def test_measure_side_reports_each_wheel_for_diagnosis() -> None:
    image, truth = draw_car()
    measure = measure_side(mask_from_image(image))
    front, rear = measure.wheels
    assert isinstance(front, WheelFit)
    assert front.center == measure.front_center
    assert rear.center == measure.rear_center
    for wheel in (front, rear):
        assert wheel.radius_px == pytest.approx(truth.tire_radius_px, rel=0.03)
        assert wheel.residual < 0.02
        assert wheel.coverage >= 0.8
        assert wheel.arc_deg >= 60
        first, last = wheel.columns
        assert 0 < last - first < 0.2 * truth.length_px
    assert front.columns[1] < rear.columns[0]


# Direct masks for the gates, so each gate can be shown to fire on its own. A 1000 x 400 canvas,
# a body from x=50 to x=950 and from y=150 to y=290, and discs for wheels standing on y=330.
_GROUND = 330


def _wheeled_mask(
    wheels: list[tuple[int, int]], extra: Callable[[ImageDraw.ImageDraw], None] | None = None
) -> NDArray[np.bool_]:
    image = Image.new("L", (1000, 400), 0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 150, 950, 290), fill=255)
    for cx, radius in wheels:
        draw.ellipse((cx - radius, _GROUND - 2 * radius, cx + radius, _GROUND), fill=255)
    if extra is not None:
        extra(draw)
    return np.asarray(image) > 0


def test_a_box_with_two_round_wheels_is_measured() -> None:
    measure = measure_side(_wheeled_mask([(250, 60), (750, 60)]))
    assert measure.wheelbase_px == pytest.approx(500, rel=0.005)
    assert measure.wheel_radius_px == pytest.approx(60, rel=0.03)
    assert measure.front_center[0] == pytest.approx(250, abs=2)


def _wobbly_wheel(cx: int, radius: int, amplitude: float) -> Callable[[ImageDraw.ImageDraw], None]:
    """A wheel whose rim is a circle plus a six-lobed ripple of `amplitude` times the radius."""

    def draw(canvas: ImageDraw.ImageDraw) -> None:
        points: list[tuple[float, float]] = []
        for step in range(720):
            angle = math.tau * step / 720
            r = radius * (1 + amplitude * math.sin(6 * angle))
            points.append((cx + r * math.sin(angle), _GROUND - radius - r * math.cos(angle)))
        canvas.polygon(points, fill=255)

    return draw


def test_wheels_with_a_wavy_rim_are_rejected_for_their_residual() -> None:
    # Every point is within the 3% band of the circle, so only the residual gate can say no.
    def both(canvas: ImageDraw.ImageDraw) -> None:
        _wobbly_wheel(250, 60, 0.025)(canvas)
        _wobbly_wheel(750, 60, 0.025)(canvas)

    with pytest.raises(SilhouetteError, match="wheels not found.*residual"):
        measure_side(_wheeled_mask([], both))


def test_wheels_with_a_barely_wavy_rim_are_measured() -> None:
    def both(canvas: ImageDraw.ImageDraw) -> None:
        _wobbly_wheel(250, 60, 0.005)(canvas)
        _wobbly_wheel(750, 60, 0.005)(canvas)

    measure = measure_side(_wheeled_mask([], both))
    assert measure.wheelbase_px == pytest.approx(500, rel=0.01)


def _hidden_arc(width: int) -> Callable[[ImageDraw.ImageDraw], None]:
    """A block that fills the contour under the left `width` px of the first wheel's arc (the arc
    below the underside runs from x=194 to x=305). It leaves the rest of the arc intact."""

    def draw(canvas: ImageDraw.ImageDraw) -> None:
        canvas.rectangle((194, 290, 194 + width, _GROUND), fill=255)

    return draw


def test_a_wheel_with_a_third_of_its_arc_hidden_is_not_trusted() -> None:
    # 39 of 111 columns (35%) of the first arc are not on the circle: coverage 65%.
    with pytest.raises(SilhouetteError, match="wheels not found.*coverage 6"):
        measure_side(_wheeled_mask([(250, 60), (750, 60)], _hidden_arc(39)))


def test_a_wheel_with_84_percent_of_its_arc_left_is_not_trusted() -> None:
    # A block 18 px wide hides 19 of the 112 columns of the arc: coverage 84%, under the 85%
    # that is trusted.
    with pytest.raises(SilhouetteError, match="wheels not found.*coverage 84%"):
        measure_side(_wheeled_mask([(250, 60), (750, 60)], _hidden_arc(18)))


def test_a_wheel_with_87_percent_of_its_arc_left_is_still_measured() -> None:
    # A block 14 px wide hides 15 of them: coverage 87%.
    measure = measure_side(_wheeled_mask([(250, 60), (750, 60)], _hidden_arc(14)))
    assert measure.wheelbase_px == pytest.approx(500, rel=0.01)
    assert measure.wheels[0].coverage == pytest.approx(0.87, abs=0.01)


def test_measure_side_gives_the_same_answer_twice() -> None:
    image, _ = draw_car(wheelbase_scale=1.06)
    mask = mask_from_image(image)
    assert measure_side(mask) == measure_side(mask)


def test_bumps_that_barely_leave_the_underside_are_not_wheels() -> None:
    # Discs of radius 55 reaching only 5 px below the underside: a 49 degree arc, which fixes a
    # center too poorly to trust.
    image = Image.new("L", (1000, 400), 0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((50, 100, 950, 290), fill=255)
    for cx in (250, 750):
        draw.ellipse((cx - 55, 295 - 110, cx + 55, 295), fill=255)
    with pytest.raises(SilhouetteError, match="wheels not found.*arc"):
        measure_side(np.asarray(image) > 0)


def test_bumps_much_smaller_than_a_wheel_are_not_wheels() -> None:
    # Two half-discs of radius 40 under a 441 px tall car: 9% of its height. They are round and
    # clean (pixel rounding is under 1% of their radius), so only the size can turn them down.
    image = Image.new("L", (3000, 1000), 0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((150, 300, 2850, 700), fill=255)
    for cx in (750, 2250):
        draw.ellipse((cx - 40, 700 - 40, cx + 40, 700 + 40), fill=255)
    with pytest.raises(SilhouetteError, match="wheels not found.*radius"):
        measure_side(np.asarray(image) > 0)


def test_a_wide_shallow_belly_is_not_a_wheel() -> None:
    # A disc of radius 300 reaching 45 px below the underside is a round bump with a clean
    # circular rim, and with more columns than a tire. It is too big to be a wheel.
    def belly(canvas: ImageDraw.ImageDraw) -> None:
        canvas.ellipse((500 - 300, 335 - 600, 500 + 300, 335), fill=255)
        canvas.rectangle((0, 0, 999, 149), fill=0)  # keep only the part under the body

    measure = measure_side(_wheeled_mask([(150, 60), (850, 60)], belly))
    assert measure.wheelbase_px == pytest.approx(700, rel=0.01)
    assert measure.wheel_radius_px == pytest.approx(60, rel=0.03)


def test_wheels_of_different_size_are_rejected() -> None:
    with pytest.raises(SilhouetteError, match="wheels not found.*radii"):
        measure_side(_wheeled_mask([(250, 55), (750, 70)]))


def test_a_small_round_skid_does_not_displace_a_wheel() -> None:
    # A third round bump, smaller than a tire but clean enough to pass every gate, at the tail. The
    # wheels are the two best-supported circles, so the skid is left out. Picking the two
    # least-supported would take the skid, and then the radii would disagree.
    def skid(canvas: ImageDraw.ImageDraw) -> None:
        canvas.ellipse((910 - 40, 290 - 40, 910 + 40, 290 + 40), fill=255)

    measure = measure_side(_wheeled_mask([(250, 60), (650, 60)], skid))
    assert measure.wheelbase_px == pytest.approx(400, rel=0.005)
    assert measure.wheel_radius_px == pytest.approx(60, rel=0.03)
    assert [wheel.columns[0] for wheel in measure.wheels] == pytest.approx([195, 595], abs=3)


def test_many_small_bumps_do_not_crowd_out_the_wheels() -> None:
    # Nine 20 px wide bumps between the wheels (each wide enough to be looked at) and the two
    # wheel bumps make eleven. Only the widest few are fitted, and the wheels are the widest.
    def studs(canvas: ImageDraw.ImageDraw) -> None:
        for x in range(340, 700, 40):
            canvas.rectangle((x, 291, x + 19, 296), fill=255)

    measure = measure_side(_wheeled_mask([(250, 60), (750, 60)], studs))
    assert measure.wheelbase_px == pytest.approx(500, rel=0.005)


def test_the_message_counts_only_the_bumps_wide_enough_to_be_looked_at() -> None:
    # One wheel, and three bumps of 8 px (under 2% of the 900 px length) that are not looked at.
    def pimples(canvas: ImageDraw.ImageDraw) -> None:
        for x in (400, 500, 600):
            canvas.rectangle((x, 291, x + 7, 297), fill=255)

    with pytest.raises(SilhouetteError, match="1 usable of 1 bump"):
        measure_side(_wheeled_mask([(250, 60)], pimples))


def _flat_patched_car(depth_share: float) -> Image.Image:
    """The drawn car (1323 px wide) with the bottom of each tire cut flat, `depth_share` of the
    radius deep: the contact patch of a loaded tire."""
    image, truth = draw_car()
    ground = truth.front_center[1] + truth.tire_radius_px
    cut = round(ground - depth_share * truth.tire_radius_px)
    ImageDraw.Draw(image).rectangle((0, cut, image.width, image.height), fill=BACKGROUND)
    return image


def _two_wobbly_wheels(radius: int, amplitude: float) -> NDArray[np.bool_]:
    def both(canvas: ImageDraw.ImageDraw) -> None:
        _wobbly_wheel(250, radius, amplitude)(canvas)
        _wobbly_wheel(750, radius, amplitude)(canvas)

    return _wheeled_mask([], both)


def test_a_small_wheel_may_be_off_by_half_a_pixel_though_that_is_over_1_percent() -> None:
    # Radius 40: the rim is 0.54 px RMS off a circle, 1.3% of the radius. 1% alone would refuse
    # it; the pixel floor of 0.6 px, when asked for, lets it through.
    measure = measure_side(_two_wobbly_wheels(40, 0.01), min_residual_px=RENDER_MIN_RESIDUAL_PX)
    assert measure.wheelbase_px == pytest.approx(500, rel=0.01)
    assert all(wheel.residual > 0.01 for wheel in measure.wheels)


def test_a_small_wheel_that_is_off_by_two_thirds_of_a_pixel_is_refused() -> None:
    # The same wheel with a rim 0.66 px off a circle: over the floor.
    with pytest.raises(SilhouetteError, match=r"wheels not found.*residual 1\.6% of the radius"):
        measure_side(_two_wobbly_wheels(40, 0.016), min_residual_px=RENDER_MIN_RESIDUAL_PX)


def test_a_contact_patch_1_percent_deep_is_still_a_circle() -> None:
    measure = measure_side(mask_from_image(_flat_patched_car(0.01)))
    assert all(0.005 < wheel.residual < 0.01 for wheel in measure.wheels)


def test_a_contact_patch_3_percent_deep_is_no_longer_a_circle() -> None:
    # Its residual is 1.1% of the radius: over the 1% that is allowed, but under 1.25% and 1.5%,
    # which a looser gate would let through.
    with pytest.raises(SilhouetteError, match=r"wheels not found.*residual 1\.1% of the radius"):
        measure_side(mask_from_image(_flat_patched_car(0.03)))


def test_a_clearance_of_70_mm_leaves_an_arc_that_is_trusted() -> None:
    image, _ = draw_car(underside_mm=(70.0, 70.0))
    measure = measure_side(mask_from_image(image))
    assert all(65 < wheel.arc_deg < 70 for wheel in measure.wheels)


def test_a_clearance_of_50_mm_leaves_an_arc_that_is_not() -> None:
    image, _ = draw_car(underside_mm=(50.0, 50.0))
    with pytest.raises(SilhouetteError, match=r"wheels not found.*arc of 56 degrees"):
        measure_side(mask_from_image(image))


def test_wheels_of_radius_60_and_64_are_a_pair() -> None:
    measure = measure_side(_wheeled_mask([(250, 60), (750, 64)]))
    assert measure.wheelbase_px == pytest.approx(500, rel=0.005)


def test_wheels_of_radius_60_and_68_are_not() -> None:
    with pytest.raises(SilhouetteError, match="wheels not found.*radii"):
        measure_side(_wheeled_mask([(250, 60), (750, 68)]))


def test_a_wheel_of_70_px_in_a_181_px_car_is_a_wheel() -> None:
    measure = measure_side(_wheeled_mask([(250, 70), (750, 70)]))  # 38.7% of the height
    assert measure.wheel_radius_px == pytest.approx(70, rel=0.03)


def test_a_wheel_of_74_px_in_a_181_px_car_is_too_big_to_be_one() -> None:
    with pytest.raises(SilhouetteError, match="wheels not found.*radius"):  # 40.9% of the height
        measure_side(_wheeled_mask([(250, 74), (750, 74)]))


def test_a_silhouette_with_one_wheel_is_not_measured() -> None:
    with pytest.raises(SilhouetteError, match="wheels not found") as refused:
        measure_side(_wheeled_mask([(250, 60)]))
    assert "1 usable of 1 bump(s)" in str(refused.value)
    assert "shadow" not in str(refused.value)  # one wheel is found: this is not the shadow case
