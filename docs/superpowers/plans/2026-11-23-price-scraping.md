# Price Scraping (`pipeline prices`) Implementation Plan

> **For agentic workers:** implement task-by-task, tests first, exactly as pinned. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** product-page discovery, weekly price collection under the ADR 0014 posture, product photos riding along, and the local weekly runner (script + `m3-weekly-scrape` skill) with its runbook — design spec section 13 as amended.

**Architecture:** a `m3_pipeline.prices` package behind a Typer sub-app (`pipeline prices ...`). Sellers live in `pipeline/pricing.toml` (tier, selector hints, currency). Fetching is two-tier: polite first (httpx and Scrapling `Fetcher` without stealth; Playwright for JS pages), then the pre-approved unblock ladder (Bright Data Web Unlocker → Browserbase with captcha solving and stealth on → Evomi residential as a spare). Extraction uses Scrapling adaptive selectors with per-seller CSS hints. Product images extracted from visited product pages go into the refs store. Everything reuses the refs package's robots cache, throttle, blocked detection, image extraction and store.

**Tech Stack:** Python 3.14 + uv; existing pins httpx 0.28.1, playwright 1.65.2, pydantic 2.14.4, pyyaml 6.0.4, typer 0.29.2; new: `scrapling==0.5.1` (re-verify the current version on the dispatch day; if it differs, pin the current one exactly). Bright Data, Evomi and Exa are plain HTTP through httpx — no new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-23-m3-tool-design.md` §7.3, §13 (amended); `docs/decisions/0014-price-scraping-unblock.md`.

**Base:** `main`, after the Phase 0b photo tooling PRs merge. Branches: `feat/prices-config`, `feat/prices-fetch`, `feat/prices-check`, `feat/prices-apply`, `feat/prices-pr`, `feat/prices-discover`, `feat/prices-week`, stacked.

## Global Constraints

- **Posture (ADR 0014, pre-approved — do not relitigate):** the polite tier respects robots.txt (via the refs `RobotsCache`), rate-limits 3 s per host, sends `m3-tool-refs/0.1 (+https://github.com/GridWork-dev/m3-tool)` and caches results. The unblock tier (sellers configured `tier = "unblock"`: marketplaces and sellers that block us) treats robots.txt as advisory. On either tier: **at most one request per product per week** per stored URL, enforced by a run-state file.
- **Polite fetches never use stealth**: no `impersonate`, no `stealthy_headers`, no stealth options in any polite code path; `test_no_evasion_code_is_present` on this lane checks the same token list as refs plus `impersonate`.
- **Unblock ladder:** when a configured-unblock seller (or a polite seller that turns out blocked, via the refs `is_blocked`) fails, escalate once per rung: Bright Data Web Unlocker → Browserbase (JS-heavy) → Evomi residential. One attempt per rung; a seller that fails all three is reported in the weekly run and skipped until it works again.
- **Browserbase on this lane** creates sessions with `solveCaptchas: true`, `advancedStealth: true`, `proxies: false`, `verified: false` — the exact opposite of the refs payload, which must stay untouched in `m3_pipeline/refs/crawl/browserbase.py`. Duplicate the payload builder into the prices package rather than parameterizing the refs one.
- **PriceObservation is consumed read-only** (`src/data/schemas.ts`): `{ amount, currency, seller, checked, url? }`. `checked` is the run date. `url` is stored only so the updater can recheck. If a schema change ever becomes necessary it goes through a `contract`-labeled PR.
- **Product photos ride along:** while on a product page, extract images (refs `extract_image_urls`) and `RefStore.ingest_bytes` them with subject `product-<part-id>` and crawl-style provenance; min side 800 px; robots checked on the polite tier. Lazy-import the refs package; `--no-images` skips it.
- **Sellers whose terms forbid automated access are `tier = "unblock"` by maintainer decision (ADR 0014); a seller can be `opted_out = true`.** Selector hints are calibrated on the first real run; wrong-looking prices are flagged, never silently trusted.
- **Secrets** (env only, `M3_` prefix, never logged, fakes in tests): `M3_BROWSERBASE_API_KEY`, `M3_BROWSERBASE_PROJECT_ID`, `M3_BRIGHTDATA_UNLOCKER_TOKEN` (plus zone/user fields as the current API needs — check docs.brightdata.com via Exa first and pin the payload semantics in tests), `M3_EVOMI_PROXY_URL` (embeds credentials; redact like the Browserbase `connectUrl`), `M3_EXA_API_KEY`. Never `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.
- **Spend ledger:** before any real paid call, a row in `docs/spend-ledger.md` with units (unlocker requests, Browserbase sessions, Evomi GB, Exa searches) even at $0 marginal. The weekly runner prints the units to paste.
- **Run state** lives in `<M3_WORK_DIR>/prices/`: `last-run.json` (per-URL fetch dates), `scrapling-store/` (adaptive selector storage), `candidates/<date>.json` (discover output). Torn `last-run.json` is tolerated like the refs skip log (drop torn tail, raise on middle corruption).
- Repo rules apply: conventional commits, stage by path, no `Claude-Session` trailers, `pnpm check:pipeline` exits 0 before every commit, tests reach no network beyond 127.0.0.1, gitleaks clean.

## Review Focus

Failure modes, most likely first. Each has a named test in its owning task.

1. **Wrong element extracted as the price** (a shipping cost, a "from" price, a related product). Per-seller CSS hints tried in order, then Scrapling adaptive match; the result must parse as money in the configured currency, be > 0, and move less than 10× from the last observation or be flagged. Task 3 `test_extraction_rejects_shipping_and_from_prices`, `test_price_jump_over_ten_x_is_flagged`.
2. **A blocked page read as available** (challenge HTML parsed for a price). The refs `is_blocked` runs on every page before extraction. Task 3 `test_blocked_page_is_never_extracted`.
3. **The 1-per-week invariant broken** by a rerun. Run-state checked before every fetch; a URL fetched this week is skipped even if the observation changed. Task 3 `test_rerun_within_the_week_skips_every_url`.
4. **Secrets or proxy URLs in logs** (Bright Data token, Browserbase `connectUrl`, Evomi credentials). Every log line passes a redact helper; tests pin no-credential-in-output for all three services. Tasks 2 and 6.
5. **Escalation spends money on sellers that are fine** (a transient 500 escalated to the unblocker). Only `is_blocked` pages escalate; HTTP 5xx retries once politely after 2× delay, then reports. Task 2 `test_server_error_is_retried_once_not_escalated`.
6. **YAML round-trip damage** in `prices apply` (comments lost, key order scrambled, options merged wrong). pyyaml round-trip with pinned key order on the prices list only; `check-data` must pass after apply. Task 4 `test_apply_preserves_everything_but_prices`.

## File Structure

```
pipeline/pricing.toml                                     seller config, first wave
pipeline/src/m3_pipeline/prices/{__init__,config,models,report}.py        Task 1
pipeline/src/m3_pipeline/prices/fetch/{__init__,brightdata,browserbase,evomi,tier}.py     Task 2
pipeline/src/m3_pipeline/prices/{extract,check,runstate}.py + tests       Task 3
pipeline/src/m3_pipeline/prices/apply.py + tests                            Task 4
pipeline/src/m3_pipeline/prices/{pr,discover,exa}.py + tests              Tasks 5-6
pipeline/src/m3_pipeline/prices/{week,cli}.py, tools/weekly-scrape.sh (or pnpm script), .claude/skills/m3-weekly-scrape/SKILL.md, docs/runbooks/weekly-scrape.md    Task 7
pipeline/tests/{test_prices_config,test_prices_fetch,test_prices_check,test_prices_apply,test_prices_pr,test_prices_discover,test_prices_week,test_prices_runbook,test_prices_e2e}.py
pipeline/tests/fixtures/prices/{turner-ok.html,ebay-ok.html,ebay-blocked.html,apex-vercel-checkpoint.html,...}   saved pages, trimmed
```

### Task 1: pricing.toml schema, loader, report models
**Files** (branch `feat/prices-config`): `pipeline/pricing.toml`, `pipeline/src/m3_pipeline/prices/{__init__,config,models,report}.py`, `pipeline/tests/test_prices_config.py`.
**Interfaces:**
```python
class Tier(Literal["polite", "unblock"])
@dataclass(frozen=True) class SellerConfig:
    id: str; base_url: str; tier: Tier; currency: str = "USD"
    price_selectors: tuple[str, ...] = ()   # CSS hints, tried in order
    image_min_side_px: int = 800; opted_out: bool = False; note: str = ""
@dataclass(frozen=True) class PricingConfig: user_agent: str; sellers: Mapping[str, SellerConfig]
class ConfigError(ValueError)
def load_pricing(path: Path, env: Mapping[str, str] | None = None) -> PricingConfig   # env M3_PRICES_USER_AGENT overrides
# models.py
@dataclass(frozen=True) class Observation: part_id: str; option_id: str | None; url: str; seller: str
    amount: Decimal; currency: str; checked: date   # PriceObservation-compatible; a to_yaml() method emits the schema's field order
# report.py
@dataclass class CheckReport: checked: int = 0; skipped_this_week: int = 0; blocked: list[str] = []; disallowed: list[str] = []
    failed: list[str] = []; flagged: list[str] = []; images_added: int = 0; unblock_used: dict[str, int] = field(...)  # service -> units
    def render(self) -> str   # the weekly table + units line for the ledger
```
Ship `pipeline/pricing.toml` with the first wave: polite — `turner-motorsports`, `ecs-tuning`, `fcp-euro`; unblock — `apexwheels` (known Vercel checkpoint, see the refs runbook), `ebay`, `amazon`. Selector hints empty until calibrated on the first real run; the note field says so.
- [ ] Steps: failing tests → `ModuleNotFoundError` → implement → green → `fix(prices)`… commit `feat(prices): add pricing config, seller tiers and report models`.
- [ ] Pinned tests: `test_tier_must_be_polite_or_unblock`, `test_opted_out_seller_parses`, `test_env_user_agent_overrides_toml`, `test_shipped_pricing_toml_parses_and_covers_the_first_wave` (asserts the six seller ids above), `test_observation_to_yaml_matches_price_observation_fields` (amount/currency/seller/checked/url in that order).

### Task 2: the fetch stack
**Files** (branch `feat/prices-fetch`): `pipeline/src/m3_pipeline/prices/fetch/{__init__,brightdata,browserbase,evomi,tier}.py`, `pipeline/tests/test_prices_fetch.py`.
**Interfaces:**
```python
# brightdata.py — check the current Web Unlocker API via Exa first; pin the payload semantics the tests assert
def brightdata_unlock(http: httpx.Client, url: str, *, token: str) -> UnlockResult   # success, html, status; token never in str/repr
def redact(text: str) -> str
# browserbase.py — prices' own payload builder, refs one untouched
def prices_session_payload(project_id: str, *, timeout_s: int = 900) -> dict[str, Any]
    # solveCaptchas True, advancedStealth True, proxies False, verified False
# evomi.py
def evomi_proxy_url(env: Mapping[str, str]) -> str   # from M3_EVOMI_PROXY_URL; MissingCredentials names the variable only
# tier.py
class PageFetchError(Exception): url: str; reason: str
def fetch_page(url: str, *, seller: SellerConfig, cfg: PricingConfig, http: httpx.Client,
               playwright_page_factory: Callable[[], ContextManager[PageFetcher]] | None,
               robots: RobotsCache, throttle: Throttle) -> FetchedPage
    # polite: per-hop robots + throttle like the refs engine fix; Playwright only when the seller needs JS
    # unblock: brightdata first; JS-heavy (config or challenge markers) -> browserbase; evomi last
@dataclass(frozen=True) class FetchedPage: html: str; final_url: str; status: int; via: Literal["polite", "brightdata", "browserbase", "evomi"]
```
- [ ] Commit `feat(prices): add polite fetch and the unblock ladder`.
- [ ] Pinned tests: `test_polite_fetch_checks_robots_per_hop`, `test_server_error_is_retried_once_not_escalated`, `test_blocked_polite_page_escalates_to_brightdata_once`, `test_js_heavy_goes_to_browserbase_with_captcha_and_stealth_on`, `test_evomi_is_the_last_rung`, `test_prices_session_payload_is_the_inverse_of_refs`, `test_no_evasion_code_is_present` (refs token list plus `impersonate`, scoped to `prices/fetch/`), `test_brightdata_token_and_evomi_url_never_logged`, `test_missing_credentials_name_variables_only`.

### Task 3: `prices check` — walk, fetch, extract, report
**Files** (branch `feat/prices-check`): `pipeline/src/m3_pipeline/prices/{extract,check,runstate}.py`, `pipeline/tests/{test_prices_check.py, fixtures/prices/*}`.
**Interfaces:**
```python
# runstate.py
class RunState: def __init__(self, path: Path) -> None; def fetched_this_week(self, url: str, today: date) -> bool; def mark(self, url: str, day: date) -> None; def save(self) -> None
    # torn tail dropped, middle corruption raises — same rules as the refs skip log
# extract.py
def extract_price(html: str, seller: SellerConfig, *, storage_dir: Path | None) -> ExtractedPrice | None
    # CSS hints in order, then Scrapling adaptive (auto_save into <work_dir>/prices/scrapling-store);
    # money regex per currency; is_blocked first; None when nothing parses
@dataclass(frozen=True) class ExtractedPrice: amount: Decimal; currency: str
# check.py
def check_prices(parts_dir: Path, *, cfg: PricingConfig, http: httpx.Client, store: RefStore | None,
                today: date, playwright_page_factory=None) -> CheckReport
    # walks data/parts/**: every price observation with a url, plus option-level prices
    # 1/product/week via RunState; blocked -> escalate (unblock tier sellers) or report; images ride along
```
CLI: `pipeline prices check [--no-images] [--seller <id>]`.
- [ ] Commit `feat(prices): add prices check with extraction, run state and image ride-along`.
- [ ] Pinned tests: `test_rerun_within_the_week_skips_every_url`, `test_blocked_page_is_never_extracted`, `test_extraction_rejects_shipping_and_from_prices` (fixture pages where a shipping span and a "from" price precede the real one), `test_price_jump_over_ten_x_is_flagged`, `test_option_prices_are_checked_their_own_urls`, `test_images_ride_along_into_product_subjects`, `test_torn_runstate_tail_is_dropped`, `test_report_renders_units_for_the_ledger`.

### Task 4: `prices apply`
**Files** (branch `feat/prices-apply`): `pipeline/src/m3_pipeline/prices/apply.py`, `pipeline/tests/test_prices_apply.py`.
**Interfaces:** `def apply_observations(parts_dir: Path, report: CheckReport, *, dry_run: bool = False) -> ApplyResult` — writes each observation into its part YAML (option list when the part has options), skipping a seller whose price is unchanged within 7 days; pyyaml round-trip with the prices list rewritten in schema field order; `ApplyResult.changed_files: list[Path]`.
- [ ] Commit `feat(prices): add prices apply`.
- [ ] Pinned tests: `test_apply_preserves_everything_but_prices` (comments in an unrelated key survive where pyyaml keeps them; all other keys and their order survive), `test_unchanged_within_seven_days_is_not_duplicated`, `test_apply_writes_option_prices_on_their_options`, `test_apply_then_check_data_passes` (runs `node tools/check-data.ts` on a fixture tree).

### Task 5: `prices pr`
**Files** (branch `feat/prices-pr`): `pipeline/src/m3_pipeline/prices/pr.py`, `pipeline/tests/test_prices_pr.py`.
**Interfaces:** `def open_pr(*, apply_result: ApplyResult, report: CheckReport, today: date, base: str = "main", runner_env: Mapping[str, str]) -> str | None` — creates `data/prices-<date>`, commits the changed files, `gh pr create` with a body containing the change table (old → new, >20 % and >10× jumps flagged) and the ledger units line. No `Claude-Session` trailers; `--no-pr` runs the flow without pushing (used by tests and dry runs).
- [ ] Commit `feat(prices): add prices pr with the weekly change table`.

### Task 6: `prices discover`
**Files** (branch `feat/prices-discover`): `pipeline/src/m3_pipeline/prices/{exa,discover}.py`, `pipeline/tests/test_prices_discover.py`.
**Interfaces:**
```python
# exa.py — check the current Exa API shape via Exa first
def exa_search(http: httpx.Client, *, query: str, api_key: str, limit: int = 5) -> list[SearchResult]  # key never logged
def discover_candidates(parts_dir: Path, cfg: PricingConfig, http: httpx.Client, *, today: date) -> Path
    # writes <work_dir>/prices/candidates/<date>.json: part id, seller, candidate urls, note
    # NEVER writes into data/; candidates become observations only through review
```
CLI: `pipeline prices discover [--part <id>]`.
- [ ] Commit `feat(prices): add candidate discovery via exa`.
- [ ] Pinned tests: `test_candidates_go_to_work_dir_never_data`, `test_exa_key_never_logged`, `test_discover_skips_opted_out_sellers`.

### Task 7: `prices week`, the runner and the skill
**Files** (branch `feat/prices-week`): `pipeline/src/m3_pipeline/prices/week.py` (+ `cli.py` wiring), root `package.json` script `"scrape:week": "uv run --project pipeline pipeline prices week"`, `.claude/skills/m3-weekly-scrape/SKILL.md`, `docs/runbooks/weekly-scrape.md`, `pipeline/tests/{test_prices_week,test_prices_runbook}.py`.
**Behavior:** `prices week` = check → apply → pr (each step skippable: `--no-apply`, `--no-pr`); prints the report, the ledger units line and the PR URL. The runbook mirrors `docs/runbooks/refs-collection.md`: setup, env var names, the tiers, what "blocked" means, the brief for another harness, and "what this deliberately won't do" (no stealth on the polite tier, no retry storms, no auto-writes from discover, robots.txt advisory only on the unblock tier).
- [ ] Commit `feat(prices): add weekly runner, skill and runbook`.
- [ ] Pinned tests: `test_week_runs_check_apply_pr_in_order` (fakes), `test_every_command_in_the_runbook_exists` (same pattern as `test_refs_runbook.py`), `test_runbook_states_the_posture_and_ledger_rules` (asserts "ADR 0014", "polite", "unblock", "robots", "spend", "one request per product").

### Task 8: end-to-end smoke
**Files** (branch `feat/prices-week`): `pipeline/tests/test_prices_e2e.py`. A local `Site` with two fake sellers (one polite, one that serves a challenge then succeeds through the fake unblocker), a fixture parts tree with one part and one option, fakes for Bright Data/Browserbase/Evomi injected: check → apply → `check-data` passes → report renders. No network.
- [ ] Commit `test(prices): add end-to-end smoke through check, apply and report`.

## Landing

Each task: `git switch -c <branch>` off the previous, `pnpm check:pipeline` exits 0 before the commit, push and open the PR per AGENTS.md (the orchestrator does the pushing after review). PR bodies carry the review section as PR #18 does.
