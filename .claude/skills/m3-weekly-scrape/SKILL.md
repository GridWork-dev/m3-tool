---
name: m3-weekly-scrape
description: Run and review m3-tool weekly price collection, product-image ride-along and candidate discovery, using the existing pipeline prices CLI.
---

Read [the weekly runbook](../../../docs/runbooks/weekly-scrape.md), `AGENTS.md`
and `pipeline/pricing.toml` from the repo root before running. The runbook owns
setup, environment names, call-tag derivation and recovery details.

Use the maintainer-provided environment. Check this session's approved cap and
same-day spend rows before paid calls; the guard requires positive estimates
even under credit. Do not read or print secrets, proxy URLs or CDP connection URLs.
The orchestrator owns ledger edits. If authorization is missing, prepare the
specific call tags and units for the orchestrator and stop before paid fetching.

Run `pnpm scrape:week` when the request authorizes collection, application and PR
publication. Add `--no-pr` when publication is excluded, or `--no-apply --no-pr`
for collection only. Use `--no-images` when photos are not wanted. The defaults
include private product photos; they use the refs store and crawl provenance.

Review flags, failed sellers and old → new prices; calibrate selector hints when
needed. Run `pnpm check:data` after applying. Discovery is a separate
`pipeline prices discover` command: candidates stay in the work directory until
reviewed. Never auto-convert candidates into observations.

Preserve ADR 0014's boundary: robots and at least 3 s host delays on the polite
tier, advisory robots only on the unblock tier, one logical product check per
seven days. Do not force retries or modify reference-photo collection's posture.

Report checked/skipped counts, blocked/failed sellers, prices needing review,
photos added, ledger units, validation result and the PR URL or local handoff.
Reconcile Evomi byte estimates and failed attempts with vendor usage. Never
commit images, private manifests, cache files or credentials, and never merge.
