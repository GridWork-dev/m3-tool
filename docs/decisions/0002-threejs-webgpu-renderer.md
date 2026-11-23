# 0002. three.js with WebGPU, a WebGL2 fallback and TSL

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

The goal is medium photoreal 3D that runs in a browser: car paint with a clear coat, an interior seen through the glass, a driver's-seat camera, selectable quality and a photo mode. WebGPU support has gaps, so some users have a device that can't run it. A phone must still be able to use the build sheet, so the text tool works without 3D (an anti-goal if it doesn't).

The configurator is one React island on `/[gen]/build`, and it loads 3D lazily.

## Decision

- **Renderer:** three.js `WebGPURenderer`. It falls back to WebGL2 on its own. Materials are written as TSL node materials, so one definition serves both backends. The checked version is three 0.187.0.
- **React binding:** React Three Fiber 9 (9.8.2) with drei 10.7.9 now. Move to R3F v10 once it reaches beta, not before.
- **Quality presets,** picked from what the device can do and switchable by hand:
  - **Low:** WebGL2, environment-map reflections, a baked contact shadow, no post-processing. Dark glass, no interior, though the driver's-seat view loads it on demand.
  - **Medium (default):** WebGPU, clear-coat paint with metallic flake in TSL, a studio HDRI, soft shadows, ambient occlusion, anti-aliasing and the interior visible through the glass.
  - **High:** Medium plus screen-space reflections, higher-resolution shadows and depth of field.
  - **Photo mode:** progressive path tracing with three-gpu-pathtracer, which supports clear coat. It produces a downloadable still image.
- **Photo mode runs in its own canvas.** three-gpu-pathtracer is WebGL-based, so it can't share the WebGPU canvas.
- **Paint and glass are parameters.** Paint is a parameter on the `paint` material and window tint is one on `glass`. Both names are part of the asset contract (ADR 0005).
- `three`, `@react-three/*` and the other 3D packages are installed by the first task that uses them, at exact versions.

## Alternatives considered

- **SvelteKit with Threlte:** a smaller 3D ecosystem, and agents know React Three Fiber better.
- **R3F v10 now:** rejected until it reaches beta.
- **WebGPU only:** rejected. Gaps in WebGPU support would leave a blank canvas for some users. The automatic WebGL2 fallback, the Low preset and a text tool that works without 3D are the answer to that risk.
- **Photo mode in the main canvas:** not possible, because the path tracer is WebGL-based. Hence the second canvas.

## Consequences

- Two render paths must work: WebGPU for Medium and High, WebGL2 for Low. A TSL material that works on one backend and not the other is a bug.
- CI has no GPU, so visual regression renders with software WebGL. A Mac script (`tools/shoot`) renders with the real GPU (WebGPU) for review. Visual baselines arrive in Phase 1, with the configurator.
- The paint is checked against the Khronos Clear Coat Car Paint sample model.
- Photo mode costs a second canvas, with its own WebGL path tracer next to the main renderer.
- The configurator renders only on the client (`client:only="react"`). The page around it, and the build sheet, work without it.
- Post-processing nodes per preset, LOD counts and the gyroscope details for the driver's-seat camera are left to the builder (spec section 17).
