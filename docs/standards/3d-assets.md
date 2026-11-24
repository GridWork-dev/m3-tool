# 3D asset standard

Every 3D model the site uses is a GLB that passes this contract. The contract values live in [`src/lib/asset-contract.ts`](../../src/lib/asset-contract.ts) and the checks in [`src/lib/asset-validate.ts`](../../src/lib/asset-validate.ts). This page is the rulebook for people and agents who make models. It starts with spec section 9.6 as written, then says how each rule is measured.

## The contract (spec section 9.6)

**Units and axes:** meters, Y up, nose toward −Z, origin on the ground under the middle of the wheelbase.

**Base car**
- Nodes: `body`, plus one mesh node for each body module: `bumper_front`, `bumper_rear`, `trunk_lid`, `roof` (see "Body modules" below).
- Anchors:
  - Wheels: `wheel_FL`, `wheel_FR`, `wheel_RL`, `wheel_RR`.
  - Aero and exhaust: `mount_front_lip`, `mount_trunk`, `mount_wing`, `mount_exhaust_L`, `mount_exhaust_R`.
  - Interior: `mount_interior`.
- Materials: `paint`, `glass`, `trim`, `lights_front`, `lights_rear`.

**Interior**
- Nodes: `interior` (the one root), `cabin_shell`, `dash`, `console`, `door_L`, `door_R`, `seat_driver`, `seat_passenger`, `steering_wheel`.
- Anchors: `mount_seat_L`, `mount_seat_R`, `mount_steering`, `camera_driver_eye`.

**Products:** one root node, with a pivot that matches the anchor they attach to.

**Body modules:** one root node, authored in the base car's frame (see "Body modules" below).

**Budgets (proposed)**

| Asset | Triangles | File size | Textures |
|---|---|---|---|
| Base car | 100k–200k | ≤ 8 MB | ≤ 2K, 4K for body detail maps |
| Interior | ≤ 150k | ≤ 6 MB | 4K for dash and gauges, so the driver's-seat view stays sharp |
| One product | ≤ 30k | ≤ 1 MB | ≤ 2K |
| One body module | ≤ 30k | ≤ 1 MB | ≤ 2K |

"MB" means 1,000,000 bytes. The kinds are `base-car`, `interior`, `product` and `body-module`. A body module has a product's budgets. The base car's own module meshes count toward the base car's triangles and file size.

## Frames, names and LODs

**Frames per kind.** Every asset is in meters with Y up and the nose toward −Z. What the origin means depends on the kind:

| Kind | Frame | Origin |
|---|---|---|
| `base-car` | The car frame | On the ground, under the middle of the wheelbase |
| `body-module` | The car frame | The car origin, so it sits in its slot when placed at 0, 0, 0 |
| `interior` | The car frame | The car origin, so the cabin sits where it belongs in the car |
| `product` | Its own | Its attach anchor: the product's pivot is the point where it mounts |

**The eye point.** The interior's `camera_driver_eye` anchor marks where the model puts the driver's eye. The driver's-seat camera is placed at the data's `driverEyePoint` (spec section 7.5), and when the two disagree, the data wins. The data's eye point is the one to correct.

**Names are unique.** Each required node, anchor and module name appears exactly once in the scene. A second `roof` is an error (`duplicate-name`), because a swap would hide one and still draw the other. Names the contract doesn't require may repeat.

**Anchors are empty leaves.** An anchor has no mesh, and nothing below it has one. A mesh under an anchor would move, hide or double up with the product that mounts there.

**LODs are separate files.** A lower level of detail is its own GLB, named `<id>.lod<N>.glb` (`e46-coupe-body.lod1.glb`). The main file, `<id>.glb`, is level 0. Each file is validated on its own, as its kind, with the same checks. The triangle range in the budgets table is the main file's, so a base car LOD under 100k triangles fails `triangles` today. The pipeline's `validate` stage checks only `<id>.glb`, so run `pnpm validate-asset` on a LOD by hand. Giving LODs their own budget is a Phase 1 decision (spec section 17 leaves the LOD counts to the builder), and it changes the contract, so it goes through a `contract` PR.

## Body modules

A body module is a part of the base car that another model can replace: `bumper_front`, `bumper_rear`, `trunk_lid` and `roof`. The names are exact, and the list lives in `BODY_MODULES` in [`src/lib/asset-contract.ts`](../../src/lib/asset-contract.ts).

Two things use the same swap:
- **Factory variants.** A CSL's carbon roof, ducktail trunk lid and single-intake bumper, a sunroof, and the US and Euro body details. A variant names its module assets in `render.modules`.
- **Aftermarket body parts.** A bumper or trunk lid that replaces the stock one. The part names the modules it takes over in `model.replaces`.

Both fields are in [the data standard](data.md#body-module-swaps).

**The base car carries every module.** Each module is a node of the base car named exactly like the module, and each node carries a mesh. The validator reports a missing node, or a node with no mesh, as `missing-node`. A module node isn't an anchor: anchors are empty nodes, and a module node is the opposite.

**The `body-module` kind is a replacement.** It's a GLB with one root node, in the base car's frame: its origin is the car origin, so the module sits where it belongs when it's placed at 0, 0, 0. That differs from a product, whose pivot matches an anchor. The root node's name isn't checked. The validator checks the budgets, the units (0.05–4.0 m on the largest dimension), the one root, and that the lowest point is no lower than −0.03 m, which catches a module authored at the wrong height. It can't check that the module sits in its slot, so the vision critic and the review in `/lab` look at that.

**How a swap works.** The configurator hides the base car's module node and shows the replacement asset at the car origin. The base module isn't drawn while the swap is active, so the car never shows two roofs. Removing the swap shows the base module again.

**One asset may cover several modules.** A CSL's roof and trunk lid can be one `body-module` asset: the variant names that id under both `roof` and `trunk_lid`, and a part lists both in `replaces`. The asset has one root node in the car frame, and it is shown once, however many modules name it. The 4.0 m cap on the largest dimension still applies to the whole asset, so a front and rear bumper pair is too long for one. Each module node it covers is hidden on the base car.

**How the base car gets its modules.** The cleanup stage splits the module nodes out of the generated mesh (spec section 9.3), along with `body`, `glass`, the lights, `trim`, `grille` and `undercarriage`.

## How each check is measured

`validate` reports each failure as an issue with a code, a severity and a message. Any `error` fails the asset. A `warning` doesn't.

| Code | What it checks |
|---|---|
| `khronos` | The Khronos glTF validator reports no errors. One issue quotes the first 5 messages and counts the rest. A file that can't be read at all is reported under this code too. |
| `missing-node` | Every required node exists. A base car's module nodes (`bumper_front`, `bumper_rear`, `trunk_lid`, `roof`) must also carry a mesh with at least one primitive. |
| `missing-anchor` | Every required anchor exists, and is an empty leaf: no mesh on it, and no mesh on anything below it. |
| `duplicate-name` | Each required node, anchor and module name is used by exactly one node in the scene. |
| `missing-material` | Every required material is used by a mesh in the scene. |
| `triangles` | The triangle count is inside the range for the kind. |
| `bytes` | The file is within the size budget for the kind. |
| `texture-size` | Every texture's longest side is within the limit. |
| `units` | The asset is the size of its real-world object, in meters. |
| `orientation` | The wheel anchors sit where Y up and a −Z nose put them. |
| `origin` | A base car's origin is under the middle of the wheelbase, its wheel anchors stand at wheel-center height, and its body sits just above the ground. A body module is not below the ground. |
| `root-count` | A product, a body module or an interior has exactly one root node, and an interior's is named `interior`. |
| `unsupported-extension` | The file doesn't use `EXT_mesh_gpu_instancing` or `KHR_draco_mesh_compression`. |

The details:

- **Names** match exactly, with case, anywhere in the scene graph. The scene is the file's default scene, which is the one a viewer loads. An anchor is a node with no mesh, so a mesh named `wheel_FL` doesn't count. A required name used by two nodes is `duplicate-name`, reported once with the count, and the checks for that name stop there. Names that the contract doesn't require may repeat.
- **Materials** are matched by name. A material counts only when a mesh in the scene uses it, because the configurator finds `paint` and `glass` through the meshes it draws.
- **Triangles** are counted per node use: a mesh that two nodes use counts twice. A triangle list counts its index count ÷ 3 (or its position count ÷ 3 when it has no indices), and strips and fans count n − 2. Points and lines aren't counted and give a `triangles` warning.
- **Texture size** is read from the image data: PNG, JPEG, WebP and KTX2. A base car's texture may be 4096 only when `paint` is the one material using it. A texture that any other material shares is held to 2048. An unreadable texture is an error, because its size can't be checked.
- **Units:**
  - A base car's world bounding box is 3.0–6.0 m along Z and 0.9–2.0 m along Y.
  - An interior's, a product's or a body module's largest dimension is 0.05–4.0 m.
  - A model exported in centimeters (449 m long) or millimeters fails here.
- **Orientation** (base car): in world space, all of these hold.
  - `wheel_FL`: x < 0, z < 0.
  - `wheel_FR`: x > 0, z < 0.
  - `wheel_RL`: x < 0, z > 0.
  - `wheel_RR`: x > 0, z > 0.
  - Every wheel anchor has y > 0.

  A Z-up export, a car facing +Z, and a mirrored car all fail here.
- **Origin** (base car), and the ground:
  - The mean z of the 4 wheel anchors is within 2% of the wheelbase from 0, where wheelbase = mean rear z − mean front z.
  - The 4 wheel anchors' y are each 0.25–0.45 m, where the wheel centers are, and within 0.02 m of each other.
  - The lowest point of the geometry is between −0.03 m and 0.35 m.

  A generated body has no wheels (spec section 9.3), so it hangs a little above the ground, and a rule that put its lowest point at y = 0 would fail every one of them. The wheel anchors stand where the wheel centers go, and the body sits between a sunk body (below −0.03 m) and a floating one (above 0.35 m). The wheel check reports every anchor that is out of range in one issue, and the spread in another. Every limit passes at exactly its value.
- **Origin** (body module): the lowest point is at least −0.03 m. A module is authored in the car frame, so it can't sit under the ground.
- **Roots:** a product and a body module have exactly one root node, and so does an interior, which is named `interior`. An interior nested under a wrapper root fails.
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
| `kind` | `base-car`, `interior`, `product` or `body-module`. |
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
pnpm validate-asset <file.glb> --kind <base-car|interior|product|body-module> [--json]
pipeline run <asset> --stage validate        # run from pipeline/, with uv run
```

`pnpm validate-asset` prints one `ERROR <code>: <message>` or `WARNING <code>: <message>` line per issue, or `ok`. With `--json` it prints `{ "ok": true, "issues": [...], "stats": { "triangles": 120000, "bytes": 5242880 } }`. `stats.triangles` is the count the triangle budget uses, and is `null` when the file couldn't be read, so no count exists. `stats.bytes` is the size of the file that was checked. It exits 0 when the asset passes, 1 when there's an error, and 2 for a usage error such as a missing file or an unknown kind.

`pipeline run <asset> --stage validate` checks `<work_dir>/assets/<asset>/export/<asset>.glb` against the kind set for the asset in `pipeline/assets.toml`. If that file is missing, run `--stage export` first. The stage runs `node tools/validate-asset.ts` on that file, so the pipeline and `pnpm validate-asset` check the same contract. It saves the CLI's JSON, stats included, as `<work_dir>/assets/<asset>/export/<asset>.validate.json` and lists that path in the stage's outputs, whether the asset passed or not. That way the publish stage can take the manifest's triangle count and size from it instead of measuring again.
