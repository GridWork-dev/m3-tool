# 0008. No commerce, no store links, no logos

- **Status:** Accepted 2026-11-23. The link allowlist is extended for citations by [0009](0009-citations-and-link-policy.md).
- **Date:** 2026-11-23

## Context

Real named aftermarket products and BMW's own marks are the two places a free fan project can slide into commerce or into trademark trouble. The tool's value is pulling together knowledge that is spread across retailer sites, parts catalogs and forum threads. It doesn't sell anything and doesn't link to stores. "BMW" and "M3" are BMW AG's trademarks.

The 3D models show real cars and products that look like real products, including wheel designs that may be protected. That is lower risk for a free tool that sells nothing, but not zero.

## Decision

- **No affiliate, ad, sponsored or store links of any kind.** A price observation's `url` is stored so the updater can check the price again, and it is never rendered as a link.
- **`pnpm check:links` fails the build** on any external link outside a short allowlist in `src/lib/link-policy.ts`: `github.com`, `creativecommons.org`, `opensource.org` and `commons.wikimedia.org`. Adding a host is a change to the policy, so it gets its own PR and a reason. A protocol-relative link such as `//shop.example` counts as external.
- **No BMW marks anywhere,** in the UI, models, textures or screenshots: the roundel (including the steering wheel and gauges), the M logo, and badges on the grille, wheel caps and trunk. A plain cap, or none, replaces a logo on a wheel center cap.
- **Name a real product in text only.** A part page says "Brand Product". Its logo is as forbidden as BMW's.
- **"BMW" and "M3" only describe the car.** The footer and `/about` carry this notice word for word:
  `Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.`
- **The site is `noindex` until the public beta** (`PUBLIC_INDEXABLE=true` at build time turns it off). The public name and domain will leave out BMW and M3.
- **Every price has a seller and a checked date.** The UI shows the range from the last 90 days and marks a price stale after 60.

## Alternatives considered

- **Affiliate links or ads:** rejected. The user's decision is free, no selling and no store links. Hosting stays at $0 a month on free tiers.
- **Linking a price to its source page:** rejected. It is a store link under another name.
- **Showing logos on real products, such as wheel center caps:** rejected. Logos are marks, and the product's mark is treated like BMW's.
- **Paraphrasing the notice or putting it behind a click:** rejected. The e2e smoke test checks the core sentence only, so "word for word" is a review rule.

## Consequences

- A visitor can't click from a price to the seller. The seller name and checked date are shown, and that is all.
- Credits link only to allowlisted hosts. A new source of credits that needs another host needs a policy PR.
- Badges come off generated models: the cleanup stage removes badge meshes and inpaints the texture, and removes the roundel on the steering wheel and gauges.
- The asset validator can't see a logo. The vision critic and the human review in `/lab` check for them, and a PR that adds a model says so in its description.
- Breaking this rule is a failure even if the tool works. The anti-goals in the spec say so.
- This is a working standard, not legal advice. Follow `docs/standards/legal.md`.
