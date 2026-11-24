# 0014. Price and product-page scraping may unblock

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

The design spec's price updater (section 13) and the legal standard started from the most defensive posture: respect robots.txt and site terms, and a source that blocks access, or whose terms forbid automated access, is dropped, not worked around. Reference-photo collection keeps that posture because the exposure there is copyright in the images themselves.

Price observations are different in kind: a price is a fact, fetched at most once per product per week, stored with a seller and a checked date, and never rendered as a link. Marketplace sellers (eBay, Amazon), whose terms forbid automated access, hold much of the useful price signal for aftermarket parts. The maintainer already owns a Browserbase Developer subscription, Bright Data credit and Evomi residential bandwidth.

## Decision

- **Two postures, by lane.**
  - **Reference and car photo collection** is unchanged: respect robots.txt, rate-limit, generic user agent, blocked pages logged and skipped, no bot-blocking workarounds ([legal standard](../standards/legal.md)).
  - **Price and product-page scraping** may unblock: when a seller blocks us or a marketplace's terms forbid automated access, the fetcher retries through an unblocking service instead of dropping the source.
- The unblock stack, in order: **Bright Data Web Unlocker** first; **Browserbase (Developer plan) with captcha solving and stealth on** for JavaScript-heavy pages; **Evomi residential** as a spare.
- The polite tier still runs first: plain local fetching (httpx, Scrapling `Fetcher` without stealth, Playwright) with our user agent at human pace.
- robots.txt is advisory on the unblock tier: polite sources are still checked against it; marketplace and blocked sellers on the unblock tier are not.
- The maintainer accepts the terms-of-service risk for price facts on those sellers. This is a deliberate exception to "a seller whose terms forbid automated access is skipped", and it never extends to reference-photo collection.
- Product photos may ride the price lane's fetcher, since they come from the same product pages; they land in the private refs store either way.
- Usage is logged in `docs/spend-ledger.md` as units (Web Unlocker requests, browser hours, GB), even when the marginal cost is $0 under owned plans.

## Alternatives considered

- **Strict polite-only everywhere:** rejected for prices by the maintainer. Marketplace price coverage matters more than the low, factual risk.
- **Per-seller opt-in as the default:** rejected. Too much bookkeeping for a one-maintainer project. A seller can still be opted out in `pipeline/pricing.toml`.
- **Unblocking reference photos too:** rejected. Photo copyright is the bigger exposure, and Wikimedia Commons covers most needs politely.

## Consequences

- `docs/standards/legal.md` scopes "skip sellers who forbid automated access" to reference photos; spec section 13 is amended to match.
- Agents building or running the price scrapers may use unblocking without asking again; they may not extend it to reference-photo collection.
- A blocked price source is retried through the unblocker; one that fails even then is reported in the weekly run and skipped until it works again.
- The weekly run is local first: a script plus the `m3-weekly-scrape` skill. A scheduled GitHub Action may replace it later, as its own decision.
- This is a working standard, not legal advice.
