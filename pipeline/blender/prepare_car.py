# pyright: basic, reportMissingImports=false
"""Put a generated car in the contract's pose and cut its wheels off: `-- --plan <plan.json>`.

Plan (every spatial number in the Blender frame, under a key ending `_blender`):
  glb, out_dir                  the generated file and where the results go
  orientation_blender           {up, nose}: axes of the import, like "-y" and "+z"
  scales_blender                TOTAL per-axis factors (x, y, z), import size to the data's
  translation_blender           (x, y, z) added last: car centered, lowest point at z = 0
  wheel_cylinders_blender       [{name, center_blender, radius, x_range_blender}]
Order: rotate to Z up and nose +Y, scale per axis, translate; delete the faces centered inside a
wheel cylinder and cap each hole. One scale only: a plan with `uniform_scale` is refused. Each
cylinder must cut a face, or the run fails naming the wheel. Writes `prepared.glb` (the exporter
turns Blender's frame into the contract's) and `prepared.npz` (Blender frame).
"""

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector


def orientation_matrix(up, nose):
    """The proper rotation taking the import's `up` axis to +Z and its `nose` axis to +Y."""
    u, n = (Vector([(c == a[1]) * (1 if a[0] == "+" else -1) for c in "xyz"]) for a in (up, nose))
    if abs(u.dot(n)) > 0.5:
        raise ValueError(f"up {up!r} and nose {nose!r} must be on different axes")
    return Matrix((n.cross(u), n, u))  # rows: new x, y, z


def import_joined(glb):
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


def remove_wheels(bm, cylinders):
    """Delete the faces centered inside a wheel cylinder, then cap each hole. Returns the counts."""
    # glTF splits vertices at seams and hard edges, which would make every seam a hole. Meters.
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    for edge in bm.edges:
        edge.tag = edge.is_boundary  # boundaries the car already had stay as they are
    doomed, per_wheel = [], [0] * len(cylinders)
    for face in bm.faces:
        c = face.calc_center_median()
        for i, cyl in enumerate(cylinders):
            x0, x1 = cyl["x_range_blender"]
            cx, cy, cz = cyl["center_blender"]
            if x0 <= c.x <= x1 and math.hypot(c.y - cy, c.z - cz) <= cyl["radius"]:
                doomed.append(face)
                per_wheel[i] += 1
                break
    for cyl, count in zip(cylinders, per_wheel, strict=True):
        if count == 0:  # a cut that misses leaves the wheel on and writes a valid file
            raise RuntimeError(
                f"wheel cylinder {cyl.get('name', cyl['center_blender'])} cut no face"
            )
    bmesh.ops.delete(bm, geom=doomed, context="FACES")
    created = 0
    for hole in components([e for e in bm.edges if e.is_boundary and not e.tag]):
        filled = bmesh.ops.triangle_fill(bm, use_beauty=True, edges=hole, normal=(0, 0, 0))
        created += sum(isinstance(item, bmesh.types.BMFace) for item in filled["geom"])
    open_edges = sum(1 for e in bm.edges if e.is_boundary and not e.tag)
    if open_edges:
        raise RuntimeError(f"{open_edges} edges of the wheel wells are still open after capping")
    return len(doomed), created


def components(edges):
    """Group edges that share vertices: one group per hole."""
    todo, groups = set(edges), []
    while todo:
        group, stack = [], [todo.pop()]
        while stack:
            edge = stack.pop()
            group.append(edge)
            linked = {other for vert in edge.verts for other in vert.link_edges} & todo
            todo -= linked
            stack.extend(linked)
        groups.append(group)
    return groups


def triangles(mesh):
    mesh.calc_loop_triangles()
    return len(mesh.loop_triangles)


def save_arrays(path, mesh):
    verts = np.empty(len(mesh.vertices) * 3, dtype=np.float32)
    mesh.vertices.foreach_get("co", verts)
    faces = np.empty(triangles(mesh) * 3, dtype=np.int32)
    mesh.loop_triangles.foreach_get("vertices", faces)
    np.savez_compressed(path, vertices=verts.reshape(-1, 3), faces=faces.reshape(-1, 3))


def main(plan):
    if "uniform_scale" in plan:
        raise ValueError("uniform_scale is gone: put the total per-axis factors in scales_blender")
    scales = plan["scales_blender"]
    if min(scales) <= 0:
        raise ValueError("scales must be positive")
    out = Path(plan["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    obj = import_joined(plan["glb"])
    rotation = orientation_matrix(**plan["orientation_blender"]).to_4x4()
    shift = Matrix.Translation(Vector(plan["translation_blender"]))
    obj.data.transform(shift @ Matrix.Diagonal(Vector((*scales, 1.0))) @ rotation)
    before = triangles(obj.data)
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    removed, capped = remove_wheels(bm, plan["wheel_cylinders_blender"])
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    after = triangles(obj.data)
    save_arrays(out / "prepared.npz", obj.data)
    bpy.ops.export_scene.gltf(filepath=str(out / "prepared.glb"), export_format="GLB")
    print("PREPARE", json.dumps(dict(before=before, removed=removed, capped=capped, after=after)))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--plan", required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
        main(json.loads(Path(args.plan).read_text("utf-8")))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
