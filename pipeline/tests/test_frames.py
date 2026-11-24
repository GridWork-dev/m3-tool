from m3_pipeline.stages.lib.frames import (
    CutBox,
    Vec,
    blender_to_contract,
    box_to_blender,
    box_to_contract,
    contract_to_blender,
    lhw_to_blender_xyz,
)


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec, b: Vec) -> Vec:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def test_contract_to_blender_round_trips_points_directions_and_boxes() -> None:
    points: list[Vec] = [
        (0.0, 0.0, 0.0),
        (1.0, 2.0, 3.0),
        (-0.37, 1.1, 0.0),
        (-0.754, 0.32985, -1.3655),
        (0.7625, 0.3306, 1.3655),
        (4.492, -1.372, 1.78),
    ]
    for point in points:
        assert blender_to_contract(contract_to_blender(point)) == point
        assert contract_to_blender(blender_to_contract(point)) == point
    # A direction is the difference of two points, so one function must convert both alike.
    for a, b in zip(points, points[1:], strict=False):
        direction = _sub(b, a)
        assert contract_to_blender(direction) == _sub(
            contract_to_blender(b), contract_to_blender(a)
        )
        assert blender_to_contract(contract_to_blender(direction)) == direction
    boxes = [
        CutBox((-0.9, -0.05, -2.3), (0.9, 0.7, -1.8)),
        CutBox((-0.5, 1.15, -0.6), (0.5, 1.42, 0.8)),
    ]
    for box in boxes:
        assert box_to_contract(box_to_blender(box)) == box
        assert box_to_blender(box_to_contract(box)) == box


def test_nose_toward_minus_z_maps_to_plus_y_and_up_stays_up() -> None:
    assert contract_to_blender((0.0, 0.0, -1.0)) == (0.0, 1.0, 0.0)
    assert contract_to_blender((0.0, 1.0, 0.0)) == (0.0, 0.0, 1.0)
    # The eye point is left of center in both frames: the driver stays at -x.
    assert contract_to_blender((-0.37, 1.1, 0.0)) == (-0.37, 0.0, 1.1)


def test_the_conversion_keeps_handedness() -> None:
    # A mirroring conversion would put the steering wheel on the wrong side of the car.
    ex, ey, ez = (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)
    bx, by, bz = (contract_to_blender(axis) for axis in (ex, ey, ez))
    assert _cross(bx, by) == bz


def test_box_conversion_resorts_min_and_max() -> None:
    box = CutBox((-0.9, 0.0, -2.3), (0.9, 0.7, -1.8))
    converted = box_to_blender(box)
    # contract z in [-2.3, -1.8] becomes blender y in [1.8, 2.3]: the corners swap.
    assert converted == CutBox((-0.9, 1.8, 0.0), (0.9, 2.3, 0.7))
    assert all(lo <= hi for lo, hi in zip(converted.min, converted.max, strict=True))
    back = box_to_contract(converted)
    assert all(lo <= hi for lo, hi in zip(back.min, back.max, strict=True))


def test_lhw_to_blender_xyz_orders_width_length_height() -> None:
    assert lhw_to_blender_xyz((4.492, 1.372, 1.78)) == (1.78, 4.492, 1.372)
