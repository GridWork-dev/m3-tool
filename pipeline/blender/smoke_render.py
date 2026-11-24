# pyright: basic, reportMissingImports=false
"""Render a GLB from a few cameras with the Workbench engine: `-- --plan <plan.json>`.

Plan: `glb`, `out_dir`, and `cameras_blender`, each `{location_blender, look_at_blender,
focal_mm}` in the Blender frame of the import. Writes one 256 x 256 `view_NN.png` per camera and
fails (exit 1) on no cameras or a PNG that is missing or empty. Workbench needs no GPU and no
lights, so this runs headless anywhere. A blank or black render is for a reader to judge.
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy
from mathutils import Vector

SIZE = 256


def main(plan):
    if not plan["cameras_blender"]:
        raise ValueError("cameras_blender is empty: nothing to render")
    out = Path(plan["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    for stale in list(bpy.data.objects):  # the factory scene's cube, light and camera
        bpy.data.objects.remove(stale, do_unlink=True)
    bpy.ops.import_scene.gltf(filepath=plan["glb"])

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "TEXTURE"
    scene.world = bpy.data.worlds.new("smoke")
    scene.world.color = (0.55, 0.55, 0.6)

    for index, camera in enumerate(plan["cameras_blender"]):
        data = bpy.data.cameras.new(f"cam{index}")
        data.lens = camera["focal_mm"]
        data.clip_start, data.clip_end = 0.01, 100_000.0
        obj = bpy.data.objects.new(f"cam{index}", data)
        scene.collection.objects.link(obj)
        obj.location = Vector(camera["location_blender"])
        toward = Vector(camera["look_at_blender"]) - obj.location
        obj.rotation_euler = toward.to_track_quat("-Z", "Y").to_euler()
        scene.camera = obj
        png = out / f"view_{index:02d}.png"
        png.unlink(missing_ok=True)  # a leftover from an earlier run must not pass as this one
        scene.render.filepath = str(png)
        bpy.ops.render.render(write_still=True)
        if not png.is_file() or png.stat().st_size == 0:
            raise RuntimeError(f"{png} was not written, or is empty")
        print("RENDER", png)


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--plan", required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
        main(json.loads(Path(args.plan).read_text("utf-8")))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
