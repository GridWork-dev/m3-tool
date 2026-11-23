# 3D asset standard

Every 3D model the site uses is a GLB that passes this contract. The contract values live in [`src/lib/asset-contract.ts`](../../src/lib/asset-contract.ts) and the checks in [`src/lib/asset-validate.ts`](../../src/lib/asset-validate.ts). This page is the rulebook for people and agents who make models. It starts with spec section 9.6 as written, then says how each rule is measured.

## The contract (spec section 9.6)

**Units and axes:** meters, Y up, nose toward −Z, origin on the ground under the middle of the wheelbase.

**Base car**
- Nodes: `body`.
- Anchors:
  - Wheels: `wheel_FL`, `wheel_FR`, `wheel_RL`, `wheel_RR`.
  - Aero and exhaust: `mount_front_lip`, `mount_trunk`, `mount_wing`, `mount_exhaust_L`, `mount_exhaust_R`.
  - Interior: `mount_interior`.
- Materials: `paint`, `glass`, `trim`, `lights_front`, `lights_rear`.

**Interior**
- Nodes: `interior` (root), `cabin_shell`, `dash`, `console`, `door_L`, `door_R`, `seat_driver`, `seat_passenger`, `steering_wheel`.
- Anchors: `mount_seat_L`, `mount_seat_R`, `mount_steering`, `camera_driver_eye`.

**Products:** one root node, with a pivot that matches the anchor they attach to.

**Budgets (proposed)**

| Asset | Triangles | File size | Textures |
|---|---|---|---|
| Base car | 100k–200k | ≤ 8 MB | ≤ 2K, 4K for body detail maps |
| Interior | ≤ 150k | ≤ 6 MB | 4K for dash and gauges, so the driver's-seat view stays sharp |
| One product | ≤ 30k | ≤ 1 MB | ≤ 2K |

"MB" means 1,000,000 bytes. The kinds are `base-car`, `interior` and `product`.

## How each check is measured

`validate` reports each failure as an issue with a code, a severity and a message. Any `error` fails the asset. A `warning` doesn't.

| Code | What it checks |
|---|---|
| `khronos` | The Khronos glTF validator reports no errors. One issue quotes the first 5 messages and counts the rest. A file that can't be read at all is reported under this code too. |
| `missing-node` | Every required node exists. |
| `missing-anchor` | Every required anchor exists, and has no mesh. |
| `missing-material` | Every required material is used by a mesh in the scene. |
| `triangles` | The triangle count is inside the range for the kind. |
| `bytes` | The file is within the size budget for the kind. |
| `texture-size` | Every texture's longest side is within the limit. |
| `units` | The asset is the size of its real-world object, in meters. |
| `orientation` | The wheel anchors sit where Y up and a −Z nose put them. |
| `origin` | The origin is under the middle of the wheelbase, on the ground. |
| `root-count` | A product has exactly one root node. |
| `unsupported-extension` | The file doesn't use `EXT_mesh_gpu_instancing` or `KHR_draco_mesh_compression`. |

The details:

- **Names** match exactly, with case, anywhere in the scene graph. The scene is the file's default scene, which is the one a viewer loads. An anchor is a node with no mesh, so a mesh named `wheel_FL` doesn't count.
- **Materials** are matched by name. A material counts only when a mesh in the scene uses it, because the configurator finds `paint` and `glass` through the meshes it draws.
- **Triangles** are counted per instance: a mesh that two nodes use counts twice. A triangle list counts its index count ÷ 3 (or its position count ÷ 3 when it has no indices), and strips and fans count n − 2. Points and lines aren't counted and give a `triangles` warning.
- **Texture size** is read from the image data: PNG, JPEG, WebP and KTX2. A base car's texture may be 4096 only when `paint` is the one material using it. A texture that any other material shares is held to 2048. An unreadable texture is an error, because its size can't be checked.
- **Units:**
  - A base car's world bounding box is 3.0–6.0 m along Z and 0.9–2.0 m along Y.
  - An interior's or a product's largest dimension is 0.05–4.0 m.
  - A model exported in centimeters (449 m long) or millimeters fails here.
- **Orientation** (base car): in world space, all of these hold.
  - `wheel_FL`: x < 0, z < 0.
  - `wheel_FR`: x > 0, z < 0.
  - `wheel_RL`: x < 0, z > 0.
  - `wheel_RR`: x > 0, z > 0.
  - Every wheel anchor has y > 0.

  A Z-up export, a car facing +Z, and a mirrored car all fail here.
- **Origin** (base car):
  - The mean z of the 4 wheel anchors is within 2% of the wheelbase from 0, where wheelbase = mean rear z − mean front z.
  - The bounding box's lowest point is within 0.03 m of y = 0.
- **File reading:** the validator reads GLBs the way the export stage writes them, with meshopt-compressed geometry and KTX2 textures.
- **Unsupported extensions:** a GLB that uses one of these fails with `unsupported-extension`.
  - `EXT_mesh_gpu_instancing`. The triangle count and bounding box cover each node's mesh once, so instancing could draw far more triangles than the budget allows. Re-export without instancing: `gltf-transform optimize --instance false`, or leave `instance()` out of the API pipeline. `optimize` turns instancing on by default once a mesh is used 5 times.
  - `KHR_draco_mesh_compression`. Draco compression isn't supported; re-export with meshopt.

## How models are made

**Every change is a script in `pipeline/`.** No unscripted Blender edits, so any asset can be rebuilt and an agent can iterate on it safely. If a model needs a fix, change the script that makes it and run the stage again.

**Keep the anchors when you prune.** glTF-Transform's `prune()` deletes empty leaf nodes by default, and an anchor is an empty leaf node, so a default prune removes every `wheel_*` and `mount_*`. The export stage must call `prune({ keepLeaves: true })`, or `gltf-transform prune --keep-leaves true` on the command line. `gltf-transform optimize` has no keep-leaves option, and `flatten()` and `join()` also remove empty leaf nodes unless you pass `cleanup: false`, so build the export from the individual functions rather than `optimize`.

**No logos, badges or roundels,** in meshes or in textures. That includes the roundel on the steering wheel and the gauges, and badges on the grille, wheel caps and trunk. The validator can't see them, so the vision critic and the human review in `/lab` check for them.

## The manifest and license metadata

`src/assets/manifest.json` maps each logical asset id to the GLB that was published. The publish stage writes it. `pnpm check:data` validates it against `AssetManifest` in [`src/lib/asset-manifest.ts`](../../src/lib/asset-manifest.ts).

```json
{
  "version": 1,
  "assets": {
    "e46-coupe-body": {
      "kind": "base-car",
      "url": "https://assets.example.com/e46-coupe-body.3f2a9c.glb",
      "sha256": "<64 lowercase hex characters>",
      "bytes": 5242880,
      "triangles": 150000,
      "license": "CC BY-SA 4.0",
      "sources": ["https://commons.wikimedia.org/wiki/File:Example.jpg"],
      "publishedAt": "2026-11-23"
    }
  }
}
```

| Field | Meaning |
|---|---|
| key | The asset id. Kebab-case, stable, never reused. It matches the id in `pipeline/assets.toml` and the ids the data files reference. |
| `kind` | `base-car`, `interior` or `product`. |
| `url` | An `https` URL of the content-hashed GLB in the public bucket, so a URL never changes what it serves. |
| `sha256` | The SHA-256 of the GLB, as 64 lowercase hex characters. |
| `bytes` | The GLB's size in bytes. Greater than 0. |
| `triangles` | The triangle count `validate` measured. A whole number, 0 or more. |
| `license` | The license the published GLB carries, by name, such as `CC BY-SA 4.0`. Never empty. |
| `sources` | Where the references came from, one string each: reference photo pages, product pages and tool names. |
| `publishedAt` | A calendar date, `YYYY-MM-DD`, with no time of day. |

The schema rejects keys it doesn't list. Record the license before you publish, from the license of every reference the model was built from.

## Running the checks

```sh
pnpm validate-asset <file.glb> --kind <base-car|interior|product> [--json]
pipeline run <asset> --stage validate        # run from pipeline/, with uv run
```

`pnpm validate-asset` prints one `ERROR <code>: <message>` or `WARNING <code>: <message>` line per issue, or `ok`. With `--json` it prints `{ "ok": true, "issues": [...] }`. It exits 0 when the asset passes, 1 when there's an error, and 2 for a usage error such as a missing file or an unknown kind.

`pipeline run <asset> --stage validate` checks `<work_dir>/assets/<asset>/export/<asset>.glb` against the kind set for the asset in `pipeline/assets.toml`. If that file is missing, run `--stage export` first. The stage runs `node tools/validate-asset.ts` on that file, so the pipeline and `pnpm validate-asset` check the same contract.
