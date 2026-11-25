# 0017. Codex-led workflow and agent reference collection

## Status

Accepted 2026-11-24 by the user. Supersedes the routing and reviewer assignments in [0007](0007-agent-roles-and-review-gates.md) and the restriction of Codex to implementation and review in [0013](0013-model-choice-without-bake-off.md). Their other decisions remain in force.

## Context

The user chose Codex orchestration and subagents, with Grok CLI for additional work, and asked for independent tasks to run in parallel. The user also transferred reference-photo collection and source selection to the agents. This changes ownership, without establishing that a model is more accurate or that a product acceptance gate has passed.

## Decision

Keep specs, plans, integration and merges with the root Codex session and the user. Assign models explicitly by role:

| Role | Assignment |
|---|---|
| Implementation, tests and bounded edits | `gpt-6.1-sol` |
| Independent task review | A separate non-author `gpt-6.1-sol` run |
| Architecture and Codex second opinion | `gpt-6-astra`, high reasoning |
| Data verification | Separate `gpt-6-astra`, high reasoning; reopen cited sources |
| 3D vision critique | `gpt-6-astra`, high reasoning, inspecting the actual images |
| Recon and bulk research | `gpt-6-luna`, low reasoning |
| Additional independent critique and research | Grok CLI; record the selected model |

Use separate worktrees and explicit file ownership for parallel implementation. Serialize integration of dependent changes. Preserve dedicated `contract` PRs and both lanes' rebases onto them.

Retain a task review and a separate Codex second opinion through `codex-review` for each PR. Require source re-reading for data PRs, the user's spot-check for `safety` PRs, required checks, applicable screenshots and fixes before squash merge. Agreement between models is not source verification.

Treat Grok's findings as inputs to verify against code, sources, tests or images. Do not give a critique authority to edit files, waive gates or merge. Grok supplements the required reviews.

Use ChatGPT login for Codex and grok.com login for Grok subscription inference. Check authentication and remove inherited API-key variables from the subprocess environment; never fall back silently to paid API billing. Subscription inference needs no spend row, but paid calls still require a fresh session cap and a row before the call. Preserve the scraping-service unit accounting in ADR 0014.

Have agents select sources, collect and curate reference photos under root coordination. Keep the existing robots, terms, rate-limit, generic-user-agent, provenance and private-storage rules; log and skip blocked sources. The price-scraping unblock exception does not apply to reference photos.

Retain user approval of synthesized views and models, scoring against real photos, and generator-license checks before publication. A critic that cannot inspect the images leaves the visual gate incomplete. Keep subscription-first image synthesis and the no-bake-off decision from ADR 0013.

## Rejected options

- Retain Claude-led execution: contradicts the user's selected workflow and keeps a harness dependency the user removed.
- Let Grok execute and merge automatically: splits integration ownership and turns unverified opinions into changes.
- Replace the review gates with Grok alone: loses the independent task review, Codex review and evidence checks.

## Consequences

Work can resume without a Claude dependency or a user-operated collection handoff. Separate reviews, direct evidence and deterministic checks remain necessary because Codex lanes can share mistakes. Grok adds an independent perspective and coordination cost.

This decision grants no paid cap, domain choice, public-beta release or acceptance of synthesized views, generated models or the spike. ADR 0015 remains reserved for the spike outcome.

## Citations

- [Workflow handoff #55](https://github.com/GridWork-dev/m3-tool/issues/55).
- User direction, 2026-11-24: use Codex and Grok, parallelize independent work, and take over reference collection.
- [AGENTS.md](../../AGENTS.md), [design spec](../superpowers/specs/2026-11-23-m3-tool-design.md), and [data standard](../standards/data.md).
- [0007](0007-agent-roles-and-review-gates.md), [0013](0013-model-choice-without-bake-off.md), and [0014](0014-price-scraping-unblock.md).
