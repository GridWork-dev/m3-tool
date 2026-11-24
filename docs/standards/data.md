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
| `generations` | `Generation` | Chassis, production years, engines, bodies and their sources, dimensions per body, driver eye point, stock wheel fitment per axle, and which values are unverified |
| `variants` | `Variant` | Market, body, transmissions, packages, paints, factory wheels, interiors, which assets render it (base car, interior, body modules), and which values are unverified |
| `parts` | `Part` | A product or a generic tier, with fitment attributes, options, prices, labor, 3D model (and the body modules it replaces), sources |
| `maintenance` | `MaintenanceItem` | A service with its interval (miles, months, triggers, or a mix), the markets and model years its sources cover, parts, fluids, an optional cost range and a buyer's inspection note |
| `issues` | `KnownIssue` | A known problem with the markets and model years its sources cover, symptoms, cause, an optional fix, an optional cost range and how common it is |

The schemas reject keys they don't list, so a typo like `brnad:` is an error instead of a silently dropped field. They also reject a few shapes the types alone allow:

- A part with no `brand` has no prices, at part level or in any option.
- A visible part has a `model`. A part that isn't visible has none.
- A part with `options` keeps its `attributes` and `prices` on each option, with unique option ids.
- A model's `replaces` names at least one body module, each at most once, and only from the four in `BODY_MODULES`. A variant's `render.modules` has only those four as keys.
- A part's `attributes.kind` matches its category: `wheel` and `hub-ring` go with `wheels`, `tire` with `tires`, `brake-kit` with `brakes`, `suspension` with `suspension`.
- `inspectWhenBuying: true` needs a non-empty `howToCheck`.
- A maintenance interval has at least one of `miles`, `months` or `triggers`, and `triggers` is a non-empty list with no repeats (see "Maintenance intervals"). A maintenance item's or known issue's `markets`, when present, is a non-empty list of `us` or `euro` with no repeats (see "Markets"). Their `modelYears`, when present, is a `[from, to]` pair of whole years from 1985 to 2035, with `from` not after `to` (see "Model years").
- A measured driver eye point has sources. An estimated one may have none, and its `note` says it is an estimate. Labor estimates are another sourceless exception the schema names (see "Labor estimates"), and a paint's display colour (`baseColor`) is a third: it is a render value, not a fact about the car, so it needs no source, and the variant file's comment says how each value was picked (a paint's code, name and the markets and variants that offered it are facts and still need sources). (A generic part has no sources of its own either, because it is a computed tier, not a claim, and so its labor is an estimate.)
- A part's `labor` always says whether it is an estimate: `estimated` is `true` or `false`, written out, with no default. Labor with `estimated: false` needs at least one source on the part.
- Required text (names, titles, sellers, publishers) must not be empty or only whitespace. The value is kept as written, not trimmed.
- A `KnownIssue`'s `fix` and `cost` are each optional. A fix needs a Tier 1 or Tier 2 source but no cost (see "Safety advice needs evidence" and "Costs that are absent"). A maintenance item's `cost` is optional too.
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
- **A third-party copy of a manufacturer's document is Tier 1 only if all of these hold** (ruling R77). A copy that fails one is Tier 2.
  1. It is complete and not retyped: the whole document, with the manufacturer's identifiers intact (number, date or revision, issuer, model range), and the passages you rely on are the copy's own text (the original file, a scan or a faithful print), not re-rendered or retyped.
  2. The `note` names the host and says what is missing.
  3. The document's number and scope are corroborated by an independent Tier 1 or Tier 2 source.
     - Test 3 is also met when all of these hold (ruling R84): the copy is the issuer's own native file (live text, not a scan or a retype); it carries the issuer's own identification line and document number; the number fits the issuer's numbering sequence, as the issuer's other documents show; and an independent Tier 1 document confirms what kind of document it is and which market it serves. The `note` states each of these. The other tests stay as they are.
  4. The `url` is an existing archive.org snapshot, if one exists. Don't create snapshots. A copy on a vendor's server is neither linkable nor stable, so when there is no snapshot the note says so.
  A safety value that rests on a copy alone says so in the entry.
- **A cost is published only under the label its source states** (ruling R78; see "Costs that are absent").
- **A generation's own `sources`** (at least one) cover its name, chassis, years, engines and bodies. Its dimensions, eye point and fitment carry their own.

### Citations

A source is shown as a citation. The page always renders its **publisher, title and accessed date as text**. Its `url` becomes a link only when the URL is `https` and its host is exactly one of `CITATION_HOSTS` in [`src/lib/link-policy.ts`](../../src/lib/link-policy.ts): `archive.org`, `web.archive.org`, `newsroom.bmwgroup.com`, `en.wikipedia.org` and `commons.wikimedia.org`. Call `isCitationLinkable(url)` to decide. Every other URL stays text, so a Tier 2 retailer is never linked, and a reader who wants the page searches for it. `pnpm check:links` accepts those five hosts, and nothing else beyond its own allowlist.

The list is short on purpose: non-commercial references only. Adding a host is a policy change, with its own PR and a reason ([ADR 0009](../decisions/0009-citations-and-link-policy.md)). When a source is a retailer's page, `note` still says what it supports, and an archived copy on `archive.org` is the better thing to link when one exists.

### Labor estimates

Install hours for most parts can't be traced to a Tier 1 or Tier 2 source, but the build sheet needs a number. So `labor` may be an explicit estimate: `estimated: true`, no source needed, and the site labels the hours "estimated" wherever it shows them. This sits beside the estimated driver eye point as a named sourceless exception.

- **`estimated: true`:** the hours need no source and don't count toward `verified`. A part whose sizes and fitment rest on a Tier 1 product page can be `verified: true` with estimated labor, because the rule reads the part's sources only. Say in a comment in the file what the estimate rests on.
- **`estimated: false`:** the hours come from the part's `sources` (an install guide, a published labor time). The schema needs at least one source on the part, and the data verifier checks the hours against it. A generic part has no sources of its own, so its labor is always `estimated: true`.
- Don't set `estimated: false` to avoid the label. The label tells the reader which hours are a guess.

## Source tiers

**Tier 1:** BMW technical documents (owner's manuals, factory service intervals, service bulletins), manufacturer product pages and install guides.

**Tier 2:** established specialist retailers' tech articles, reputable publications, well-known specialist shops.

**Tier 3:** forums and owner reports.

A marketplace's staffed editorial content (reviews, news) is Tier 2, and its listings and fitment lookups are Tier 3.

### What counts as verified

Maintenance intervals, and fixes for known issues, need one Tier 1 source or two independent Tier 2 sources to be marked `verified: true`.

Tier 3 alone is enough for symptoms and "how common". The entry stays `verified: false`, and the UI shows an "unverified" badge.

`verified` means the same thing everywhere it appears. A part with `verified: true` needs the same one Tier 1 source or two independent Tier 2 sources, and a manufacturer product page counts as Tier 1. `check-data` reports a verified part, maintenance item or issue that falls short as `verified-without-tier`.

"Independent" means different publishers. `check-data` compares publisher names after trimming, collapsing spaces and ignoring case, so `Shop A` and ` shop  a ` are one publisher, and two articles from it count once.

A model-wide statement in a Tier 1 source, or in two Tier 2 sources from different publishers, covers every variant it does not explicitly exclude, and a document for one market covers that market only.

- **A value that a Tier 1 one-market document states covers every market** when an independent Tier 1 document that speaks for all markets says the thing the value names is the same across them (ruling R85). Example: BMW North America's service bulletin SI B 11 04 04 (a US document) names the engine code `S54B32`, and BMW Group's twenty-years press kit (an international document from another publisher) says "One engine for all countries." of the 3,246 cc straight-six, so the code is verified for every market. R85 covers values in generations and variants. It never widens `markets` on a maintenance item or a known issue: a schedule or a fault can differ by market even when the part is the same, so those follow "Markets".

### Unverified values in variants and generations

A part, maintenance item or issue is verified or not as a whole (`verified`). A variant or a generation is different: most of the file meets the rule (one Tier 1 source, or two independent Tier 2 sources), and a few values fall short, such as a paint's code, a wheel offset or the CSL's end year. List those in the file's optional `unverified` field, as paths:

```yaml
unverified:
  - paints.A08.code
  - factoryWheels.optional-19.rear.offsetMm
```

A path says that the value it names, and everything under it, is below the rule. Leave the field out when nothing is. Pages that render these fields show a per-value "unverified" marker, taken from this field and not from the comments. A value is covered, and gets the marker, when its own path is listed, or the path of an object or element above it.

**Path grammar.** A path is dot-separated keys, from the top of the file down to one value. A key is letters, digits, `-` and `_`. Ids already fit, and the schema holds paint and engine codes to the same set, so every element can be named.

- **Fields and record keys** are written as in the file: `fitment.front.stock.offsetMm`, `dimensions.coupe.lengthMm`, `render.modules.trunk_lid`.
- **A list element is named by its `id`, or by its `code`** (paints and engines), never by its position, so reordering a list can't move a mark: `factoryWheels.optional-19.front.offsetMm`, `paints.A08.code`.
- **A fixed-length list names its values by position, from 0.** Only `years` is one: `years.1` is the end year.
- **A list with no key** (`transmissions`, `sources`) is named whole, because nothing stable tells its elements apart.
- **A path may stop at an object, a list or an element.** It then covers everything under it: `paints.A08` covers that paint's code, name, finish and base colour, and its place in the list.

**Choose the smallest existing field that carries the claim:**

- A claim about one value is that value's path: `paints.A08.code`.
- A claim carried by text inside a field is the path of the field that carries it. The label "Style 163M" is part of a wheel's `name`, so the path is `factoryWheels.competition-19-style-163m.name`. A leather colour appears in both `name` and `color`, so list both.
- A claim that a variant offers something (a paint's availability) is the path of the element, such as `paints.A08`: "this paint's presence on this variant is unverified". The path covers the whole element, so it can mark more than the claim. That is the safe direction.
- A claim about something with no field of its own is the path of the field that holds the text. A package has no years field, so its dates are in its `summary`, and `packages.competition-package.summary` marks them.
- A claim with no field and no element to point at can't be listed: a paint's months (the schema has no field for them), or that a paint was not offered on a variant. Say so in the file's header comment, next to the reason, until a field exists.

Listing a value and the object above it is allowed, so each claim keeps its own path. Listing one path twice is an error. The file's header comment keeps the reasons each value falls short: the field says which values, the comment says why.

### Safety advice needs evidence

Safety advice never rests on a forum post alone. This is weaker than `verified` and applies even to an unverified entry:

- **A maintenance item** needs at least one Tier 1 or Tier 2 source.
- **A known issue's `fix`** is optional. When it's there, the issue needs at least one Tier 1 or Tier 2 source. A `cost` is optional (see "Costs that are absent").
- **A known issue without a `fix`** publishes its symptoms, cause and how common it is, and Tier 3 sources are enough for that. Its `cost` is optional.
- **A maintenance item that says there is no scheduled service** (the `lifetime-fill` or `condition-based` trigger) needs at least one Tier 1 source, whatever its `verified` flag says. That is advice not to change something, so it needs a Tier 1 source, and a retailer's article or a forum alone is not enough. `check-data` reports it as `no-schedule-without-tier1`.

`check-data` reports a maintenance item, or an issue with a fix, that has only Tier 3 sources as `safety-advice-without-evidence`. To fix it, add a Tier 1 or Tier 2 source, or (for an issue) remove the `fix` until there is one. `prevention` isn't checked by a rule, so the data verifier and the user's spot-check on `safety` PRs look at it.

### Maintenance intervals

An interval is `miles`, `months`, `triggers`, or a mix, and it says what the source says.

- **Give a number only when the source gives one.** BMW's E46 documents give a number for a few services (oil at least once a year, brake fluid every two years, spark plugs at 60,000 miles in the 2005 US checklist), each for the model years the document names (see "Model years"). For the others they name the service that carries it. Record that in `triggers`. The site shows the triggers, not a made-up mileage, so don't turn a trigger into miles from a forum, from a typical figure, or by reading one number across from another document.
- **`miles` and `months` may sit beside `triggers` only when the source gives both** the service and its number, for the item's model years: a number from a source for other model years doesn't carry across. A source that names only the service supports the triggers alone. The schema can't see the source, so the data verifier and the `safety` spot-check look at this. It does enforce two cases. `lifetime-fill` takes no number at all. And a number sits beside a single trigger only: with two or more, it couldn't be pinned to one of them (`miles: 1200` beside `[break-in, inspection-ii]` would read as the interval of both), so the gearbox oil's `[break-in, inspection-ii]` takes no `miles` or `months`. An item whose source lists more than one trigger and also gives a calendar or mileage maximum records that number in `notes`, quoting the source (ruling R81). Engine oil is the example: the 2004 US booklet changes it at the 1200 Mile Service, at every Engine Oil Service and at Inspection I, and says "change oil at least once a year", so the triggers are `[break-in, oil-service, inspection-i]` and the year is in `notes`.
- **One service can have several triggers,** so `triggers` is a list with each value at most once. The 2004 US M3 booklet lists the microfilter at the Engine Oil Service and at Inspection I (`[oil-service, inspection-i]`), and the transmission and differential oil at the 1200 Mile Service and at Inspection II (`[break-in, inspection-ii]`). Inspection II repeats every Inspection I item, so an item due at both inspections lists `inspection-i` only, and the schema rejects the pair. `lifetime-fill` and `condition-based` say there is no scheduled service, so each stands alone in the list, and an item that uses either needs a Tier 1 source (see "Safety advice needs evidence").
- **A shorter interval that specialists recommend is not the interval.** It goes in `notes`, labelled as theirs, with its own source. It never replaces BMW's number or triggers.

On the E46 the Service Interval Indicator works out when the next service is due from how the car is driven, and shows OIL SERVICE or INSPECTION with the distance left. The record pages of BMW's 2004 US M3 booklet list Engine Oil Service, Inspection I, Engine Oil Service, Inspection II, in that order, and the booklet says Inspection II "Includes all items listed under Inspection I, and the following checks and maintenance operations." So Inspection II repeats every Inspection I item, and the distance between two services is not a fixed number. The triggers:

| Trigger | Means for the E46 |
|---|---|
| `break-in` | The first service, early in the car's life, whatever the indicator shows. The 2004 US M3 booklet calls it the "1200 Mile Service" and says it "requires changing the oil in the engine and both the transmission and the differential". The US owner's manual calls it a "break-in inspection" at approx. 1,250 miles and says to have it done "regardless of the service interval indicated on the display". |
| `oil-service` | Due at each Engine Oil Service, which the indicator shows as OIL SERVICE. |
| `inspection-i` | Due at Inspection I, and again at every Inspection II, because Inspection II repeats every Inspection I item. So an `inspection-i` item is due at every inspection, and an item due at both inspections lists this trigger only. |
| `inspection-ii` | Due at Inspection II only: an item BMW lists under Inspection II and not under Inspection I. |
| `lifetime-fill` | BMW says the fluid or part is a lifetime fill with no scheduled change. It stands alone and takes no `miles` or `months`: the schema rejects both. It needs a Tier 1 source. |
| `condition-based` | BMW's Condition Based Service decides from its own monitoring of that part. It stands alone and needs a Tier 1 source. A `miles` or `months` value beside it is the manufacturer's stated maximum, not a fixed interval. BMW started it with the E65, so no E46 item uses it. |

A page that shows an item's triggers shows an `inspection-i` item as due at every inspection, not only at Inspection I.

The table is sourced from BMW of North America's 2004 US M3 booklet, with the US owner's manual for `break-in` and BMW's training module ST050 for `condition-based`. Other generations, markets and model years can differ (the E46 coolant changed mid-run, see "Model years"), so check a new generation's own documents before reusing a row.

### Markets

`markets` names the markets a maintenance item's or a known issue's sources speak for: a non-empty list of `us` or `euro`, each at most once.

A document for one market covers that market only (the one-market clause of ruling R61, in "What counts as verified"). A BMW of North America booklet, checklist or bulletin supports `markets: [us]` and nothing else, and a European handbook supports `markets: [euro]`. A model-wide statement inside a one-market document is still a one-market document, so it does not widen the item.

A remedy that rests on a market-specific document splits the issue into one entry per market (ruling R82). The entry for the document's market carries the remedy and is verified on it. Every other market keeps an entry of its own, built from what the evidence supports there and `verified: false` unless it has its own sourced remedy, so a market without a sourced remedy keeps an unverified entry and the issue does not disappear from it. Each entry's id names its market.

Leave `markets` out only when the evidence covers every market: either one source that applies to all of them (a document that is not for one market, such as an international BMW media release), or a source for each market. When the US and European schedules differ, write one item for each market, with its own `markets` and an id that names the market. The schema can't see which market a source is for, so the data verifier and the `safety` spot-check look at `markets` against the sources.

### Model years

`modelYears` names the model years a maintenance item's or a known issue's sources speak for: `[from, to]`, both inclusive, such as `[2001, 2003]`. One year is `[2004, 2004]`. Both ends are always given, and there is no open-ended form: "from 2004 on" for a generation that ends in 2006 is `[2004, 2006]`.

For a maintenance item or a known issue, a manufacturer document (a booklet, an owner's manual, a checklist, a bulletin or a training module) speaks for the model years it names and for no others (ruling R86, the time counterpart of the one-market clause of R61 in "Markets"). A document for 2001 to 2003 says nothing about 2004. A model-wide statement inside a document for one model year is still a document for that year, so it covers that year only, and R85 never widens `modelYears` either.

The range lies inside the generation's `years`, with nothing past either end (ruling R88). The generation's `years` are also the year choices the site offers, so a range inside them can always be picked. If a source names a model year past the generation's `years`, the generation's `years` is fixed first, as its own sourced change, and `modelYears` may use the year afterwards. A model year must come from a source that names it: a document that names none supports no `modelYears` on its own. For a generation with `years: [2000, 2006]`, `[2001, 2006]` is fine, and `[1999, 2003]` and `[2001, 2007]` aren't. `check-data` reports a range outside as `model-years-outside-generation`.

Leave `modelYears` out only when the sources cover every model year of the generation, meaning every year in its `years`: either one source that applies to the whole span, or a source for each part of it.

When the schedule differs by year, write one entry for each year range, each with its own `modelYears` and an id that names the years. When the market differs too, the id names both, as in `e46-coolant-us-2001-2003`. The ranges of one service must not overlap, and an entry without `modelYears` can't sit beside them, because it would claim every year again. A gap between the ranges means no source gives a schedule for those years, so no entry says anything about them. `check-data` can't tell which entries are one service, so the data verifier looks.

BMW changed the E46 coolant schedule mid-run. BMW NA SI B17 01 07 gives "Every 4 years" and "Starting from the date of production" for model years 2001 to 2003, and "Long-Term" and "No Replacement Interval" from model year 2004. The bulletin is a BMW of North America document, so both entries are `markets: [us]` (see "Markets"). The coolant is two items:

| id | `markets` | `modelYears` | `interval` |
|---|---|---|---|
| `e46-coolant-2001-2003` | `[us]` | `[2001, 2003]` | `months: 48`, with the date-of-production wording in `notes` |
| `e46-coolant-2004-2006` | `[us]` | `[2004, 2006]` | `triggers: [lifetime-fill]` |

The schema can't see which model years a source covers, so the data verifier and the `safety` spot-check look at `modelYears` against the sources. It does enforce the shape: two whole years from 1985 to 2035, with `from` not after `to`.

### Costs that are absent

`cost` is optional on a maintenance item and on a known issue. Leave it out when no Tier 1 or Tier 2 source gives a figure. A cost is published only under the label its source states (ruling R78): a shop price, meaning parts and labor, goes in `shop`, and a do-it-yourself price in `diy` and never in `shop`. `cost` requires `shop` (a maintenance `cost` requires both), so a DIY figure with no shop figure is not published. A figure whose source doesn't say what it covers is not a sourced cost, and a parts-only figure is never a `shop` price. In those cases leave `cost` out, even when the source is Tier 1 or Tier 2. The site then shows "no sourced cost", and never zero. Don't write `[0, 0]` for "unknown": nothing tells it from free. A `cost` that is given is still checked: USD, a sorted range, and for a maintenance item both `diy` and `shop`. Price collection is a separate lane (see "Prices"), so a figure from a retailer's product listing is not a sourced cost.

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
| `safety-advice-without-evidence` | A maintenance item, or a known issue with a `fix`, has no Tier 1 or Tier 2 source | Add a source, or remove the issue's `fix` |
| `variant-body-not-in-generation` | A variant's `body` isn't in its generation's `bodies` | Fix the body, or add it to the generation |
| `variant-years-outside-generation` | A variant's `years` aren't within its generation's `years` | Fix the years |
| `part-years-outside-generation` | A part's `fits.years` aren't within its generation's `years` | Fix the years |
| `part-bodies-outside-generation` | A part's `fits.bodies` names a body its generation doesn't build | Fix the bodies |
| `fits-list-empty` | A part's `fits.bodies` or `fits.transmissions` is `[]`, which fits nothing | List at least one, or leave the field out to fit all |
| `unknown-engine` | A maintenance item or issue names an `engine` that isn't one of its generation's engine codes | Fix the code, or leave `engine` out for every engine |
| `model-years-outside-generation` | A maintenance item's or issue's `modelYears` aren't within its generation's `years` | Fix the years |
| `no-schedule-without-tier1` | A maintenance item with the `lifetime-fill` or `condition-based` trigger has no Tier 1 source | Add the Tier 1 source, or use the trigger the sources do support |
| `future-date` | A source's `accessed` or a price's `checked` is more than a day after today (UTC) | Fix the date |
| `unverified-path-missing` | A path in `unverified` doesn't point at a value: no such field, key or element; an optional field that isn't set in the file; an element named by position; a position or an element under a list with no key; a key under a fixed-length list; a position past its end; a path below a plain value; an element key shared by two elements (the path is ambiguous); or the `unverified` field itself | Fix the path; the message says where it stops |
| `unverified-path-duplicate` | The same path is listed twice in `unverified` | Remove the repeat |
