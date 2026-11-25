# 0007. Agent roles, review gates and zero required approvals

- **Status:** Accepted 2026-11-23. The model bake-off (its bullet, its alternative and its routing-change note) is superseded by [0013](0013-model-choice-without-bake-off.md).
- **Routing/reviewer assignments:** Superseded by [0017](0017-codex-led-workflow-and-reference-collection.md). Other review and repository gates remain in force.
- **Date:** 2026-11-23

## Context

The tool is built and maintained mostly by coding agents, behind strong tests, previews and review gates. The repo has one maintainer. GitHub doesn't let an author approve their own PR, so a required approval would block every merge. `main` is protected, and a PR is the only way in.

Agents run in parallel lanes, and a wrong model choice either wastes budget or lowers quality. Routing has to be written down, not left to each session.

## Decision

- **Model routing.** Pass a model on every subagent, and never run a child on the orchestrator's tier.

  | Role | Claude | Codex |
  |---|---|---|
  | Orchestrator: owns specs, plans and merges, with the user | Main session (Fable or Opus) | none |
  | Architecture and code review | Opus 5.5 (when the orchestrator isn't Opus) | gpt-6-astra (high), via codex-review |
  | Data verifier (every data PR) | Opus 5.5 | none |
  | 3D vision critic | Opus 5.5 | none |
  | Implementation, tests, bounded edits | Sonnet 5.5 | gpt-6.1-sol |
  | Research, bulk data gathering, recon | Haiku 5.5 | gpt-6-luna (low) |

- **Task review.** Every PR gets a task review plus a Codex second opinion. With an Opus orchestrator, the reviewers are Sonnet plus Codex. Data PRs also get the Opus data verifier. `safety` PRs (maintenance and issues) wait for the user's spot-check.
- **Zero required approvals.** The ruleset (`infra/github-ruleset.json`) requires the `check`, `e2e` and `gitleaks` status checks, squash merges and no bypass actors. The review happens before the merge instead.
- **Two lanes after Phase 0:** app and data (`src/`, `data/`), and 3D (`pipeline/`, the scene code, the asset manifest). Each has its own worktree and branch. The shared contracts change only through a dedicated `contract` PR that both lanes rebase onto.
- **The model bake-off runs inside the spike.**
  - Contestants: Fable 5.2 and Opus 5.5 in Claude Code, against Astra 6.2 and Sol in Codex.
  - Three tasks: a parametric wheel and rotor fitted to product photos, splitting and cleaning a generated mesh, and a critic-only defect hunt.
  - At least 3 seeds per cell, scored by automatic metrics plus blind votes on screenshots. Tokens, dollars and minutes are logged for every run.
  - The winner takes that kind of task, and the result is recorded in an ADR.

## Alternatives considered

- **One required approval:** rejected. The sole maintainer can't approve their own PR, so it would block every merge.
- **Merging without a second model's opinion:** rejected. Review is the gate that replaces the approval.
- **Unpinned subagents, or children on the orchestrator's tier:** rejected, per the user's routing rules.
- **Hand-modeling the body with an LLM as a bake-off task:** out of scope. The research showed it isn't viable (ADR 0004).

## Consequences

- GitHub doesn't enforce the review, so the process does. Nothing in the ruleset stops a merge that skipped it, and the PR template's checklist is the reminder.
- `deploy` runs on every PR but isn't required, because it needs secrets that fork PRs don't get.
- Opus reviews only when the orchestrator isn't Opus, so the reviewer pair changes with the session. The PR template's checklist names both pairs.
- The routing table may change after the bake-off. That change is its own PR and cites the ADR with the result.
- Contract changes cost a separate PR and a rebase for both lanes. That is the price of two lanes building against stable contracts.
