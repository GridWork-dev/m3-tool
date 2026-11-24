# Weekly price scrape

## Setup and private output

Run from the repository root. Install the pinned tools with `mise install`,
`pnpm install`, `uv sync --project pipeline`, and
`uv run --project pipeline playwright install chromium`.
Set `M3_WORK_DIR` to a private directory outside the repository (default
`~/.cache/m3-tool`). Never commit photos, manifests, credentials or cached pages.
The maintainer supplies credentials through the environment; the runner never
opens a secrets file and never prints credentials.

`pipeline/pricing.toml` selects sellers and tiers. Initially, selectors await
calibration: inspect flagged results and calibrate CSS hints against the product's
own price. Shipping, related items and "from" prices are rejected. Changes of
10× or more and currency mismatches require review and are excluded from apply.

Environment names:

- `M3_BRIGHTDATA_UNLOCKER_TOKEN`, `M3_BRIGHTDATA_UNLOCKER_ZONE`.
- `M3_BROWSERBASE_API_KEY`, `M3_BROWSERBASE_PROJECT_ID`.
- `M3_EVOMI_PROXY_URL` (credential-bearing; never paste it into output).
- `M3_EXA_API_KEY` for candidate discovery.
- `M3_PRICES_USER_AGENT` optionally overrides the identifying User-Agent.
- `M3_REPO_ROOT` optionally selects the repository; normally leave it unset.
- `M3_SPEND_SESSION` and the cost estimates described below.

## Posture and limits

ADR 0014 applies to prices and their product-image ride-along. The polite tier
respects robots.txt on every redirect hop, waits at least 3 seconds per host,
uses `m3-tool-refs/0.1 (+https://github.com/GridWork-dev/m3-tool)`, and uses plain
httpx or a local browser when JavaScript is required. Robots delays can raise
that floor. It uses no stealth.

The unblock tier treats robots.txt as advisory. Its ladder is Bright Data Web
Unlocker → Browserbase with captcha solving and advanced stealth enabled →
Evomi residential. Each rung runs at most once. Missing credentials skip that
rung; spend denial stops the run. A polite seller escalates only when the refs
blocked detector sees a challenge or block status. An ordinary 5xx retries once
politely after a double delay and never escalates.

There is at most one request per product per rolling seven days, by stored URL,
including failures. Retries and ladder attempts belong to that single logical
product check. A blocked result means the challenge survived all available
rungs; it is reported and skipped for the week. Do not delete run state to force
another attempt. Reference/car-photo collection keeps its separate polite-only
posture and unchanged Browserbase payload.

Product images use the refs crawl engine and private RefStore under
`product-<part-id>`, with crawl provenance and a minimum side of 800 px. Polite
image requests also check robots on redirects; `--no-images` skips the refs store.

## Spend before calls

Before any paid outbound call, the orchestrator obtains a session-approved cap
and writes same-day rows in `docs/spend-ledger.md`, including units even when
credit covers the marginal cost. This runner never edits the ledger. Set
`M3_SPEND_SESSION=<label>` to match the cap row's exact purpose:
`cap approved by the user session:<label>`.

The existing spend guard requires a **positive** USD estimate for each call,
a same-day `spike:<tag>` purpose row, correct running totals, and remaining cap.
It journals authorization before network access; a tag cannot be reused, even
after a crash. This lane complies with the guard's `spike:` grammar despite being
a weekly job. Configure positive conservative estimates through
`M3_PRICES_BRIGHTDATA_COST_USD`, `M3_PRICES_BROWSERBASE_COST_USD`,
`M3_PRICES_EVOMI_COST_USD`, and `M3_PRICES_EXA_COST_USD`.
Zero is refused even under existing credit. Reconcile actual usage afterward.

Call tags are deterministic: `prices-<service>-<YYYY-MM-DD>-<digest>`, where
`digest` is the first 16 lowercase hex characters of SHA-256 of the exact URL
encoded as UTF-8. Services are `brightdata`, `browserbase`, `evomi`, and `exa`;
Exa hashes the exact query instead of a URL. Its query is
`<brand> <name> <part-id> site:<seller-host>` with outer whitespace stripped.
Prepare rows for every rung that might be used, including redirected product
URLs. The date is the local run date. No cap, missing call row, a reused tag, or
an invalid estimate stops before that paid call. A denied run may already have
marked attempted URLs; inspect state rather than forcing a retry.

The report prints the ledger units line: unlocker requests, Browserbase sessions,
Evomi GB and Exa searches. Evomi GB is estimated from response payload bytes,
excluding overhead and failed transfers; reconcile it with the vendor dashboard.
Failed session/request attempts may also need vendor reconciliation. Discovery
writes its Exa units into the candidates file and prints them.

Verified API shapes (2026-11-24): Bright Data uses
[POST /request](https://docs.brightdata.com/api-reference/rest-api/unlocker/unlock-website),
Bearer authentication, and `{zone, url, format: "raw"}`. Exa uses
[POST /search](https://exa.ai/docs/reference/search), `x-api-key` authentication,
and `{query, numResults: 5, type: "auto"}`. Payload tests pin these semantics.

## Run and review

A review-only collection (still requires spend authorization if it unblocks):

```sh
uv run --project pipeline pipeline prices check --no-images
uv run --project pipeline pipeline prices check --seller turner-motorsports --no-images
uv run --project pipeline pipeline prices apply --dry-run
```

`check` saves `prices/report.json` in the work directory. `apply` reads that saved
report; the dry run lists files without writing. Review flagged items and the
seller selectors before accepting prices. Applied observations retain historical
prices and schema field order. Unchanged prices within seven days are not added.

```sh
uv run --project pipeline pipeline prices apply
pnpm check:data
uv run --project pipeline pipeline prices pr --no-pr
```

`apply` saves the changed-file list and change table in `prices/applied.json`.
`pr --no-pr` creates the local `data/prices-<date>` branch and commits only those
part YAML files, with no push or PR. Run standalone `pr` instead, when authorized
to publish; it pushes and creates the PR, containing old → new prices, >20% and
>10× flags, failures and ledger units. It rejects unrelated tracked/staged edits.
Do not run standalone `pr` again after the local-commit flow: that branch already
exists; hand its reviewed commit to the orchestrator for publication.

The combined runner checks → applies → opens a PR. Each mutation is skippable:

```sh
uv run --project pipeline pipeline prices week --no-images --no-apply --no-pr
uv run --project pipeline pipeline prices week --no-pr
```

The first command only collects; the second also applies locally. Neither
pushes. `--no-apply` also suppresses PR creation. An authorized full weekly run is
`pnpm scrape:week` (or `uv run --project pipeline pipeline prices week`);
it prints the report, ledger units and PR URL. All command help is available
with `--help`. The weekly runner leaves the resulting data branch checked out.

Discover candidates separately:

```sh
uv run --project pipeline pipeline prices discover --part fixture-wheel
uv run --project pipeline pipeline prices discover
```

Replace `fixture-wheel` with a real part ID. Discovery writes
`prices/candidates/<date>.json`, never `data/`. Review product, option, seller
and currency by hand before adding stored URLs. An opted-out seller is neither
checked nor searched. Discovery repeats on the same date need fresh spend
planning; existing tags cannot be reused.

`prices/last-run.json` is a JSON-lines log despite its filename: per-URL fetch
dates, with a torn final append dropped and middle corruption refused.
`prices/scrapling-store/` contains seller-specific adaptive selector databases.
Only validated price elements are saved for adaptive matching. Keep both private.

## Brief for another harness

    Work from the repo root. Read AGENTS.md, ADR 0014, pricing.toml and this runbook.
    Use the maintainer-provided environment only; never print secrets or proxy URLs.
    Check the current session cap, same-day spend rows and positive call estimates.
    Run prices week with --no-pr if publication is not authorized, or with
    --no-apply --no-pr for collection only. Report checked/skipped URLs, failed
    sellers, flags, photos added and ledger units. Inspect price hints rather than
    accepting a wrong-looking price. Keep photos and run state outside git.
    Do not force reruns, change refs behavior or write discover candidates into data.
    Give the orchestrator the resulting changes and tests; publish only as authorized.

## What this deliberately won't do

No stealth on the polite tier, no retry storms, no auto-writes from discover,
and no automatic acceptance of large jumps or ambiguous prices. robots.txt is
advisory only on the unblock tier. No reference-photo unblocking, store links,
affiliates, logo assets, secrets-file loading, spend-ledger edits or automatic
merges. The weekly job stays local; it does not install a scheduled Action.
