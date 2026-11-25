# pyright: basic, reportMissingImports=false
"""Convert an FBX to a GLB, keeping its objects as they are: `-- --plan <plan.json>`.

Plan: `input` (the FBX) and `out_glb` (where to write). Used for a segmented result that comes
back as FBX only, so that nothing downstream reads FBX. Objects keep their names (a split's parts
are separate objects), and nothing is joined, rotated or scaled beyond what the importer and the
glTF exporter do for the axes. The exporter leaves out animations, morph targets and skins.
Prints `CONVERT {...}`.
"""

import argparse
import json
import sys
import traceback
from pathlib import Path

import bpy


def main(plan):
    for stale in list(bpy.data.objects):  # the factory scene's cube, light and camera
        bpy.data.objects.remove(stale, do_unlink=True)
    bpy.ops.import_scene.fbx(filepath=plan["input"])
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"{plan['input']} holds no mesh")
    out = Path(plan["out_glb"])
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        export_animations=False,
        export_morph=False,
        export_skins=False,
    )
    print("CONVERT", json.dumps(dict(meshes=len(meshes), names=sorted(o.name for o in meshes))))


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--plan", required=True)
        args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
        main(json.loads(Path(args.plan).read_text("utf-8")))
    except Exception:
        traceback.print_exc()
        sys.exit(1)
