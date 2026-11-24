# Spend ledger

Every paid API call is logged here, such as 3D generation now and scraping later. Hosting stays on free tiers, so only these calls cost money. The table below must stay last: nothing may follow it, and every line after its header must be a table row, because the spend guard reads the ledger that way and denies every paid call on a line it cannot read.

**Rules**
- The user approves a cap at the start of each session. An earlier approval covers nothing.
- Add a row before you make the call. Set `Cost` to your estimate, and correct it to the real figure afterward.
- Keep the running total and the cap in the last column. Stop when the next call would pass the cap, and ask the user.
- Put no key, token or account ID in a row. A service is named, never its credentials.

| Date | Session cap | Service | Purpose | Units | Cost (USD) | Running total / cap |
|---|---|---|---|---|---|---|
| 2026-11-23 | $50 (Phase 0 spike, 3D generation) | — | cap approved by the user | — | 0.00 | 0.00 / 50.00 |
| 2026-11-23 | $0 incremental this phase (owned: Browserbase Developer, Bright Data credit, Evomi prepaid) | Browserbase / Bright Data / Evomi | price and product-page scraping cap approved by the user (ADR 0014) | browser-hrs / requests / GB | 0.00 | 0.00 / 0.00 incremental |
