## Summary

<!-- What changed and why, in a few lines. Say `Closes #<issue>`. -->

## Lane

<!-- Delete the lines that don't apply. -->
- App + data (`src/`, `data/`)
- 3D (`pipeline/`, `src/lib/asset-*`, the asset manifest)
- Infra, CI or docs
- Contract change (`src/data/schemas.ts`, `src/data/unverified.ts`, `src/lib/asset-contract.ts`, `docs/standards/3d-assets.md`). Add the `contract` label.

## Checks

- [ ] `pnpm check` passes
- [ ] `pnpm e2e` passes
- [ ] No store links, logos or secrets
- [ ] Opus + Codex review done (Sonnet + Codex when the orchestrator is Opus)

## Screenshots

<!-- Before and after for any UI or 3D change. Write "n/a" if there are none. -->

## Data sources (tiers)

<!-- For each data value you added or changed: the source, its publisher, its tier (1 to 3) and the date you opened it.
     Maintenance and issues also get the `safety` label. Write "n/a" if you didn't touch `data/`. -->

## Spend (ledger row)

<!-- Paid calls: paste the row you added to `docs/spend-ledger.md`. Write "none" if there were no paid calls. -->
