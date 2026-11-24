import json
import struct
from pathlib import Path

import pytest

from m3_pipeline.stages.lib.glbmeta import (
    GlbError,
    ai_markers,
    mesh_stats,
    read_glb_asset_block,
)

JSON_CHUNK, BIN_CHUNK = 0x4E4F534A, 0x004E4942


def _glb(path: Path, document: dict[str, object], binary: bytes = b"") -> Path:
    """Write a GLB from a JSON document and a binary chunk, padded as the format requires."""
    text = json.dumps(document).encode("utf-8")
    text += b" " * (-len(text) % 4)
    chunks = struct.pack("<II", len(text), JSON_CHUNK) + text
    if binary:
        padded = binary + b"\0" * (-len(binary) % 4)
        chunks += struct.pack("<II", len(padded), BIN_CHUNK) + padded
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)
    return path


def _accessor(count: int, **extra: object) -> dict[str, object]:
    return {"bufferView": 0, "componentType": 5126, "count": count, "type": "VEC3", **extra}


def _quad_document() -> dict[str, object]:
    """Two meshes. The first is a quad of two indexed triangles, the second three unindexed
    triangles. The first sits on a node moved 10 m along x, the second on a node at the origin."""
    return {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": [
            {"name": "body", "mesh": 0, "translation": [10.0, 0.0, 0.0]},
            {"name": "roof", "mesh": 1},
        ],
        "meshes": [
            {"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]},
            {"primitives": [{"attributes": {"POSITION": 2}}]},
        ],
        "accessors": [
            _accessor(4, min=[-1.0, 0.0, -2.0], max=[1.0, 1.0, 2.0]),
            {"bufferView": 0, "componentType": 5123, "count": 6, "type": "SCALAR"},
            _accessor(9, min=[-0.5, 1.0, -0.5], max=[0.5, 1.5, 0.5]),
        ],
        "buffers": [{"byteLength": 4}],
        "bufferViews": [{"buffer": 0, "byteLength": 4}],
    }


def test_mesh_stats_counts_triangles_and_reads_position_bounds(tmp_path: Path) -> None:
    stats = mesh_stats(_glb(tmp_path / "a.glb", _quad_document(), b"\0\0\0\0"))
    assert stats.triangles == 2 + 3
    # The first mesh is x in [9, 11] after its node's translation; the second is untouched.
    assert stats.bbox_min == pytest.approx((-0.5, 0.0, -2.0))
    assert stats.bbox_max == pytest.approx((11.0, 1.5, 2.0))


def test_mesh_stats_counts_a_mesh_once_per_node_that_uses_it(tmp_path: Path) -> None:
    document = _quad_document()
    document["nodes"] = [{"name": "a", "mesh": 0}, {"name": "b", "mesh": 0, "scale": [2, 2, 2]}]
    stats = mesh_stats(_glb(tmp_path / "a.glb", document))
    assert stats.triangles == 4
    assert stats.bbox_max == pytest.approx((2.0, 2.0, 4.0))  # the scaled copy


def test_mesh_stats_applies_a_node_rotation_and_a_parent_chain(tmp_path: Path) -> None:
    half = 0.5**0.5  # 90 degrees about +x turns +y into +z
    document = _quad_document()
    document["nodes"] = [
        {"name": "root", "children": [1], "translation": [0.0, 5.0, 0.0]},
        {"name": "body", "mesh": 0, "rotation": [half, 0.0, 0.0, half]},
    ]
    document["scenes"] = [{"nodes": [0]}]
    stats = mesh_stats(_glb(tmp_path / "a.glb", document))
    # The mesh spans y in [0, 1] and z in [-2, 2]: rotated, z in [0, 1] and y in [-2, 2], then +5.
    assert stats.bbox_min == pytest.approx((-1.0, 3.0, 0.0))
    assert stats.bbox_max == pytest.approx((1.0, 7.0, 1.0))


def test_mesh_stats_ignores_a_mesh_no_scene_node_uses(tmp_path: Path) -> None:
    document = _quad_document()
    document["nodes"] = [{"name": "body", "mesh": 0}, {"name": "spare", "mesh": 1}]
    document["scenes"] = [{"nodes": [0]}]
    assert mesh_stats(_glb(tmp_path / "a.glb", document)).triangles == 2


def test_mesh_stats_is_valid_for_a_meshopt_file(tmp_path: Path) -> None:
    """Meshopt compresses the buffer, but the accessors keep their counts and bounds."""
    document = _quad_document()
    document["extensionsUsed"] = ["EXT_meshopt_compression"]
    document["extensionsRequired"] = ["EXT_meshopt_compression"]
    document["bufferViews"] = [
        {
            "buffer": 0,
            "byteLength": 4,
            "extensions": {
                "EXT_meshopt_compression": {
                    "buffer": 0,
                    "byteOffset": 0,
                    "byteLength": 4,
                    "byteStride": 12,
                    "count": 4,
                    "mode": "ATTRIBUTES",
                }
            },
        }
    ]
    stats = mesh_stats(_glb(tmp_path / "a.glb", document, b"\xde\xad\xbe\xef"))
    assert stats.triangles == 5
    assert stats.bbox_max == pytest.approx((11.0, 1.5, 2.0))


def test_mesh_stats_counts_strip_and_fan_primitives_and_skips_lines(tmp_path: Path) -> None:
    document = _quad_document()
    document["meshes"] = [
        {
            "primitives": [
                {"attributes": {"POSITION": 2}, "mode": 5},  # strip: 9 vertices, 7 triangles
                {"attributes": {"POSITION": 2}, "mode": 6},  # fan: 7 triangles
                {"attributes": {"POSITION": 2}, "mode": 1},  # lines: none
            ]
        },
        {"primitives": []},
    ]
    document["nodes"] = [{"name": "body", "mesh": 0}]
    document["scenes"] = [{"nodes": [0]}]
    assert mesh_stats(_glb(tmp_path / "a.glb", document)).triangles == 14


def test_mesh_stats_reads_names_materials_and_textures(tmp_path: Path) -> None:
    document = _quad_document()
    document["nodes"] = [
        {"name": "body", "mesh": 0, "children": [1]},
        {"name": "wheel_FL"},
        {"mesh": 1},
    ]
    document["scenes"] = [{"nodes": [0, 2]}]
    document["materials"] = [{"name": "paint"}, {"name": "glass"}, {}]
    document["textures"] = [{"source": 0}, {"source": 1}]
    document["images"] = [{"uri": "a.png"}, {"uri": "b.png"}]
    stats = mesh_stats(_glb(tmp_path / "a.glb", document))
    assert stats.node_names == ("body", "wheel_FL")
    assert stats.material_names == ("paint", "glass")
    assert stats.texture_count == 2


def _one_mesh_document(position: dict[str, object], scale: float) -> dict[str, object]:
    """One node, scaled by `scale`, using a mesh with a single POSITION accessor."""
    return {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": "part", "mesh": 0, "scale": [scale, scale, scale]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"bufferView": 0, "type": "VEC3", "count": 8, **position}],
        "buffers": [{"byteLength": 4}],
        "bufferViews": [{"buffer": 0, "byteLength": 4}],
    }


# componentType: (name, largest value, smallest raw value, a normalized accessor's unit)
INTEGER_POSITIONS = [
    pytest.param(5120, 127, -128, id="int8"),
    pytest.param(5121, 255, 0, id="uint8"),
    pytest.param(5122, 32767, -32768, id="int16"),
    pytest.param(5123, 65535, 0, id="uint16"),
]


@pytest.mark.parametrize(("component_type", "largest", "smallest"), INTEGER_POSITIONS)
def test_mesh_stats_decodes_normalized_integer_position_bounds(
    tmp_path: Path, component_type: int, largest: int, smallest: int
) -> None:
    """A quantized file (KHR_mesh_quantization with normalized positions) stores min and max as
    raw integers, and its node scale carries the real size. The bounds must be decoded first."""
    signed = smallest < 0
    decoded_low = -1.0 if signed else 0.0
    quantized = _one_mesh_document(
        {
            "componentType": component_type,
            "normalized": True,
            "min": [smallest, 0, smallest],
            "max": [largest, largest, largest],
        },
        scale=0.3,
    )
    as_floats = _one_mesh_document(
        {
            "componentType": 5126,
            "min": [decoded_low, 0.0, decoded_low],
            "max": [1.0, 1.0, 1.0],
        },
        scale=0.3,
    )
    got = mesh_stats(_glb(tmp_path / "q.glb", quantized))
    want = mesh_stats(_glb(tmp_path / "f.glb", as_floats))
    assert got.bbox_min == pytest.approx(want.bbox_min)
    assert got.bbox_max == pytest.approx(want.bbox_max)
    assert max(b - a for a, b in zip(got.bbox_min, got.bbox_max, strict=True)) <= 0.6 + 1e-9


def test_mesh_stats_leaves_unnormalized_integer_bounds_alone(tmp_path: Path) -> None:
    """Without `normalized`, an integer position is its own value; only the node scales it."""
    document = _one_mesh_document(
        {"componentType": 5122, "min": [-100, 0, -100], "max": [100, 100, 100]}, scale=0.01
    )
    stats = mesh_stats(_glb(tmp_path / "a.glb", document))
    assert stats.bbox_min == pytest.approx((-1.0, 0.0, -1.0))
    assert stats.bbox_max == pytest.approx((1.0, 1.0, 1.0))


def test_mesh_stats_of_a_file_without_geometry_is_an_error(tmp_path: Path) -> None:
    path = _glb(tmp_path / "a.glb", {"asset": {"version": "2.0"}})
    with pytest.raises(GlbError, match="geometry"):
        mesh_stats(path)


def test_read_glb_asset_block_reads_generator_and_extras(tmp_path: Path) -> None:
    asset: dict[str, object] = {
        "version": "2.0",
        "generator": "Example Generator 1.0",
        "copyright": "Example Corp",
        "extras": {"model": "example-3d", "seed": 7},
    }
    block = read_glb_asset_block(_glb(tmp_path / "a.glb", {"asset": asset}))
    assert block == asset


def test_ai_markers_returns_generator_copyright_and_extras_when_present() -> None:
    block: dict[str, object] = {
        "version": "2.0",
        "generator": "Example Generator 1.0",
        "copyright": "Example Corp",
        "extras": {"model": "example-3d"},
    }
    assert ai_markers(block) == {
        "generator": "Example Generator 1.0",
        "copyright": "Example Corp",
        "extras": {"model": "example-3d"},
    }
    assert ai_markers({"version": "2.0", "generator": "Only A Generator"}) == {
        "generator": "Only A Generator"
    }


def test_ai_markers_is_empty_when_the_file_carries_none() -> None:
    assert ai_markers({"version": "2.0"}) == {}
    assert ai_markers({"version": "2.0", "generator": "", "copyright": "  ", "extras": {}}) == {}


def test_a_file_that_is_not_a_glb_raises_a_clear_error(tmp_path: Path) -> None:
    text = tmp_path / "a.glb"
    text.write_text('{"asset": {"version": "2.0"}}', "utf-8")
    with pytest.raises(GlbError, match="not a GLB"):
        mesh_stats(text)
    with pytest.raises(GlbError, match="not a GLB"):
        read_glb_asset_block(text)

    empty = tmp_path / "empty.glb"
    empty.write_bytes(b"")
    with pytest.raises(GlbError, match="not a GLB"):
        read_glb_asset_block(empty)

    truncated = _glb(tmp_path / "t.glb", _quad_document())
    truncated.write_bytes(truncated.read_bytes()[:40])
    with pytest.raises(GlbError, match="truncated"):
        mesh_stats(truncated)

    version_one = tmp_path / "v1.glb"
    version_one.write_bytes(struct.pack("<4sII", b"glTF", 1, 12))
    with pytest.raises(GlbError, match="version"):
        read_glb_asset_block(version_one)

    bad_json = tmp_path / "bad.glb"
    body = b"{not json"
    body += b" " * (-len(body) % 4)
    chunk = struct.pack("<II", len(body), JSON_CHUNK) + body
    bad_json.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunk)) + chunk)
    with pytest.raises(GlbError, match="JSON"):
        read_glb_asset_block(bad_json)


def test_a_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        mesh_stats(tmp_path / "nope.glb")
