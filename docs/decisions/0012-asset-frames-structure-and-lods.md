# 0012. Asset frames, structure checks and LODs

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

ADR 0005 set one frame and four kinds. The final review found the contract too loose in three places. Generated bodies have no wheels (spec section 9.3), so a base car's lowest point is above the ground, and the check that it was within 0.03 m of y = 0 failed every real body. Required names could repeat, so a second `roof` would be hidden by a swap while the first was drawn. And nothing said how a build step learns a validated file's size, or what a LOD is.

## Decision

- **The ground check uses the wheel anchors.** The four anchors' y are 0.25 to 0.45 m and within 0.02 m of each other, and the body's lowest point is between −0.03 and 0.35 m. The mean-z check is unchanged. All of them report as `origin`.
- **Frames per kind:** base car, body module and interior are authored in the car frame. A product's pivot is its attach anchor. The data's `driverEyePoint` wins over the GLB's `camera_driver_eye` (spec section 7.5).
- **Required node, anchor and module names are unique** in the scene (`duplicate-name`).
- **Anchors are empty leaves:** no mesh on an anchor, and none below it.
- **An interior has exactly one root, named `interior`.**
- **A body module's lowest point is at least −0.03 m,** and a module node's mesh has at least one primitive.
- **One asset may cover several modules,** such as a CSL roof and trunk lid. It is shown once, and the 4.0 m cap applies to the whole asset.
- **`validateGlb` returns `stats: { triangles, bytes }`,** and `validate-asset --json` prints them. The Python `validate` stage saves that JSON as `<export>/<id>.validate.json` and lists it in its outputs. `StageResult` is unchanged.
- **LODs are separate files** named `<id>.lod<N>.glb`, each validated on its own.
- Triangles are counted per node use: a mesh two nodes use counts twice.

## Alternatives considered

- **Keep the lowest-point check and require wheels in the base car:** rejected. Wheels are separate products (spec section 9.3), and the configurator moves them.
- **Raycast tire contact:** rejected. The anchors already say where the wheel centers go, and a range check is simple and exact.
- **Let the first node of a duplicate name win:** rejected. The swap and the anchors would depend on traversal order.
- **A LOD as a node inside one file:** rejected. The Low preset should download less, not hide nodes.

## Consequences

- The wheel anchor range, 0.25 to 0.45 m, suits wheels up to about 20 inches. A larger car changes the contract.
- A LOD is checked against the full contract for its kind today, so a base car LOD under 100k triangles fails `triangles`. A budget for LODs is a Phase 1 decision and a `contract` PR.
- `stats.triangles` is `null` for a file that can't be read, so a consumer checks `ok` first.
- The validator still can't see that a module sits in its slot. The critic and `/lab` do.
