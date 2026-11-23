# 0005. The 3D asset contract and swappable body modules

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

Two lanes build against one set of GLB rules: the 3D lane makes models, and the app lane loads and places them. Generated and exported models fail in predictable ways: exported in centimeters, Z-up, facing the wrong way, anchors pruned away, or a texture too large for a phone. The configurator also has to show factory variants (a CSL roof and trunk lid, a sunroof, US and Euro details) and aftermarket bumpers and trunk lids on one base car. The user decided that factory variants render in v1.

## Decision

- **One frame for every asset:** meters, Y up, nose toward −Z, origin on the ground under the middle of the wheelbase.
- **Four kinds:** `base-car`, `interior`, `product` and `body-module`. Each kind has its own requirements and budget. The names and numbers are in [the 3D asset standard](../standards/3d-assets.md) and `src/lib/asset-contract.ts`. The budgets are proposed.
- **The base car carries swappable body modules:** `bumper_front`, `bumper_rear`, `trunk_lid` and `roof`. Each is a mesh node of the base car, named exactly like the module. A module node is not an anchor.
- **The `body-module` kind is a replacement,** authored in the car frame: one root node, with its origin at the car origin and not at an anchor pivot. The configurator hides the base car's node of that name and shows the replacement at the car origin.
- **One swap mechanism for both uses.** Factory variants name their module assets in `render.modules`. Aftermarket body parts list the modules they take over in `model.replaces`. A CSL trunk lid and an aftermarket trunk lid are the same kind of asset.
- **GPU instancing and Draco are rejected.** The validator fails `EXT_mesh_gpu_instancing` and `KHR_draco_mesh_compression` with `unsupported-extension`. Geometry is meshopt-compressed and textures are KTX2.
- **Anchors must survive `prune`.** An anchor is an empty leaf node, and a default `prune` deletes those. The export stage calls `prune({ keepLeaves: true })` and is built from the individual glTF-Transform functions, not `optimize`.
- **Changes go through a `contract` PR.** `src/lib/asset-contract.ts` and `docs/standards/3d-assets.md` change only in a dedicated PR that both lanes rebase onto.

## Alternatives considered

- **Separate mechanisms for factory variants and aftermarket parts:** rejected. They share the one swap.
- **A module authored at an anchor pivot, like a product:** rejected. A module belongs where the stock part was, so it is authored in the car frame and placed at 0, 0, 0.
- **GPU instancing:** the triangle count and bounding box count each node's mesh once, so instancing could draw far more triangles than the budget allows.
- **Draco:** not supported. Meshopt is the compression.

## Consequences

- Every base car needs the four module meshes. A missing node or a node with no mesh is `missing-node`. The cleanup stage splits them out of the generated mesh.
- The swap must hide the base module, so the car never shows two roofs. Removing the swap shows the base module again.
- The validator can't check that a module sits in its slot or that a model has no logo. The vision critic and the review in `/lab` check both.
- Which part wins when two build parts replace the same module, or a build part and the variant's factory module, is not decided. It is an open item for Phase 2 (spec section 16).
- One body-module asset may cover several modules, such as a CSL roof and trunk lid. Its root then spans them, and the validator's 4.0 m ceiling on its largest dimension still applies, so a front and rear bumper pair is too long for one asset. An asset listed under several module keys is shown once.
- Export can't use `gltf-transform optimize`, which has no keep-leaves option. Calling `flatten()` or `join()` also needs `cleanup: false`.
