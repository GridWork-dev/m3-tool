# pyright: basic, reportMissingImports=false
"""Build the fixture car that stands in for a generated one: `-- --out <car.glb>`.

A coupe-shaped box body with four cylinder wheels, 4.40 x 1.80 x 1.40 m (length, width, height),
rotated so that its up is -Y and its nose +Z and scaled to centimeters, as a generated mesh
arrives. Reaching the E46 data takes total factors of 0.98889 on width, 1.02091 on length and 0.98
on height. Each wheel is round, 64-sided and at the data's tire radius after those factors, with
its center on the data's wheel anchor, the case a cut at 0.98 x the radius missed. The wheels
overlap the body floor, which `prepare_car.py` caps once they are gone.
"""

import argparse
import math
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Vector

# Body: (name, low corner, high corner, cuts). Blender frame before the rotation: x width,
# y length with the nose at +y, z up. The cabin sits rearward (toward -y) like a coupe's.
BOXES = (
    ("floor_and_sills", (-0.90, -2.20, 0.12), (0.90, 2.20, 0.85), 16),
    ("cabin", (-0.70, -1.30, 0.85), (0.70, 0.50, 1.40), 8),
    ("skid", (-0.50, -1.00, 0.00), (0.50, 1.00, 0.12), 0),
)
# The scale prepare_car.py's per-axis factors end up applying to a fixture axis (data / fixture
# size: width 1.78 / 1.80, length 4.492 / 4.40, height 1.372 / 1.40), so wheels built with its
# inverse come out round, at the data's tire radius, after the corrections.
POST = (1.78 / 1.80, 4.492 / 4.40, 1.372 / 1.40)
# Wheels: (anchor x, anchor y along the length with the nose at +y, tire radius), in meters of the
# data. Each is 64-sided, as a generated tire is, and 0.20 m wide. Its center is one radius up.
WHEEL_WIDTH, WHEEL_SIDES = 0.20, 64
WHEELS = {
    "wheel_FL": (-0.754, -1.3655, 0.32985),
    "wheel_FR": (0.754, -1.3655, 0.32985),
    "wheel_RL": (-0.7625, 1.3655, 0.3306),
    "wheel_RR": (0.7625, 1.3655, 0.3306),
}
# Rotation of the finished car: +90 degrees about X turns up (+z) into -y and the nose (+y) into +z.
SPIN = Matrix.Rotation(math.radians(90), 4, "X")
CENTIMETERS = 100.0


def add_box(bm, low, high, cuts):
    cube = bmesh.ops.create_cube(bm, size=2.0)
    for vert in cube["verts"]:
        vert.co = Vector(
            tuple(low[i] + (vert.co[i] + 1.0) / 2.0 * (high[i] - low[i]) for i in range(3))
        )
    if cuts:
        edges = {e for v in cube["verts"] for e in v.link_edges}
        bmesh.ops.subdivide_edges(bm, edges=list(edges), cuts=cuts, use_grid_fill=True)


def make_object(name, bm, material):
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(material)
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def main(out):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    paint, tire = material("paint", (0.6, 0.1, 0.1, 1)), material("tire", (0.05, 0.05, 0.05, 1))

    bm = bmesh.new()
    for _name, low, high, cuts in BOXES:
        add_box(bm, low, high, cuts)
    objects = [make_object("body", bm, paint)]
    for name, (ax, ay, radius) in WHEELS.items():
        bm = bmesh.new()
        center = Vector((ax / POST[0], ay / POST[1], radius / POST[2]))
        undo = Matrix.Diagonal(Vector((1 / POST[0], 1 / POST[1], 1 / POST[2], 1.0)))
        axle_to_x = Matrix.Translation(center) @ undo @ Matrix.Rotation(math.radians(90), 4, "Y")
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=WHEEL_SIDES,
            radius1=radius,
            radius2=radius,
            depth=WHEEL_WIDTH,
            matrix=axle_to_x,
        )
        objects.append(make_object(name, bm, tire))
    for obj in objects:
        obj.data.transform(Matrix.Scale(CENTIMETERS, 4) @ SPIN)  # bake: no node transform left
    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_apply=True)
    counts = {o.name: len(o.data.polygons) for o in objects}
    wheels = sum(n for name, n in counts.items() if name.startswith("wheel_"))
    print(f"FIXTURE wrote {out}: {sum(counts.values())} triangles, {wheels} of them wheels")


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--out", required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
        main(args.out)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
