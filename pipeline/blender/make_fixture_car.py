# pyright: basic, reportMissingImports=false
"""Build the fixture car that stands in for a generated one: `-- --out <car.glb>`.

A coupe-shaped box body with four cylinder wheels, 4.40 x 1.80 x 1.40 m (length, width, height),
rotated so that its up is -Y and its nose +Z and scaled to centimeters, as a generated mesh
arrives. Reaching the E46 data takes a uniform 1.0209, then 0.9599 on height and 0.9686 on width.
Wheel centers sit where the data puts the wheel anchors (after those corrections). The body's
lowest point is a skid plate, so the wheels stay clear of it, and the wheels cut the body floor,
which is what `prepare_car.py` caps.
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
# Wheel centers: (x, y, z) as pre-correction meters, radius and width.
WHEEL_RADIUS, WHEEL_WIDTH, WHEEL_SIDES = 0.30, 0.20, 16
WHEELS = {
    "wheel_FL": (-0.7625, -1.3375, 0.33658),
    "wheel_FR": (0.7625, -1.3375, 0.33658),
    "wheel_RL": (-0.7710, 1.3375, 0.33735),
    "wheel_RR": (0.7710, 1.3375, 0.33735),
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
    for name, center in WHEELS.items():
        bm = bmesh.new()
        axle_to_x = Matrix.Translation(center) @ Matrix.Rotation(math.radians(90), 4, "Y")
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=WHEEL_SIDES,
            radius1=WHEEL_RADIUS,
            radius2=WHEEL_RADIUS,
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    try:
        main(args.out)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
