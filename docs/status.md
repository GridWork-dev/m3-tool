# Repository state and next work

Snapshot taken 2026-11-25. The first E46 factory spec page is live. The 3D spike is preparing conditioning images for the first generator comparison. Catalog coverage, model quality and public-beta readiness have separate exit criteria.

## What an owner can use

The [E46 factory reference](https://m3-tool.broken-wood-97a9.workers.dev/e46/) presents dimensions by body, engine specifications, the driver eye point, factory wheel fitment, source tiers and verification marks. The production site also serves home, About and 404. The homepage generation picker, variant panels and hero illustration are the next app group. The site remains `noindex`.

The catalog contains one E46 generation, five variants, one real APEX EC-7 wheel design with 17 options, 13 maintenance entries and seven known issues. There are no observations priced for the wheel. Maintenance coverage is US-scoped. Parts, maintenance and issues still need their reading pages. The published 3D asset manifest is empty.

## Work by lane

| Lane | Landed or verified | Next |
|---|---|---|
| App | The B2 shell, fixture build and before/after screenshot workflow landed in [#53](https://github.com/GridWork-dev/m3-tool/pull/53). The first generation page landed in [#60](https://github.com/GridWork-dev/m3-tool/pull/60). | App group C covers the five variant panels, generation hero and homepage links. Then come owner reading pages, the text build sheet, share links and search. See the [reading-pages plan](superpowers/plans/2026-11-24-phase-1-app-reading-pages.md). |
| Data and prices | Sourced factory, maintenance and issue data, citation link policy and price discovery, checking, application and weekly PR tooling. The pricing stack landed in [#49](https://github.com/GridWork-dev/m3-tool/pull/49), [#50](https://github.com/GridWork-dev/m3-tool/pull/50) and [#51](https://github.com/GridWork-dev/m3-tool/pull/51). | Verify real seller observations and expand catalog coverage. Phase 1 targets approximately 60 products plus generic categories, 25 maintenance items and 15 issues. Safety-data changes receive a user spot-check. |
| 3D | Reference collection and curation, export, validation, proportion checks, splitting and generator transport. [#61](https://github.com/GridWork-dev/m3-tool/pull/61) corrected a false silhouette rejection while keeping the 2% dimensional thresholds. [#63](https://github.com/GridWork-dev/m3-tool/pull/63) tracks the five-view synthesis stage and its redaction, provenance and approval checks. | In [the spike](https://github.com/GridWork-dev/m3-tool/issues/6), three matched exterior photos condition five synthesized views. A true side and straight rear remain absent from the real set. Inspect the private contact sheet before generator trials, score against real photos, then complete the exterior, interior and wheel experiments and decision record. |
| Operations | Protected main, CI, secret scanning, Cloudflare previews and commit-verified production deploys. [ADR 0017](decisions/0017-codex-led-workflow-and-reference-collection.md) assigns Codex orchestration, model-specific review, Grok critique and agent-run reference collection. | [#21](https://github.com/GridWork-dev/m3-tool/issues/21) tracks preview/production token isolation. Two older scraping worktrees contain local handoff material to preserve. |

## Decisions to carry forward

- E46 coupe first. Gearwell is the public name. The domain is undecided, and the existing Worker and bucket names still apply.
- The cap for the session that started on November 24 is $50 total for the E46 spike. New sessions require new approval. [#7](https://github.com/GridWork-dev/m3-tool/issues/7) is the later Phase 1 generation budget.
- The maintainer selects the synthesized reference set before paid 3D trials and reviews model quality before publication. Publication terms and the final 3D asset license remain open. The [spike plan](superpowers/plans/2026-11-23-phase-0-6-3d-spike.md) defines the quality gates.
- Keep photos, prepared inputs, contact sheets and private manifests outside git. Code and catalog data retain their existing MIT and CC BY-SA 4.0 licenses.
