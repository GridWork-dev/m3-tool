# Visual design

The site uses direction **B2, "pit garage"**, which the user chose on 2026-11-23 from three directions:

- A, an engineering drawing set
- B, a pit garage
- C, an owners' journal

[`b2-garage.html`](b2-garage.html) is the reference mock-up. It's one self-contained page with no build step. Open it in a browser.

## The direction

- **Dark only.** The ground is a studio floor. On the generation page and in the configurator, the 3D viewport is the hero.
- **Spec groups as tool-chest drawers.** The key figures sit on a yellow pit board.
- **The build sheet is a pale yellow paper "work order".** It shows the seller as plain text, the checked date, the tier badge, and a stamp on any price older than 60 days.
- **A known issue is a tech card on a pegboard.** Its sources carry tier labels.
- **Type:** Big Shoulders Display for headings and Geist for text, with tabular numerals everywhere.

## Tokens

The mock-up defines 66 design tokens as CSS custom properties at `:root`: color with its role, type scale, spacing, radii and shadows. The "Tokens" section at the bottom of the page lists them in a table, with the contrast ratio for each color pair. Phase 1 lifts them into the site's Tailwind theme. Change a token there, not in a copy.

## What the mock-up already settles

- **States:**
  - an empty build sheet and a first-visit prompt
  - a stale price
  - an unverified issue
  - the 3D viewport while loading, and when WebGPU is unavailable
- **Phone, at 390 px:** the viewport comes first. Categories, parts, and paint and quality sit in a bottom sheet with tabs, and the build total stays pinned.
- **Accessibility:**
  - WCAG AA contrast on the dark, yellow and paper surfaces
  - a visible focus ring on every stop
  - 44 px tap targets on phone
  - the camera, paint and quality toggles work without JavaScript

## Still to do

- **Replace the hero's car outline.** It's a generic two-door drawn to the E46's length, wheelbase and height. The Phase 0.6 spike's proportion-checked side view will provide the outline to trace.
- **Fill in the placeholders.** Variants, parts, prices and issue text on the page are labelled placeholders, not data.

## Rules the design keeps

These are from `AGENTS.md`:

- no BMW logos, roundels, M stripes or badges
- no store or affiliate links; sellers and sources are plain text unless `isCitationLinkable` allows a link
- the footer notice, word for word
- no car photos in the UI
