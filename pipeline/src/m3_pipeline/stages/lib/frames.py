"""The one conversion between Python's contract frame and Blender's frame.

Contract frame (spec 9.6): meters, +Y up, nose toward -Z, the driver's side at -X. Blender frame:
+Z up, nose toward +Y, the driver still at -X. `(x, y, z)_contract -> (x, -z, y)_blender` is a
rotation (no mirroring), and it is the same for points, directions and box corners, so every
spatial number that crosses into or out of a Blender script goes through this file. It is also
what Blender's glTF exporter does (`export_yup`), which is why a Blender-frame mesh exports as a
contract-frame GLB.

Standard library only, so it imports before any third-party package is installed.
"""

from dataclasses import dataclass

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class CutBox:
    """An axis-aligned box. `min` is at or below `max` on every axis."""

    min: Vec
    max: Vec


def contract_to_blender(v: Vec) -> Vec:
    """A point, direction or box corner from the contract frame to the Blender frame."""
    x, y, z = v
    # `0.0 - z` and not `-z`: a zero must not turn into -0.0, which json writes as "-0.0".
    return (x, 0.0 - z, y)


def blender_to_contract(v: Vec) -> Vec:
    """The inverse of `contract_to_blender`."""
    x, y, z = v
    return (x, z, 0.0 - y)


def box_to_blender(box: CutBox) -> CutBox:
    """The box in the Blender frame: both corners converted, then `min` and `max` re-sorted."""
    return _sorted_box(contract_to_blender(box.min), contract_to_blender(box.max))


def box_to_contract(box: CutBox) -> CutBox:
    """The box in the contract frame: both corners converted, then `min` and `max` re-sorted."""
    return _sorted_box(blender_to_contract(box.min), blender_to_contract(box.max))


def lhw_to_blender_xyz(v: Vec) -> Vec:
    """`(length, height, width)` as the x, y, z of the oriented Blender frame.

    Width runs along x, length along y (the nose at +y) and height along z.
    """
    length, height, width = v
    return (width, length, height)


def _sorted_box(a: Vec, b: Vec) -> CutBox:
    return CutBox(
        (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2])),
        (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2])),
    )
