# Docs

An index of everything under `docs/`, plus the infrastructure notes. Start with [AGENTS.md](../AGENTS.md) at the repo root: it has the commands, the layout and the hard rules.

- [Repository state and next work](status.md): shipped capabilities, open work, gates and cleanup.

## Standards

| Page | What it sets |
|---|---|
| [Code](standards/code.md) | TypeScript and Python rules, and where logic lives |
| [Testing](standards/testing.md) | One command per question, test layers, fixtures |
| [Data](standards/data.md) | Data layout, ids, source tiers, what counts as verified, prices |
| [3D assets](standards/3d-assets.md) | The GLB contract, how each check is measured, the manifest |
| [Legal](standards/legal.md) | Trademarks, forbidden marks, the notice, reference photos, licenses |

## Decisions

[Decisions](decisions/README.md): the architecture decision records. Each one says what was decided, what was rejected and why, and what it costs.

## Design and plans

- [Design spec](superpowers/specs/2026-11-23-m3-tool-design.md): what the tool is, the stack, the architecture and the roadmap.
- [Phase 0A plan](superpowers/plans/2026-11-23-phase-0a-foundations.md): the foundations, task by task.
- [Phase 0B plan](superpowers/plans/2026-11-23-phase-0b-photo-tooling.md): the reference-photo tooling.
- [Phase 1 app plan 1](superpowers/plans/2026-11-24-phase-1-app-reading-pages.md): the app lane's roadmap in five plans, and the first one in full (the reading pages).
- [3D spike plan](superpowers/plans/2026-11-23-phase-0-6-3d-spike.md): offline stages, experiments and human gates.
- [Reference collection runbook](runbooks/refs-collection.md): private collection and curation.
- [Visual design](design/README.md): the chosen direction, "pit garage", with its mock-up and tokens.

## Operations

- [Spend ledger](spend-ledger.md): every paid API call, with its session cap.
- [Infrastructure](../infra/README.md): the Cloudflare Worker, the R2 buckets and the tokens, by name.
- [Contributing](../CONTRIBUTING.md): setup and the rules in short form.
