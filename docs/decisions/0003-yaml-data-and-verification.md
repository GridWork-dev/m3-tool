# 0003. YAML data, Zod schemas and the verification rule

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

The site publishes claims: specs, part fitment, prices, maintenance intervals and known issues. Wrong fitment or maintenance advice harms users, and stale or wrong prices cost trust. Two lanes (app and data, and 3D) build against the data shapes at once, and agents write most of the entries.

Source quality varies from factory manuals to forum threads. The rules have to be mechanical enough that `check-data` can enforce them.

## Decision

- **YAML, one entry per file,** under `data/{generations,variants,parts,maintenance,issues}/`. A file's stem equals its `id`. IDs are kebab-case, stable and never reused.
- **Zod schemas in `src/data/schemas.ts` are the contract.** Astro content collections (`src/content.config.ts`) and `tools/check-data.ts` share them, so the build and the CLI can't disagree. Schemas import `z` from `astro/zod`.
- **Objects are strict.** A key the schema doesn't list is an error, so a typo like `brnad:` fails instead of being dropped.
- **Entry ids come from the YAML `id`,** not from the file path. Astro's default would store `e46/fixture-wheel`, while `requires` and `conflicts` name the bare id.
- **Dates are date-only,** `YYYY-MM-DD`. A timestamp without a zone means different instants on different host time zones. Quoted and unquoted dates validate to the same instant, midnight UTC, because `yaml` 1.2 keeps a string and Astro's loader makes a Date.
- **Source tiers.**
  - Tier 1: BMW technical documents and manufacturer product pages and install guides.
  - Tier 2: specialist retailers' tech articles, reputable publications, well-known specialist shops.
  - Tier 3: forums and owner reports.
- **"Verified" means one thing** for maintenance, issues and parts: one Tier 1 source, or two Tier 2 sources from distinct publishers. Manufacturer product pages are Tier 1. Publisher names are compared after trimming, collapsing spaces and ignoring case. Tier 3 alone leaves an entry `verified: false`, with an "unverified" badge.
- **Data is licensed CC BY-SA 4.0** (`DATA_LICENSE`). Code is MIT.

## Alternatives considered

- **A database (D1):** not in v1. The spec brings in D1 only if accounts ever arrive, and accounts and server-saved builds are non-goals.
- **Timestamps in data:** rejected for the time-zone reason above.
- **A separate rule for parts:** rejected. `verified` means the same thing for maintenance, issues and parts.
- **Forum posts as sufficient evidence for fixes and intervals:** rejected. Safety-relevant advice that rests only on a forum post is an anti-goal.
- **Schemas that drop unknown keys:** rejected, for the typo reason above.

## Consequences

- `check-data` reports a verified entry that falls short as `verified-without-tier`. It also checks ids, references and the generic-tier rule. The data standard lists every code.
- Every data PR gets an Opus data verifier that re-reads the cited sources. PRs touching maintenance or issues carry the `safety` label, and the user spot-checks them.
- Changing `src/data/schemas.ts` needs a dedicated `contract` PR that both lanes rebase onto.
- Hand-written dates like `2026-11-23T10:30` are errors. Write the day only.
- Anything under `data/` is published, so it holds real, sourced values only. Sample entries live in `tests/fixtures/data/`.
- Share-alike data means anyone may reuse it with credit, under the same license. The 3D models are proposed at CC BY-SA 4.0 too, final once the generator terms are checked.
