# 0013. Model choice without a bake-off

- **Status:** Accepted 2026-11-23
- **Codex role restriction / unchanged routing:** Superseded by [0017](0017-codex-led-workflow-and-reference-collection.md). No-bake-off and subscription-first synthesis decisions remain in force.
- **Date:** 2026-11-23
- **Supersedes:** the bake-off parts of [0004](0004-car-bodies-from-photos.md) and [0007](0007-agent-roles-and-review-gates.md)

## Context

ADR 0007 planned a model bake-off inside the Phase 0 spike: Fable 5.2 and Opus 5.5 against Astra 6.2 and Sol, on three tasks, with at least three seeds a cell and blind votes. ADR 0004 planned an A/B test of two image models for view synthesis. Both cost spike budget and sessions. The user dropped the bake-off and asked that research choose the models. Accepted ADRs are frozen, so this one carries the change.

## Decision

- **No bake-off and no image-model A/B test.** The spike keeps its pass criteria (spec section 9.9). The routing table in ADR 0007 stays as it is.
- **The research basis:**
  - No head-to-head comparison of these models on 3D scripting exists.
  - The public benchmarks are confounded by the harness each model runs in, and they split on which model leads.
  - An LLM hand-modeling the car body isn't viable (ADR 0004).
  - LLMs do well on parametric parts, cleanup, splitting and critique, where a deterministic check scores the result.
- **So:** frontier LLMs write parametric parts and do cleanup and splitting, checked by scripts. Image-to-3D generators make the body and the complex parts.
- **Subscription first for OpenAI image generation.** Reference view synthesis (spec section 9.1a) uses the user's OpenAI subscription through the Codex CLI with its ChatGPT login, and Codex's built-in image generation. That has no API spend. A fal image-edit model is the fallback.
- **The Codex models stay implementation and review lanes,** as `AGENTS.md` routes them.
- **Paid fal calls still need the session cap and a row in `docs/spend-ledger.md`** before the call.

## Alternatives considered

- **Run the bake-off as planned:** rejected by the user. It spends budget to confirm what the research already says.
- **Use the OpenAI image API, A/B tested against Gemini:** rejected. The subscription covers it with no API spend.
- **Pick one model family for everything:** rejected. The routing table assigns roles by what each does well.

## Consequences

- ADR 0007's bake-off bullet, its bake-off alternative and its note that the routing table may change after the bake-off no longer apply. The A/B test in ADR 0004's view-synthesis bullet, and its `gpt-image-2.6-sunburst` first choice, are replaced by the subscription-first rule.
- The routing table changes only by its own PR, with evidence.
- Subscription use is limited by the plan's quota, not by a cap. If Codex can't make the views, the fallback is a paid fal call, with a ledger row.
- Without a head-to-head, a wrong choice shows up late, in the spike's scores and the critic. Changing a model is then cheap: one line of routing.
