# 0014. Optional costs, interval triggers and markets

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23
- **Amends:** the cost-with-a-fix rule of [0010](0010-safety-advice-evidence.md)

## Context

The first E46 safety data (the known issues PR) hit four limits of the maintenance and issue schemas, and stopped rather than work around them:

- `MaintenanceItem.cost` was required, with no way to say "unknown". No Tier 1 or Tier 2 source gives a per-item cost for the E46, and price collection is another lane's job. `[0, 0]` would read as free.
- BMW states most E46 intervals as Oil Service, Inspection I or Inspection II, set by the Service Interval Indicator, with no mileage. The interval needed `miles` or `months`.
- There was no market field, so a US booklet could not be told from a European one except by id and title.
- A `KnownIssue` with a `fix` needed a `cost` (ADR 0010). The SMG pump has a sourced Tier 2 repair and no sourced shop cost, so the fix would have been dropped.

## Decision

- **`MaintenanceItem.cost` is optional.** Absent, the site shows "no sourced cost", never zero. A cost that is given is validated as before.
- **A `KnownIssue`'s `fix` no longer requires a `cost`.** The refinement is dropped, and the same "no sourced cost" rule applies. A fix still needs a Tier 1 or Tier 2 source.
- **`MaintenanceItem.interval` gains an optional `trigger`**: `oil-service`, `inspection-i`, `inspection-ii`, `lifetime-fill` or `condition-based`. An interval needs at least one of `miles`, `months` or `trigger`. `miles` and `months` may sit beside a trigger only when the source gives both. The site shows the trigger, not a made-up mileage.
- **`MaintenanceItem` gains an optional `markets`**: a non-empty list of `us` or `euro`, with no repeats. Absent means every market. A document for one market supports that market only (R61).
- `data.md` says what each trigger means and when to use each new field.

## Alternatives considered

- **`cost: [0, 0]` for unknown:** rejected. Nothing tells it from free, and the site would show it.
- **An `estimated` flag on cost, like labor:** rejected. Labor hours are a guess a reader can weigh. A dollar figure with no source is a price the other lane owns.
- **Infer mileages for the inspections:** rejected. Inspection II looks like 60,000 miles from two documents of different years, but that is an inference and BMW's own documents don't state it.
- **A free-text interval note:** rejected. The site couldn't group or order maintenance by it.
- **Market in the id and title only:** rejected. It can't be checked, filtered or rendered as a market.

## Consequences

- The Phase 1 pages must render an absent cost as "no sourced cost", a trigger as its name, and `markets` as the markets covered.
- Nothing in the schema stops `lifetime-fill` from carrying `miles` or `months`, or a trigger from carrying a number the source doesn't give. The data verifier and the `safety` spot-check look at both.
- Existing data is unchanged: every current entry stays valid.
- This is a contract change, so it comes in a `contract` PR, and the E46 maintenance items follow it.
