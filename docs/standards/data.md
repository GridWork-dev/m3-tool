# Data standard

Everything under `data/` is published on the site and licensed CC BY-SA 4.0 (`DATA_LICENSE`). Treat every value as a public claim: cite it, date it, and don't add a value you haven't checked against a source you opened.

Run `pnpm check:data` before you push. It validates every file and runs the cross-file checks (see "Checking your data").

## Layout and ids

One entry per YAML file.

```
data/
  generations/<id>.yaml
  variants/<generation>/<id>.yaml
  parts/<generation>/<id>.yaml
  maintenance/<generation>/<id>.yaml
  issues/<generation>/<id>.yaml
```

- **Ids are kebab-case:** `^[a-z0-9]+(-[a-z0-9]+)*$`, such as `e46` or `e46-us-coupe`. Lowercase letters and digits, joined by single hyphens.
- **Ids are stable and never reused.** Other files, saved builds and URLs point at them. Never reuse an id for something else.
- **A file's stem equals its `id`.** `parts/e46/ohlins-road-track.yaml` holds the part with `id: ohlins-road-track`.
- **Ids are unique per collection, across generations.** Part ids are looked up without a generation, so two parts can't share one.
- **The directory names the generation.** A file under `parts/e46/` has `fits.generation: e46`. Variants, maintenance items and issues use their `generation` field the same way.
- **Enum values are kebab-case too.** A known issue's frequency is `very-common` in YAML. The UI renders it with a space.

## Schemas

The schemas in [`src/data/schemas.ts`](../../src/data/schemas.ts) are the contract. Read them for exact fields, and keep this page for the rules they can't express.

| Collection | Schema | What it holds |
|---|---|---|
| `generations` | `Generation` | Chassis, production years, engines, bodies, dimensions per body, driver eye point, stock wheel fitment per axle |
| `variants` | `Variant` | Market, body, transmissions, packages, paints, factory wheels, interiors, which asset renders it |
| `parts` | `Part` | A product or a generic tier, with fitment attributes, options, prices, labor, 3D model, sources |
| `maintenance` | `MaintenanceItem` | A service interval with parts, fluids, cost ranges and a buyer's inspection note |
| `issues` | `KnownIssue` | A known problem with symptoms, cause, fix, cost range and how common it is |

The schemas reject keys they don't list, so a typo like `brnad:` is an error instead of a silently dropped field. They also reject a few shapes the types alone allow:

- A part with no `brand` has no prices, at part level or in any option.
- A visible part has a `model`. A part that isn't visible has none.
- A part with `options` keeps its `attributes` and `prices` on each option, with unique option ids.
- A part's `attributes.kind` matches its category: `wheel` and `hub-ring` go with `wheels`, `tire` with `tires`, `brake-kit` with `brakes`, `suspension` with `suspension`.
- `inspectWhenBuying: true` needs a non-empty `howToCheck`.
- A maintenance interval has `miles`, `months` or both.
- A measured driver eye point has sources. An estimated one may have none.
- Dimensions are keyed by bodies the generation lists, and there's at least one.

Dates are ISO strings such as `2026-11-23`. Write them unquoted or quoted: both parse to the same instant.

The `fitment.*.envelopes` list may be empty. The Phase 1 rules then report "fitment unknown" instead of guessing. Mounting geometry is in mm from the hub face: `inner = widthIn * 25.4 / 2 + offsetMm` and `outer = widthIn * 25.4 / 2 - offsetMm`.

### Sources

Every `Source` has a `title`, `publisher`, `tier` (1 to 3) and `accessed` date, and optionally an `https` `url` and a `note`.

- **Cite what you opened.** Record the date you read it as `accessed`. Never invent a source or a URL.
- **Use `note` to say what the source supports,** with the page or table, so a reviewer can find the number.
- **Say so when a copy is not the original.** An archived or mirrored copy goes in the `url`, and the `note` says it is a copy.
- **Fields without a place for sources** (such as a generation's name and years) get a comment in the YAML naming the source.

## Source tiers

**Tier 1:** BMW technical documents (owner's manuals, factory service intervals, service bulletins), manufacturer product pages and install guides.

**Tier 2:** established specialist retailers' tech articles, reputable publications, well-known specialist shops.

**Tier 3:** forums and owner reports.

### What counts as verified

Maintenance intervals, and fixes for known issues, need one Tier 1 source or two independent Tier 2 sources to be marked `verified: true`.

Tier 3 alone is enough for symptoms and "how common". The entry stays `verified: false`, and the UI shows an "unverified" badge.

"Independent" means different publishers. `check-data` compares publisher names after trimming, collapsing spaces and ignoring case, so `Shop A` and ` shop  a ` are one publisher, and two articles from it count once.

### Review

Every data PR gets an Opus data verifier, which re-reads the cited sources and checks the claims against them.

PRs that touch `data/maintenance/` or `data/issues/` get the `safety` label. The user spot-checks those.

## Prices

A price observation is `{ amount, currency, seller, checked, url? }`, for real products only.

- **`seller` and `checked` are required.** A price without both is rejected.
- **`url` is stored only so the updater can check the price again.** Never render it as a link: the site has no affiliate, ad or store links of any kind, and `check:links` fails the build if one appears.
- **The UI shows the range from the last 90 days** and marks it stale after 60 days.
- **Prices live on options when a part has them,** one list per size or variant.

### The generic tier is computed

Each category gets one generic part with no brand, so every build can get an estimate. Its price is calculated: the minimum low and maximum high across that category's current real-product ranges.

So never hand-price a generic part. A part without a `brand` can't carry prices, and `check-data` allows one generic part per category per generation.

### Collecting starting prices

Before the Phase 3 updater, agents collect starting prices from manufacturer list prices and retailer product pages, at normal browsing pace: one visit per product, recorded with the date.

A seller whose terms forbid automated access is skipped.

## Samples are fixtures

Spec section 15 asks for sample entries. Those live under `tests/fixtures/data/`, never under `data/`. Fixture ids start with `fixture-` and the brand is `Fixture Co`, so none of it can be mistaken for real data. Anything in `data/` is published, so it carries real sourced values only.

## Checking your data

```sh
pnpm check:data                       # same as: node tools/check-data.ts data
node tools/check-data.ts <directory>  # any directory with the same layout
```

It prints one `<file>: <code>: <message>` line per problem, exits 1 if there are any, and prints nothing when the data is clean. `pnpm check` runs it.

| Code | Meaning | Fix |
|---|---|---|
| `schema` | The file isn't valid YAML, doesn't match its schema (the message starts with the field path), or ends in `.yml` instead of `.yaml` | Fix the field, or rename the file |
| `duplicate-id` | Two files in one collection share an id | Pick a new id for the newer entry |
| `id-filename-mismatch` | The file stem differs from the `id` | Rename the file or fix the id |
| `unknown-generation` | The entry names a generation with no file in `generations/` | Fix the name, or add the generation first |
| `directory-generation-mismatch` | The directory differs from the entry's generation, or the file sits outside the layout above | Move the file |
| `unknown-ref` | `requires` or `conflicts` names a part that doesn't exist | Fix the id, or add the part |
| `self-ref` | A part lists itself in `requires` or `conflicts` | Remove it |
| `requires-conflicts-overlap` | The same id is in both `requires` and `conflicts` | Keep it in one |
| `verified-without-tier` | A verified maintenance item or issue fails the rule above | Add the sources, or set `verified: false` |
| `multiple-generic-in-category` | A generation has two brandless parts in one category | Keep one |
