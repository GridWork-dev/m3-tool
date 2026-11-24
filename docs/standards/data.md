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
| `generations` | `Generation` | Chassis, production years, engines, bodies and their sources, dimensions per body, driver eye point, stock wheel fitment per axle |
| `variants` | `Variant` | Market, body, transmissions, packages, paints, factory wheels, interiors, which assets render it (base car, interior, body modules) |
| `parts` | `Part` | A product or a generic tier, with fitment attributes, options, prices, labor, 3D model (and the body modules it replaces), sources |
| `maintenance` | `MaintenanceItem` | A service interval with parts, fluids, cost ranges and a buyer's inspection note |
| `issues` | `KnownIssue` | A known problem with symptoms, cause, fix, cost range and how common it is |

The schemas reject keys they don't list, so a typo like `brnad:` is an error instead of a silently dropped field. They also reject a few shapes the types alone allow:

- A part with no `brand` has no prices, at part level or in any option.
- A visible part has a `model`. A part that isn't visible has none.
- A part with `options` keeps its `attributes` and `prices` on each option, with unique option ids.
- A model's `replaces` names at least one body module, each at most once, and only from the four in `BODY_MODULES`. A variant's `render.modules` has only those four as keys.
- A part's `attributes.kind` matches its category: `wheel` and `hub-ring` go with `wheels`, `tire` with `tires`, `brake-kit` with `brakes`, `suspension` with `suspension`.
- `inspectWhenBuying: true` needs a non-empty `howToCheck`.
- A maintenance interval has `miles`, `months` or both.
- A measured driver eye point has sources. An estimated one may have none. It is the one sourceless exception the schema names, and its `note` says it is an estimate. (A generic part has no sources of its own either, because it is a computed tier, not a claim.)
- Required text (names, titles, sellers, publishers) must not be empty or only whitespace. The value is kept as written, not trimmed.
- A `KnownIssue` with a `fix` also has a `cost`. Without a `fix` the `cost` is optional (see "Safety advice needs evidence").
- Dimensions are keyed by bodies the generation lists, and there's at least one.

### Body module swaps

The base car is split into four swappable modules: `bumper_front`, `bumper_rear`, `trunk_lid` and `roof`. Their names are exact, and the list is `BODY_MODULES` in [`src/lib/asset-contract.ts`](../../src/lib/asset-contract.ts). Two fields use them, and both rest on the same swap: the configurator hides the base car's module and shows the replacement asset at the car origin. How the models are built is in [the 3D asset standard](3d-assets.md#body-modules).

**Factory variants: `render.modules` on a variant.** It names the module asset the variant uses in place of the base car's own. A module left out keeps the base car's.

```yaml
render:
  baseAsset: e46-coupe-body
  interiorAsset: e46-coupe-interior
  modules:
    trunk_lid: e46-csl-trunk-lid
    roof: e46-csl-roof
```

The US coupe leaves `modules` out and renders the base car as it is. An empty `modules: {}` means the same thing: the defaults. Each value is the id of a `body-module` asset. The keys are body modules only: `hood: x` is an error.

**Aftermarket body parts: `replaces` on a part's `model`.** A bumper or trunk lid that replaces the stock one lists what it takes over. It sits on both kinds of model, `{ asset }` and `{ standIn }`.

```yaml
model:
  asset: example-ducktail-trunk-lid
  replaces: [trunk_lid]
```

`replaces` has at least one module, and no module twice. Leave it out for a part that doesn't replace anything, such as a wheel. A part that isn't visible has no model, so it has no `replaces`.

A `standIn` with `replaces` uses a car-frame stand-in style for those modules, as a `body-module` asset does. The UI still labels it "3D look approximate".

**One mechanism for both.** A CSL's trunk lid and an aftermarket trunk lid are each a `body-module` asset that replaces `trunk_lid`. The variant picks the first, and a build picks the second. One `body-module` asset may cover several modules, such as a CSL roof and trunk lid. A variant names its id under each module it covers, and a part lists each of those modules in `replaces`. The asset's root node then spans them all, in the base car's frame, and its largest dimension must stay within the 4.0 m ceiling for the kind, so a front and rear bumper pair is too long for one asset. An asset listed under several modules is shown once.

The schemas don't say which one wins when a build's part and its variant name the same module: the configurator decides that, and the rule isn't settled yet (open item 5 in spec section 16).

Dates are calendar dates, `YYYY-MM-DD`, such as `2026-11-23`, with no time of day. Write them unquoted or quoted: both parse to the same instant, midnight UTC. A time (`2026-11-23T10:30`), an impossible date (`2026-02-31`) or a Date with a time of day is an error, because a time without a zone means different instants on different machines. The year is 1900 to 2100, so a swapped digit or a missing century is an error, and a `source`'s `accessed` date or a price's `checked` date can't be more than a day after today in UTC (`future-date`, below). The day of slack is for contributors east of UTC, who write their own date while it is still yesterday in UTC.

**`check:data` is the gate for dates**. Astro's content loader turns an unquoted YAML date into a `Date` before the schema runs, so it can accept a value that `check:data`'s own loader, which keeps the text and checks it, refuses. Run `check:data` before every build that ships: `pnpm check` does, and CI runs `pnpm check`. The deploy workflow's build job must run it before it builds too.

The `fitment.*.envelopes` list may be empty. The Phase 1 rules then report "fitment unknown" instead of guessing. Mounting geometry is in mm from the hub face: `inner = widthIn * 25.4 / 2 + offsetMm` and `outer = widthIn * 25.4 / 2 - offsetMm`.

### Sources

Every `Source` has a `title`, `publisher`, `tier` (1 to 3) and `accessed` date, and optionally an `https` `url` and a `note`.

- **Cite what you opened.** Record the date you read it as `accessed`. Never invent a source or a URL.
- **Use `note` to say what the source supports,** with the page or table, so a reviewer can find the number.
- **Say so when a copy is not the original.** An archived or mirrored copy goes in the `url`, and the `note` says it is a copy.
- **A generation's own `sources`** (at least one) cover its name, chassis, years, engines and bodies. Its dimensions, eye point and fitment carry their own.

### Citations

A source is shown as a citation. The page always renders its **publisher, title and accessed date as text**. Its `url` becomes a link only when the URL is `https` and its host is exactly one of `CITATION_HOSTS` in [`src/lib/link-policy.ts`](../../src/lib/link-policy.ts): `archive.org`, `web.archive.org`, `newsroom.bmwgroup.com`, `en.wikipedia.org` and `commons.wikimedia.org`. Call `isCitationLinkable(url)` to decide. Every other URL stays text, so a Tier 2 retailer is never linked, and a reader who wants the page searches for it. `pnpm check:links` accepts those five hosts, and nothing else beyond its own allowlist.

The list is short on purpose: non-commercial references only. Adding a host is a policy change, with its own PR and a reason ([ADR 0009](../decisions/0009-citations-and-link-policy.md)). When a source is a retailer's page, `note` still says what it supports, and an archived copy on `archive.org` is the better thing to link when one exists.

## Source tiers

**Tier 1:** BMW technical documents (owner's manuals, factory service intervals, service bulletins), manufacturer product pages and install guides.

**Tier 2:** established specialist retailers' tech articles, reputable publications, well-known specialist shops.

**Tier 3:** forums and owner reports.

### What counts as verified

Maintenance intervals, and fixes for known issues, need one Tier 1 source or two independent Tier 2 sources to be marked `verified: true`.

Tier 3 alone is enough for symptoms and "how common". The entry stays `verified: false`, and the UI shows an "unverified" badge.

`verified` means the same thing everywhere it appears. A part with `verified: true` needs the same one Tier 1 source or two independent Tier 2 sources, and a manufacturer product page counts as Tier 1. `check-data` reports a verified part, maintenance item or issue that falls short as `verified-without-tier`.

"Independent" means different publishers. `check-data` compares publisher names after trimming, collapsing spaces and ignoring case, so `Shop A` and ` shop  a ` are one publisher, and two articles from it count once.

### Safety advice needs evidence

Safety advice never rests on a forum post alone. This is weaker than `verified` and applies even to an unverified entry:

- **A maintenance item** needs at least one Tier 1 or Tier 2 source.
- **A known issue's `fix`** is optional. When it's there, the issue needs at least one Tier 1 or Tier 2 source, and a `cost`.
- **A known issue without a `fix`** publishes its symptoms, cause and how common it is, and Tier 3 sources are enough for that. Its `cost` is optional.

`check-data` reports a maintenance item, or an issue with a fix, that has only Tier 3 sources as `safety-advice-without-evidence`. To fix it, add a Tier 1 or Tier 2 source, or (for an issue) remove the `fix` and its `cost` until there is one. `prevention` isn't checked by a rule, so the data verifier and the user's spot-check on `safety` PRs look at it.

### Review

Every data PR gets an Opus data verifier, which re-reads the cited sources and checks the claims against them.

PRs that touch `data/maintenance/` or `data/issues/` get the `safety` label. The user spot-checks those.

## Prices

A price observation is `{ amount, currency, seller, checked, url? }`, for real products only. `checked` can't be more than a day after today (UTC).

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

It prints one `<file>: <code>: <message>` line per problem, exits 1 if there are any, and prints nothing when the data is clean. `pnpm check` runs it. "Today" for `future-date` is the current date in UTC; tests pass their own date to `checkDataSet`.

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
| `verified-without-tier` | A part, maintenance item or issue is `verified: true` but fails the rule above | Add the sources, or set `verified: false` |
| `multiple-generic-in-category` | A generation has two brandless parts in one category | Keep one |
| `safety-advice-without-evidence` | A maintenance item, or a known issue with a `fix`, has no Tier 1 or Tier 2 source | Add a source, or remove the issue's `fix` and `cost` |
| `variant-body-not-in-generation` | A variant's `body` isn't in its generation's `bodies` | Fix the body, or add it to the generation |
| `variant-years-outside-generation` | A variant's `years` aren't within its generation's `years` | Fix the years |
| `part-years-outside-generation` | A part's `fits.years` aren't within its generation's `years` | Fix the years |
| `part-bodies-outside-generation` | A part's `fits.bodies` names a body its generation doesn't build | Fix the bodies |
| `fits-list-empty` | A part's `fits.bodies` or `fits.transmissions` is `[]`, which fits nothing | List at least one, or leave the field out to fit all |
| `unknown-engine` | A maintenance item or issue names an `engine` that isn't one of its generation's engine codes | Fix the code, or leave `engine` out for every engine |
| `future-date` | A source's `accessed` or a price's `checked` is more than a day after today (UTC) | Fix the date |
