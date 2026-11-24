# 0010. Safety advice needs evidence

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

Spec section 7.6 says safety advice never rests on a forum post alone, but the rule was only half enforced. `verified: true` was checked against the tier rule, while an entry left at `verified: false` could publish a maintenance interval or a fix backed by Tier 3 sources only. The `fixture-rod-bearings` fixture did exactly that: a fix, a cost and a single forum thread. `KnownIssue.fix` was required, so an issue known only from forum reports couldn't be published without one. The Codex final review ranked this a P1.

## Decision

- **A maintenance item needs at least one Tier 1 or Tier 2 source,** verified or not.
- **`KnownIssue.fix` is optional.** When it is present, the issue needs at least one Tier 1 or Tier 2 source, and a `cost`. Without a fix, `cost` is optional.
- **A Tier 3 only issue publishes symptoms, cause and how common it is,** and no fix. Tier 3 is enough for those.
- **A new quality code, `safety-advice-without-evidence`,** reports a violation. The `cost`-with-`fix` rule is a schema refinement.
- **Evidence is weaker than verification.** One Tier 2 source is enough to publish; `verified: true` still needs one Tier 1 or two independent Tier 2. The badge means what it meant.
- **`fixture-rod-bearings` loses its fix and cost.** A new fixture shows a fix backed by Tier 2.
- Spec sections 7.3 and 7.6 are amended to match.

## Alternatives considered

- **Require `verified: true` before publishing:** rejected. Nothing would publish until two Tier 2 sources exist, and one good source is useful.
- **Keep `fix` required and mark Tier 3 fixes with a badge:** rejected. People act on a fix, and a badge doesn't stop them.
- **Warn instead of fail:** rejected. A warning is skipped in a data PR, and the user's spot-check of `safety` PRs shouldn't be the only line of defense.
- **Gate `prevention` too:** deferred. It is advice, but it isn't a repair, and no one has asked for it. The data verifier and the spot-check look at it.

## Consequences

- Some fixes that forums know about can't be published until a better source turns up. The issue still appears with symptoms, cause and frequency.
- `fix` and `cost` are optional on `KnownIssue`, so the Phase 1 pages must render an issue without a fix, for example as "no sourced fix yet".
- The schema change is a contract change, so it comes in a `contract` PR.
- The data verifier checks that a Tier 2 source really supports the fix. The rule only checks that one exists.
