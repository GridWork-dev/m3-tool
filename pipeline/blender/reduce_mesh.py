# pyright: basic, reportMissingImports=false
"""Reduce a GLB to about a triangle budget: `-- --plan <plan.json>`.

Plan: `glb` (the input), `out_glb` (where to write) and `target_triangles` (the budget). The meshes
are joined and collapse-decimated to a little under the budget; a file at or under it is
re-exported as it is. Nothing is rotated or scaled, so the copy keeps the input's frame and size,
and it keeps its materials and textures (a split by Tripo may want them). Prints `REDUCE {...}`.
The exporter leaves out animations, morph targets and skins.
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Matrix


def import_joined(glb):
    """Import `glb` and join its meshes into one object in world space."""
    for stale in list(bpy.data.objects):  # the factory scene's cube, light and camera
        bpy.data.objects.remove(stale, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"{glb} holds no mesh")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    joined.data.transform(joined.matrix_world)
    joined.matrix_world = Matrix.Identity(4)
    return joined


def triangles(mesh):
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def main(plan):
    budget = int(plan["target_triangles"])
    if budget < 1:
        raise ValueError("target_triangles must be positive")
    obj = import_joined(plan["glb"])
    before = triangles(obj.data)
    if before > budget:
        # Collapse decimation lands within a few triangles of its ratio; aim a little under.
        modifier = obj.modifiers.new("reduce", "DECIMATE")
        modifier.ratio = 0.95 * budget / before
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    after = triangles(obj.data)
    out = Path(plan["out_glb"])
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        export_animations=False,
        export_morph=False,
        export_skins=False,
    )
    print("REDUCE", json.dumps(dict(before=before, after=after, target=budget)))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--plan", required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
        main(json.loads(Path(args.plan).read_text("utf-8")))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
