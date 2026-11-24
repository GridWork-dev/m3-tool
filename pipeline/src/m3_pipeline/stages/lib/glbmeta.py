"""What a GLB says about itself, read from its JSON chunk alone.

The numbers come from the accessors (`count`, and `min` and `max` of POSITION), which every
valid GLB carries whether or not its buffers are compressed, so they hold for meshopt files that
nothing here decodes. The binary chunk is never read. Triangles and bounds are measured the way
`src/lib/asset-validate.ts` measures them: over the default scene, once per node that uses a
mesh, with every node's transform applied.

Standard library only, so it imports before any third-party package is installed.
"""

import json
import os
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from m3_pipeline.stages.lib.frames import Vec

_MAGIC = b"glTF"
_JSON_CHUNK = 0x4E4F534A
_HEADER = struct.Struct("<4sII")  # magic, version, total length
_CHUNK_HEADER = struct.Struct("<II")  # chunk length, chunk type
_TRIANGLES, _TRIANGLE_STRIP, _TRIANGLE_FAN = 4, 5, 6

# A column-major 4x4 matrix, as glTF writes `matrix`.
_Matrix = tuple[float, ...]
_IDENTITY: _Matrix = (
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
)


class GlbError(ValueError):
    """A file is not a GLB this module can read, or its JSON is malformed."""


@dataclass(frozen=True)
class MeshStats:
    triangles: int
    bbox_min: Vec
    bbox_max: Vec
    node_names: tuple[str, ...]  # named nodes of the default scene, parents before children
    material_names: tuple[str, ...]  # every named material of the file
    texture_count: int


def mesh_stats(path: Path) -> MeshStats:
    """Triangle count, world bounding box, names and texture count of a GLB."""
    doc = _read_json(path)
    nodes = _objects(doc, "nodes", path)
    meshes = _objects(doc, "meshes", path)
    accessors = _objects(doc, "accessors", path)

    triangles = 0
    lows: list[Vec] = []
    highs: list[Vec] = []
    names: list[str] = []
    for index, world in _walk_scene(doc, nodes, path):
        node = nodes[index]
        name = node.get("name")
        if isinstance(name, str) and name:
            names.append(name)
        mesh_index = node.get("mesh")
        if mesh_index is None:
            continue
        mesh = _at(meshes, mesh_index, "mesh", path)
        for primitive in _objects(mesh, "primitives", path):
            triangles += _triangles(primitive, accessors, path)
            bounds = _position_bounds(primitive, accessors, path)
            if bounds is not None:
                low, high = _transformed_box(world, *bounds)
                lows.append(low)
                highs.append(high)
    if not lows:
        raise GlbError(f"{path} has no geometry: no mesh with a POSITION accessor in its scene")
    return MeshStats(
        triangles=triangles,
        bbox_min=(min(v[0] for v in lows), min(v[1] for v in lows), min(v[2] for v in lows)),
        bbox_max=(max(v[0] for v in highs), max(v[1] for v in highs), max(v[2] for v in highs)),
        node_names=tuple(names),
        material_names=tuple(_names(_objects(doc, "materials", path))),
        texture_count=len(_objects(doc, "textures", path)),
    )


def read_glb_asset_block(path: Path) -> dict[str, object]:
    """The file's `asset` object: `version`, and when present `generator`, `copyright`, `extras`."""
    asset = _read_json(path).get("asset")
    if not isinstance(asset, dict):
        raise GlbError(f"{path} has no asset object")
    return dict(cast("dict[str, object]", asset))


def ai_markers(asset_block: Mapping[str, object]) -> dict[str, object]:
    """The fields of an asset block that can say who made a file: `generator`, `copyright` and
    `extras`, each only when it is not empty. `{}` when the file carries none."""
    found: dict[str, object] = {}
    for key in ("generator", "copyright"):
        value = asset_block.get(key)
        if isinstance(value, str) and value.strip():
            found[key] = value
    extras = asset_block.get("extras")
    if isinstance(extras, str):
        extras = extras.strip()
    if extras:
        found["extras"] = extras
    return found


def _read_json(path: Path) -> dict[str, object]:
    """The parsed JSON chunk. Reads the 12-byte header and the first chunk, nothing more."""
    with path.open("rb") as handle:
        size = os.fstat(handle.fileno()).st_size
        header = handle.read(_HEADER.size)
        if len(header) < _HEADER.size or header[:4] != _MAGIC:
            raise GlbError(f"{path} is not a GLB file: it does not start with the glTF header")
        _, version, declared = _HEADER.unpack(header)
        if version != 2:
            raise GlbError(f"{path}: GLB version {version} is not supported, only version 2")
        if declared > size:
            raise GlbError(f"{path} is truncated: its header says {declared} bytes, it has {size}")
        chunk_header = handle.read(_CHUNK_HEADER.size)
        if len(chunk_header) < _CHUNK_HEADER.size:
            raise GlbError(f"{path} is truncated: it ends before the JSON chunk")
        length, kind = _CHUNK_HEADER.unpack(chunk_header)
        if kind != _JSON_CHUNK:
            raise GlbError(f"{path}: the first chunk is not JSON (type {kind:#x})")
        body = handle.read(length)
    if len(body) < length:
        raise GlbError(f"{path} is truncated inside its JSON chunk")
    try:
        parsed: object = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GlbError(f"{path}: the JSON chunk is not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise GlbError(f"{path}: the JSON chunk is not an object")
    return cast("dict[str, object]", parsed)


def _objects(owner: Mapping[str, object], key: str, path: Path) -> list[dict[str, object]]:
    """`owner[key]` as a list of objects; absent means empty."""
    value = owner.get(key)
    if value is None:
        return []
    items = cast("list[object]", value) if isinstance(value, list) else None
    if items is None or not all(isinstance(item, dict) for item in items):
        raise GlbError(f"{path}: {key} is not a list of objects")
    return cast("list[dict[str, object]]", items)


def _at(items: list[dict[str, object]], index: object, what: str, path: Path) -> dict[str, object]:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(items):
        raise GlbError(f"{path}: {what} index {index!r} does not exist")
    return items[index]


def _names(items: list[dict[str, object]]) -> list[str]:
    names = (item.get("name") for item in items)
    return [name for name in names if isinstance(name, str) and name]


def _numbers(value: object, count: int, what: str, path: Path) -> tuple[float, ...]:
    items = cast("list[object]", value) if isinstance(value, list) else []
    if len(items) != count or not all(
        isinstance(n, int | float) and not isinstance(n, bool) for n in items
    ):
        raise GlbError(f"{path}: {what} is not a list of {count} numbers")
    return tuple(float(n) for n in cast("list[float]", items))


def _walk_scene(
    doc: dict[str, object], nodes: list[dict[str, object]], path: Path
) -> list[tuple[int, _Matrix]]:
    """Every node of the default scene, once per place it appears, with its world matrix."""
    scenes = _objects(doc, "scenes", path)
    if scenes:
        scene = _at(scenes, doc.get("scene", 0), "scene", path)
        roots = _int_list(scene.get("nodes"), "scene nodes", path)
    else:
        children = {c for n in nodes for c in _int_list(n.get("children"), "children", path)}
        roots = [i for i in range(len(nodes)) if i not in children]
    visited: list[tuple[int, _Matrix]] = []

    def visit(index: int, parent: _Matrix, ancestors: frozenset[int]) -> None:
        if index in ancestors:
            raise GlbError(f"{path}: node {index} is its own ancestor")
        node = _at(nodes, index, "node", path)
        world = _multiply(parent, _local_matrix(node, path))
        visited.append((index, world))
        for child in _int_list(node.get("children"), "children", path):
            visit(child, world, ancestors | {index})

    for root in roots:
        visit(root, _IDENTITY, frozenset())
    return visited


def _int_list(value: object, what: str, path: Path) -> list[int]:
    if value is None:
        return []
    items = cast("list[object]", value) if isinstance(value, list) else None
    if items is None or not all(isinstance(i, int) and not isinstance(i, bool) for i in items):
        raise GlbError(f"{path}: {what} is not a list of integers")
    return cast("list[int]", items)


def _local_matrix(node: dict[str, object], path: Path) -> _Matrix:
    if "matrix" in node:
        return _numbers(node["matrix"], 16, "a node matrix", path)
    tx, ty, tz = _numbers(node.get("translation", [0, 0, 0]), 3, "a node translation", path)
    qx, qy, qz, qw = _numbers(node.get("rotation", [0, 0, 0, 1]), 4, "a node rotation", path)
    sx, sy, sz = _numbers(node.get("scale", [1, 1, 1]), 3, "a node scale", path)
    norm = (qx * qx + qy * qy + qz * qz + qw * qw) ** 0.5 or 1.0
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    # T * R * S, column-major: the columns are the scaled rotation axes, then the translation.
    return (
        (1 - 2 * (qy * qy + qz * qz)) * sx,
        (2 * (qx * qy + qz * qw)) * sx,
        (2 * (qx * qz - qy * qw)) * sx,
        0.0,
        (2 * (qx * qy - qz * qw)) * sy,
        (1 - 2 * (qx * qx + qz * qz)) * sy,
        (2 * (qy * qz + qx * qw)) * sy,
        0.0,
        (2 * (qx * qz + qy * qw)) * sz,
        (2 * (qy * qz - qx * qw)) * sz,
        (1 - 2 * (qx * qx + qy * qy)) * sz,
        0.0,
        tx,
        ty,
        tz,
        1.0,
    )


def _multiply(a: _Matrix, b: _Matrix) -> _Matrix:
    """`a * b` for column-major 4x4 matrices."""
    return tuple(
        sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
        for col in range(4)
        for row in range(4)
    )


def _position_index(primitive: dict[str, object]) -> object:
    """The accessor index of the primitive's POSITION attribute, or None."""
    attributes = primitive.get("attributes")
    if not isinstance(attributes, dict):
        return None
    return cast("dict[str, object]", attributes).get("POSITION")


def _triangles(primitive: dict[str, object], accessors: list[dict[str, object]], path: Path) -> int:
    """Triangles of one primitive. Points and lines count for none."""
    mode = primitive.get("mode", _TRIANGLES)
    if "indices" in primitive:
        source = _at(accessors, primitive["indices"], "accessor", path)
    else:
        position = _position_index(primitive)
        if position is None:
            return 0
        source = _at(accessors, position, "accessor", path)
    count = source.get("count")
    if isinstance(count, bool) or not isinstance(count, int):
        raise GlbError(f"{path}: an accessor has no integer count")
    if mode == _TRIANGLES:
        return count // 3
    if mode in (_TRIANGLE_STRIP, _TRIANGLE_FAN):
        return max(0, count - 2)
    return 0


def _position_bounds(
    primitive: dict[str, object], accessors: list[dict[str, object]], path: Path
) -> tuple[Vec, Vec] | None:
    position = _position_index(primitive)
    if position is None:
        return None
    accessor = _at(accessors, position, "accessor", path)
    low = _numbers(accessor.get("min"), 3, "a POSITION accessor's min", path)
    high = _numbers(accessor.get("max"), 3, "a POSITION accessor's max", path)
    return (low[0], low[1], low[2]), (high[0], high[1], high[2])


def _transformed_box(world: _Matrix, low: Vec, high: Vec) -> tuple[Vec, Vec]:
    """The box that bounds the eight corners of `low`..`high` after `world`."""
    corners = [
        _transform_point(world, (x, y, z))
        for x in (low[0], high[0])
        for y in (low[1], high[1])
        for z in (low[2], high[2])
    ]
    return (
        (min(c[0] for c in corners), min(c[1] for c in corners), min(c[2] for c in corners)),
        (max(c[0] for c in corners), max(c[1] for c in corners), max(c[2] for c in corners)),
    )


def _transform_point(m: _Matrix, p: Vec) -> Vec:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )
