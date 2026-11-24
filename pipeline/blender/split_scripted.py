# pyright: basic, reportMissingImports=false
"""Split a prepared car into named parts by rules: `-- --plan <plan.json>`.

Plan: `glb` (one mesh, as `prepare_car.py` writes it), `out_dir`, `modules_blender` ({name: {min,
max}}, in order) and the thresholds `classify` reads. Spatial numbers are in the Blender frame (Z
up, nose at +Y) under keys ending `_blender`; color thresholds carry no suffix. A face's color is
its material's base color texture at the face's UV center, else the base color factor, sRGB-coded.
Writes `out_dir/segmented.glb`, one mesh object per part named by it, and prints `SPLIT {...}`.
"""

import json
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Color, Matrix


def import_mesh(glb):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if len(meshes) != 1:
        raise RuntimeError(f"{glb} must hold one mesh, as prepare_car.py writes it: {len(meshes)}")
    obj = meshes[0]
    obj.data.transform(obj.matrix_world)
    obj.parent, obj.matrix_world = None, Matrix.Identity(4)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=obj.modifiers.new("tri", "TRIANGULATE").name)
    return obj


def read(items, prop, shape, dtype):
    out = np.zeros(int(np.prod(shape)), dtype=dtype)
    items.foreach_get(prop, out)
    return out.reshape(shape)


def base_color(material):
    nodes = material.node_tree.nodes if material and material.node_tree else []
    principled = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
    if principled is None:
        return (0.8, 0.8, 0.8), None
    socket = principled.inputs["Base Color"]
    stack, seen, image = [link.from_node for link in socket.links], set(), None
    while stack and image is None:
        node = stack.pop()
        if node.name not in seen:
            seen.add(node.name)
            if node.type == "TEX_IMAGE" and node.image and node.image.size[0] > 0:
                image = node.image
            stack += [link.from_node for i in node.inputs for link in i.links]
    return Color(socket.default_value[:3]).from_scene_linear_to_srgb()[:], image


def face_colors(obj):
    mesh, n = obj.data, len(obj.data.polygons)
    index = read(mesh.polygons, "material_index", n, np.int32)
    starts = read(mesh.polygons, "loop_start", n, np.int32)
    layer = mesh.uv_layers.active
    uvs = read(layer.uv, "vector", (len(mesh.loops), 2), np.float32) if layer else None
    colors = np.empty((n, 3), dtype=np.float32)
    for slot, material in enumerate([s.material for s in obj.material_slots] or [None]):
        mask = index == slot
        factor, image = base_color(material)
        colors[mask] = factor
        if image is not None and uvs is not None and mask.any():
            width, height = image.size
            pixels = np.zeros(width * height * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
            uv = uvs[starts[mask, None] + np.arange(3)].mean(axis=1)
            x = np.floor(uv[:, 0] * width).astype(np.int64) % width
            y = np.floor(uv[:, 1] * height).astype(np.int64) % height
            colors[mask] = pixels.reshape(height, width, 4)[y, x, :3]
    return colors


def classify(obj, plan):
    """The part name of every face: modules, undercarriage (down-facing, low), glass (dark, above
    the belt line), lights (bright or red, in the end bands), grille (dark, front center, low),
    trim (other dark below the belt line), body (the rest)."""
    mesh, n = obj.data, len(obj.data.polygons)
    centers = read(mesh.polygons, "center", (n, 3), np.float32)
    normals = read(mesh.polygons, "normal", (n, 3), np.float32)
    r, g, b = face_colors(obj).T
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    x, y, z = centers.T
    rules = [
        (name, np.all((centers >= box["min"]) & (centers <= box["max"]), axis=1))
        for name, box in plan["modules_blender"].items()
    ]
    down = normals[:, 2] < plan["undercarriage_normal_z_max_blender"]
    rules.append(("undercarriage", down & (z < plan["undercarriage_z_max_blender"])))
    dark, belt = luminance <= plan["dark_luminance_max"], plan["belt_line_z_blender"]
    rules.append(("glass", dark & (z > belt)))
    red = (r >= plan["red_min"]) & (r >= plan["red_dominance"] * np.maximum(g, b))
    light = (luminance >= plan["bright_luminance_min"]) | red
    front, rear = y >= plan["front_band_y_min_blender"], y <= plan["rear_band_y_max_blender"]
    rules += [("lights_front", light & front), ("lights_rear", light & rear)]
    centered = (np.abs(x) <= plan["grille_x_max_blender"]) & (z <= plan["grille_z_max_blender"])
    rules += [("grille", dark & front & centered), ("trim", dark & (z <= belt))]
    labels, free = np.full(n, "body", dtype=object), np.ones(n, dtype=bool)
    for name, mask in rules:  # each rule takes from what is left
        labels[mask & free] = name
        free &= ~mask
    return labels


def split(obj, labels):
    counts = {}
    obj.name = obj.data.name = "source"  # the parts take the part names
    for name in dict.fromkeys(labels):  # in rule order
        keep = (labels == name).tolist()
        part = obj.copy()
        part.data = obj.data.copy()
        part.name = part.data.name = name
        bpy.context.scene.collection.objects.link(part)
        bm = bmesh.new()
        bm.from_mesh(part.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep[f.index]], context="FACES")
        bm.to_mesh(part.data)
        bm.free()
        counts[name] = keep.count(True)
    bpy.data.objects.remove(obj, do_unlink=True)
    return counts


def main(plan):
    obj = import_mesh(plan["glb"])
    counts = split(obj, classify(obj, plan))
    bpy.ops.export_scene.gltf(
        filepath=str(Path(plan["out_dir"]) / "segmented.glb"),
        export_format="GLB",
        export_animations=False,
        export_morph=False,
        export_skins=False,
    )
    print("SPLIT", json.dumps(counts))


if __name__ == "__main__":
    try:
        main(json.loads(Path(sys.argv[sys.argv.index("--plan") + 1]).read_text("utf-8")))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
