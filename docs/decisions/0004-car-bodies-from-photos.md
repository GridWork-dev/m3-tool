# 0004. Car bodies generated from curated photos

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

The tool needs a medium photoreal body for each generation, starting with the E46 coupe. There is no access to a real E46, so online photos are the only reference. Generators return one fused mesh with lighting and paint baked in, so it has to be split and re-materialed. Generic generators are still inconsistent on cars, and with no walk-around set of one car, matched views are hard to get. Paid calls need a session cap and a ledger row (`docs/spend-ledger.md`).

## Decision

- **Bodies are AI-generated from curated online photos plus a description,** then cleaned up, split and re-materialed by scripts. This was the user's pick.
- **A reference view-synthesis step makes matched views.** An image model renders clean front, side, rear and two three-quarter views of one car from the best real set. `gpt-image-2.6-sunburst` is the first choice. It is A/B tested against `gemini-nano-banana-2.1` through OpenRouter.
- **Three guards, all required.** (1) A proportion check: length, wheelbase and height ratios from the side silhouette are within 2% of the data dimensions. (2) A vision critic compares the views against the real photos. (3) The user approves the set.
- **Synthesized views are generator inputs only.** Scoring compares against real photos only. Which real photos fed which view is recorded.
- **Generators are reached through fal** with one key (`M3_FAL_KEY`): Rodin 2.5, Hunyuan 3.1 Pro, Tripo H3.1 and Meshy 7.1. Tripo and Meshy also have direct keys. Rodin 2.5 is the main generator, and it takes up to 5 views.
- **Hunyuan is experiment-only** because of its license. The terms the spec cites are the Hunyuan3D 2.x community license, which excludes the EU, UK and South Korea. 3.1 Pro is treated the same until its own terms are read. It never runs on machines in the EU, UK or South Korea.
- **The Phase 0 spike gates this approach** (spec section 9.9). If it fails, licensed marketplace models are a fallback that is offered to the user, never switched to automatically.
- **The Phase 0 spike cap is $50 of paid 3D generation,** logged in the ledger. View synthesis comes out of the same cap.

## Alternatives considered

- **Buying licensed marketplace models.** Highest and most predictable quality, but it costs money per generation, and each license needs checking for in-browser use. This is the fallback, not the plan.
- **An LLM hand-modeling the body in Blender.** Rejected. In BlenderGym, top vision models struggle with tasks that are easy for humans. 2026 Blender benchmarks show realism is the weakest dimension, and reconstruction from references is weaker than generation from text. Agents model only parametric parts.
- **A self-hosted GPU for the spike.** Rejected. APIs are cheaper at this volume, and the Hunyuan3D 2.x license excludes the EU, UK and South Korea.
- **Scoring against synthesized views too.** Rejected. Scoring uses real photos only.
- **Hunyuan as the main generator.** Rejected for its license.

## Consequences

- Agents build the photo tooling and the user runs the collection and chooses the sources. Reference photos and the manifest stay private (R2 `m3-tool-refs` plus a local cache), never in the repo.
- Each generator's terms decide whether its output can be published. Check them before anything reaches `public/` or the models bucket. If they don't allow it, the asset stays private.
- Generated meshes need splitting into `body`, `glass`, the lights, `trim`, `grille`, `undercarriage` and the four body modules. Several methods are compared in the spike, and the spike decides which wins.
- Interiors are generated component by component, because today's generators build objects, not enclosed spaces.
- The risks stay open until the spike reports: a body short of medium photoreal, an interior that looks wrong from the driver's seat, and unreliable splitting.
- A fail brings the user options part by part: buy licensed bodies or interiors for some or all generations, or lower the target for that part.
