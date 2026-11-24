# 0016. Optional costs, interval triggers and markets

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23
- **Amends:** the cost-with-a-fix rule of [0010](0010-safety-advice-evidence.md)

## Context

The first E46 safety data (the known issues PR) hit limits in the maintenance and issue schemas, and stopped rather than work around them:

- `MaintenanceItem.cost` was required, with no way to say "unknown". No Tier 1 or Tier 2 source gives a per-item cost for the E46, and price collection is another lane's job. `[0, 0]` would read as free.
- BMW states most E46 intervals as Oil Service, Inspection I or Inspection II, set by the Service Interval Indicator, with no mileage. The interval needed `miles` or `months`.
- BMW's booklet ties some items to two services: the microfilter at the Oil Service and Inspection I, the gearbox and differential oil at the 1200 Mile Service and Inspection II.
- There was no market field, so a US booklet could not be told from a European one except by id and title.
- A `KnownIssue` with a `fix` needed a `cost` (ADR 0010). The SMG pump has a sourced Tier 2 repair and no sourced shop cost, so the fix would have been dropped.

## Decision

- **`MaintenanceItem.cost` is optional.** Absent, the site shows "no sourced cost", never zero. A cost that is given is validated as before.
- **A `KnownIssue`'s `fix` no longer requires a `cost`.** The same "no sourced cost" rule applies. A fix still needs a Tier 1 or Tier 2 source.
- **`MaintenanceItem.interval` gains optional `triggers` (ruling R79):** a non-empty list of unique values from `break-in` (BMW's 1200 Mile Service), `oil-service`, `inspection-i`, `inspection-ii`, `lifetime-fill` and `condition-based`. An interval needs at least one of `miles`, `months` or `triggers`. `lifetime-fill` and `condition-based` stand alone, and `lifetime-fill` takes no `miles` or `months`. Otherwise `miles` and `months` may sit beside triggers only when the source gives both.
- **An item that uses `lifetime-fill` or `condition-based` needs a Tier 1 source,** whatever its `verified` flag says (`no-schedule-without-tier1`). It is advice not to change something.
- **`MaintenanceItem` and `KnownIssue` gain optional `markets`:** a non-empty list of `us` or `euro`, no repeats. Absent means every market, which needs evidence for every market: one source that applies to all of them, or a source for each. A document for one market supports that market only (R61).
- `data.md` says what each trigger means, including that Inspection II repeats every Inspection I item.

## Alternatives considered

- **`cost: [0, 0]` for unknown:** rejected. Nothing tells it from free, and the site would show it.
- **An `estimated` flag on cost, like labor:** rejected. A dollar figure with no source is a price the other lane owns.
- **Infer mileages for the inspections:** rejected. BMW's own documents don't state them.
- **A single `trigger`, with one item per trigger or a note:** rejected. The booklet ties items to two services, so it means duplicate items or an unchecked note, and changing the shape later needs another contract PR.
- **A free-text interval note:** rejected. The site couldn't group or order maintenance by it.
- **Market in the id and title only:** rejected. It can't be checked, filtered or rendered as a market.
- **Let any Tier 2 source carry `lifetime-fill`:** rejected. One retailer's article could then tell owners never to change a fluid.

## Consequences

- The Phase 1 pages must render an absent cost as "no sourced cost", triggers as their names (an `inspection-i` item as due at every inspection), and `markets` as the markets covered.
- The schema can't see sources, so nothing stops a trigger from carrying a number the source doesn't give, or `markets` left out for a one-market source. The data verifier and the `safety` spot-check look at both.
- Existing data is unchanged: every current entry stays valid.
- This is a contract change, so it comes in a `contract` PR, and the E46 maintenance items follow it.
