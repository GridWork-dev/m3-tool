# Repository state and next work

Snapshot: 2026-11-24. This is a handoff, not evidence that an open PR has merged. Check GitHub and the branch before resuming a task.

## Built on main

- Foundations: static Astro site, React integration, Tailwind, Pagefind build, strict TypeScript/Python checks, data validation, GLB contract/validator, link policy, CI, protected main and Cloudflare deploy/preview workflows.
- Site: home, about and 404 only. No generation reading pages, mods, build sheet, share links or search UI yet. The site remains `noindex`.
- Data: one E46 generation, five variants, one real APEX EC-7 product with 17 options and no price observations, 13 maintenance entries and seven known issues. Maintenance is US-scoped. Recorded uncertainty in generation/variant fields must remain visible when the reading pages render it.
- Reference tooling: collectors, provenance store, classification/curation, viewsets, private R2 sync and a collection runbook. Collection is now agent-owned under ADR 0017.
- 3D spike: Tasks 0–7 and 9 provide inputs, spending guards, placement/preparation, export, Codex runner, local viewer, generator transport and scoring math. Registered stages on the audited main are `refs`, `export` and `validate`. The asset manifest is empty; helper code is not a passed spike.

## Work in flight

| Work | State and next gate |
|---|---|
| [#53: app group A](https://github.com/GridWork-dev/m3-tool/pull/53) | Tokens/shell plus fixture build and CI screenshots; verify review and CI before landing. Group B (Tasks 5–7: display/citation helpers and generation specs) follows. |
| [#46: proportion check](https://github.com/GridWork-dev/m3-tool/pull/46) | Review found disconnected foreground pixels could falsely pass the height check; regression fix and re-review required. |
| [#54: segmentation](https://github.com/GridWork-dev/m3-tool/pull/54) | Scripted/Tripo stage, with offline tests and recorded Blender checks; independent review required. This is not proof of quality on a real generated car. |
| [#49](https://github.com/GridWork-dev/m3-tool/pull/49), [#50](https://github.com/GridWork-dev/m3-tool/pull/50), [#51](https://github.com/GridWork-dev/m3-tool/pull/51): pricing stack | Fetch/config → check/apply/PR → weekly runner/discovery. Narrow test-typing repairs prepared on the first two branches. Review current heads and integrate bottom-up, resolving overlap with the top branch's earlier fix. No live paid scrape was run. |

The full app roadmap is the [reading-pages plan](superpowers/plans/2026-11-24-phase-1-app-reading-pages.md): reading pages, prices/mods, build logic, build sheet/share links, then search/beta readiness. The approximate data targets remain 60 real products plus generic categories, 25 maintenance items and 15 issues; source quality takes precedence over counts.

The 3D sequence is proportion/segment integration → synth → generate → cleanup → score → exterior/interior/wheel experiments → report and ADR 0015. Implement independent stages offline while the app progresses. Real runs still need suitable references, applicable session spending authorization and the human gates in the [spike plan](superpowers/plans/2026-11-23-phase-0-6-3d-spike.md).

## Decisions retained and unresolved

- E46 coupe first; Gearwell public name; B2 “pit garage” design; separate app/data and 3D lanes; no commerce/logos; noindex until beta; contracts in dedicated PRs.
- Codex root orchestrates, Codex workers implement/review and Grok adds independent critique. [ADR 0017](decisions/0017-codex-led-workflow-and-reference-collection.md) records source verification, billing and collection ownership.
- No domain is selected or registered by this session. Keep existing deployment names. The reading-pages plan defers the public rename to the domain decision.
- No fresh paid generation cap is approved. Old ledger approvals authorize no new paid calls. Phase 1 generation budget follows the spike result.
- Generator publication terms and final 3D licensing remain open; so do Phase 2 module-swap precedence and the later generation choice.
- [#21](https://github.com/GridWork-dev/m3-tool/issues/21) remains open: production/preview token isolation is a kickoff follow-up, not a completed security improvement. Token minting remains with the maintainer's session.

## Cleanup and resumption rules

Ten clean legacy worktrees matched the final heads of merged PRs in this audit: labor estimate, model years, maintenance, paints, safety, ST041 tier, app plan, numpy, generators and scoring. They are retirement candidates, not permission to delete ignored artifacts without inspecting them. Preserve the unmerged app/proportion/segment/pricing worktrees.

The scraping and scraping-prices worktrees contain untracked handoff material. Preserve it before any cleanup; branch ancestry is insufficient after squash merges. The price plan also exists in the committed pricing stack, so compare contents before treating local copies as redundant.

Photo tooling issue [#5](https://github.com/GridWork-dev/m3-tool/issues/5) is closed: PRs #18/#20 fulfilled its tooling-and-runbook exit criterion. The 3D spike (#6) and Phase 1 spend cap (#7) remain open. Keep photos, private manifests, renders and local handoff paths out of this public document.
