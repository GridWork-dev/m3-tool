# Decisions

Architecture decision records (ADRs): one short page for each choice that a later session would otherwise re-argue. Read the ADR before you reopen a decision. The [design spec](../superpowers/specs/2026-11-23-m3-tool-design.md) says what we are building, and these say why we built it this way and what that cost.

| ADR | Decision |
|---|---|
| [0001](0001-static-site-on-workers.md) | Astro static site on Workers static assets, deployed from GitHub Actions, with one API-minted Cloudflare token per purpose and a split TypeScript install |
| [0002](0002-threejs-webgpu-renderer.md) | three.js WebGPU renderer with a WebGL2 fallback and TSL, React Three Fiber 9, path-traced photo mode in its own canvas |
| [0003](0003-yaml-data-and-verification.md) | YAML data validated by Zod, date-only dates, source tiers, one meaning of "verified", CC BY-SA 4.0 data |
| [0004](0004-car-bodies-from-photos.md) | Car bodies generated from curated photos and gated by the Phase 0 spike, with licensed models as a fallback offered to the user |
| [0005](0005-asset-contract.md) | The 3D asset contract: one frame, four kinds, swappable body modules |
| [0006](0006-pipeline-python-validator-typescript.md) | Pipeline in Python with uv, asset validator in TypeScript |
| [0007](0007-agent-roles-and-review-gates.md) | Agent roles and model routing, review gates, zero required approvals (the bake-off part is superseded by 0013) |
| [0008](0008-no-commerce-no-logos.md) | No commerce, no store links, no logos |
| [0009](0009-citations-and-link-policy.md) | Citations render as text and link only to a short list of non-commercial hosts, and `check:links` parses HTML with parse5 |
| [0010](0010-safety-advice-evidence.md) | Safety advice needs a Tier 1 or Tier 2 source: a maintenance item always, a known issue's optional fix when present |
| [0011](0011-deploy-pipeline-hardening.md) | A secret-free build job and a deploy job that takes only static files from it, with its config from git and wrangler from a lockfile, no deploy for forks or bots, a smoke test that checks the deployed commit, SHA-pinned actions, and Renovate gates |
| [0012](0012-asset-frames-structure-and-lods.md) | The ground check through the wheel anchors, frames per kind, unique names, empty-leaf anchors, validation stats and LOD files |
| [0013](0013-model-choice-without-bake-off.md) | No model bake-off: research chooses the models, and OpenAI image generation runs on the subscription first |
| [0016](0016-optional-costs-interval-triggers-and-markets.md) | Maintenance cost and a fix's cost are optional, an interval may be a trigger such as Inspection II instead of a number, and a maintenance item names the markets its sources cover |

## Format

Each ADR is 60 lines at most, in this shape:

```
# NNNN. Title

- **Status:** Accepted YYYY-MM-DD
- **Date:** YYYY-MM-DD

## Context
## Decision
## Alternatives considered
## Consequences
```

Name the file `NNNN-short-slug.md`, with the next number. Numbers are never reused.

## Rules

- **Write what was decided, what was rejected and why, and what it costs.** Name the numbers and files, and don't invent a benchmark or a price.
- **Keep private details out.** These pages are public: no host names, local paths, account IDs, personal emails, token values or the name of the key-management token.
- **Don't edit an accepted ADR to change the decision.** Write a new ADR, and mark the old one `Superseded by NNNN` in its status line. Fixing a typo or adding a link is fine.
- **Write an ADR when a choice has a rejected alternative a reviewer would propose again.** Pure implementation detail belongs in the code and the standards.
- **The spike result is the next ADR.** Phase 0's go/no-go spike ends with a report and an ADR that records the outcome. The model bake-off was dropped ([0013](0013-model-choice-without-bake-off.md)).
