# 0009. Citations and the link policy

- **Status:** Accepted 2026-11-23
- **Date:** 2026-11-23

## Context

Every data value carries sources, and the site has to show them. The sources in `data/generations/e46.yaml` include Tier 2 retailer pages, and ADR 0008 forbids store links of any kind. The first `check:links` found anchors with a regex, so `href="&#104;ttps://shop.example"` and `href="https&#58;//shop.example/p"` passed, and only `<a>` was looked at: an `<area>`, a form action, an iframe or a `<base href>` could carry a store link or redirect every relative one. The final review found both gaps.

## Decision

- **A source renders as a plain-text citation:** publisher, title and accessed date, always as text.
- **Its `url` is a link only when its host is on `CITATION_HOSTS`** in `src/lib/link-policy.ts`: `archive.org`, `web.archive.org`, `newsroom.bmwgroup.com` (the BMW host the E46 file cites), `en.wikipedia.org` and `commons.wikimedia.org`. `isCitationLinkable(url)` decides: https, no credentials, exact host. A Tier 2 retailer is never linked.
- **`check:links` accepts the citation hosts** as well as its own allowlist. A test pins the list, so a host can't join with a one-line change.
- **`check:links` parses the HTML** with parse5 (8.1.1, pinned) instead of a regex. Entities are decoded, a quoted `>` stays in its value, the first of a repeated attribute wins, and `<noscript>` and `<template>` content is read.
- **It checks `a[href]`, `area[href]`, `form[action]` and `iframe[src]`,** and any `<base href>` is a violation, even one that points at the site.
- **A post-hydration island link test is a Phase 1 requirement.** The check reads built HTML, so it can't see a link a React island adds after hydration. Phase 1 adds a Playwright test that applies the same policy to the live DOM of every page with an island.

## Alternatives considered

- **Link every source:** rejected. A retailer's product page is a store link under another name (ADR 0008).
- **Show no URLs:** rejected. An archived copy or a BMW press page is how a reader checks a claim, and it isn't commerce.
- **Keep the regex and add cases:** rejected. Any hand-written scanner differs from a browser somewhere. A parser that follows the HTML standard reads the page as the browser does.
- **htmlparser2:** rejected. It is lenient where the standard is exact, and the exactness is the point.
- **Allow `*.wikipedia.org` or `www.archive.org`:** rejected. Exact hosts, as for the site allowlist.

## Consequences

- A reader who wants a retailer-hosted source searches for it by title and publisher. Archived copies, when they exist, are the better citation.
- Adding a citation host is a policy change: its own PR, a reason, and an edit to the pinned list in the test.
- Not covered: `formaction` on buttons and inputs, `<meta http-equiv="refresh">`, and links that scripts create. Add them when a page uses them. The island test above covers the last.
- parse5 is a dev dependency, and `check:links` reads every built page with it. The cost is a few milliseconds a page.
- No page renders citations yet. This sets the rule and the helper for Phase 1.
