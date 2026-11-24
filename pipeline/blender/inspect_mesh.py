# pyright: basic, reportMissingImports=false
"""Measure a generated GLB as imported: `-- --plan <plan.json>`.

Plan: `glb` (the file), `out_dir`, `proxy_triangles` (the proxy's triangle budget). Nothing is
rotated or scaled, so every number is in the Blender frame of the import. Writes to `out_dir`:
`raw.json` (`triangles`, `vertices`, `bbox_min_blender`, `bbox_max_blender`, `proxy_triangles`)
and `raw.npz` (`vertices` float32 Nx3, `faces` int32 Mx3 of a copy decimated to the budget).
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix


def import_joined(glb):
    """Import `glb` and join its meshes into one object in world space."""
    for stale in list(bpy.data.objects):  # the factory scene's cube, light and camera
        bpy.data.objects.remove(stale, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    scene = bpy.context.scene
    meshes = [o for o in scene.objects if o.type == "MESH"]
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


def arrays(mesh):
    """Vertices (Nx3) and triangles (Mx3) of `mesh`."""
    verts = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts)
    mesh.calc_loop_triangles()
    faces = np.empty(len(mesh.loop_triangles) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", faces)
    return verts.reshape(-1, 3), faces.reshape(-1, 3)


def main(plan):
    out = Path(plan["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    obj = import_joined(plan["glb"])
    vertices, faces = arrays(obj.data)
    budget = int(plan["proxy_triangles"])
    proxy_vertices, proxy_faces = vertices, faces
    if len(faces) > budget:
        # Collapse decimation lands within a few triangles of its ratio; aim a little under.
        modifier = obj.modifiers.new("proxy", "DECIMATE")
        modifier.ratio = 0.95 * budget / len(faces)
        evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
        proxy_vertices, proxy_faces = arrays(evaluated.to_mesh())
    np.savez_compressed(out / "raw.npz", vertices=proxy_vertices, faces=proxy_faces)
    raw = {
        "triangles": int(len(faces)),
        "vertices": int(len(vertices)),
        "bbox_min_blender": [float(v) for v in vertices.min(axis=0)],
        "bbox_max_blender": [float(v) for v in vertices.max(axis=0)],
        "proxy_triangles": int(len(proxy_faces)),
    }
    (out / "raw.json").write_text(json.dumps(raw, indent=2) + "\n", "utf-8")
    print("INSPECT", json.dumps(raw))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    try:
        main(json.loads(Path(args.plan).read_text("utf-8")))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
