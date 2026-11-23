# 0006. Pipeline in Python, asset validator in TypeScript

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

The site is TypeScript. The asset pipeline drives headless Blender (`bpy`) and image tools such as background removal and perceptual hashing, which are Python-native. The asset contract has to be checked in two places: by the pipeline after export, and by contributors and CI through `pnpm validate-asset`. The contract's module list also feeds the data schemas, because a variant's `render.modules` accepts only those four keys.

Every change to a model has to be a script, so any asset can be rebuilt and an agent can iterate on it safely. Blender isn't in CI for v1: 3D assets are built on the Mac.

## Decision

- **The pipeline is Python with uv,** in `pipeline/`. Python is 3.14, not 3.15: wheel coverage, since onnxruntime and similar packages land later. Typer provides the CLI, and ruff, strict pyright and pytest check it.
- **A stage is one function** that takes an `AssetSpec` and `Settings` and returns a `StageResult`. It registers itself with `@register("<name>")`. `pipeline run <asset> --stage <name>` runs one.
- **The asset validator is TypeScript,** in `src/lib/asset-validate.ts`, built on glTF-Transform and the Khronos glTF validator. The contract lives in `src/lib/asset-contract.ts`.
- **One source of truth for the contract.** The Python `validate` stage runs `tools/validate-asset.ts` through node, instead of reimplementing the checks.
- **Side effects sit behind injectable functions.** A subprocess, a network call or a write outside the work directory goes in a small module-level function that tests replace. No test starts Blender or node, or touches the network.
- **Each side has its own check command,** and the root `pnpm check` runs both: `pnpm check:site`, then `pnpm check:pipeline`.

## Alternatives considered

- **The whole pipeline in TypeScript:** rejected. Blender scripting and the image tools are Python-native.
- **The validator in Python:** rejected. It would copy the contract into a second language, and the two copies would drift. The site's schemas already import the module list from the TypeScript contract.
- **Python 3.15:** rejected for now, for the wheel coverage above.
- **Hand edits in Blender:** rejected. Anything not captured in a script can't be rebuilt.
- **blender-mcp as a way to change models:** optional, for inspecting a scene only. Changes still land as scripts.

## Consequences

- Two toolchains are pinned in `mise.toml`: node and pnpm for the site, python and uv for the pipeline. Run `pnpm install` and `uv sync --project pipeline` in every worktree.
- The `validate` stage needs node at run time, so its tests replace the subprocess call.
- A change to the contract is a change in TypeScript, and the Python side picks it up for free. It still goes through a `contract` PR.
- The stages from the spec are `refs`, `generate`, `cleanup`, `assemble`, `product`, `export`, `validate`, `score` and `publish`. `pipeline stages` lists the ones that exist.
- Blender runs only on the Mac, so CI covers the pure functions and the stages with their side effects replaced.
- `publish` uploads content-hashed GLBs to the public bucket, updates `src/assets/manifest.json` and opens a PR.
