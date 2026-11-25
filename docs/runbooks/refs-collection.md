# Reference collection

Agents now own source selection, collection and curation under [ADR 0017](../decisions/0017-codex-led-workflow-and-reference-collection.md). Inspect the existing private cache before fetching; preserve curated sets, provenance and blocked-source records. User approval of synthesized views and models remains required.

## What this stores

This is a private local store under `M3_WORK_DIR` (default `~/.cache/m3-tool`),
outside the repository. Original image bytes are hash-addressed under
`refs/images/<hash-prefix>/<hash>.<ext>`; provenance and labels live in
`refs/manifest.jsonl`. R2 copies go to the private `m3-tool-refs` bucket.
Never commit images or the manifest. Generated cutouts, classification batches,
view sets and descriptions also belong in this private work directory.

## Setup

Run all commands below from `pipeline/`. Run `uv sync`, then
`uv run playwright install chromium`. For background removal, optionally run
`uv sync --group bg`; the first cutout run downloads a large model into
`<work_dir>/refs/models`. Leave `U2NET_HOME` unset to use that location.

The maintainer supplies environment variables from `~/.config/secrets.env`:
`M3_R2_ACCOUNT_ID`, `M3_R2_ACCESS_KEY_ID`, `M3_R2_SECRET_ACCESS_KEY`,
`M3_BROWSERBASE_API_KEY`, `M3_BROWSERBASE_PROJECT_ID`. Set `M3_WORK_DIR` to a private
location outside the repo. `M3_REFS_USER_AGENT` optionally overrides the generic
User-Agent. Never print or copy credential values into logs, prompts or the repo.

```sh
uv run pipeline refs stats
```

## Commons

Edit `pipeline/refs-sources.toml` (from here, `refs-sources.toml`). Example settings:

    [http]
    user_agent = "m3-tool-refs/0.1 (+https://github.com/GridWork-dev/m3-tool)"

    [commons]
    thumb_width = 1920
    min_interval_s = 3.0

    [subjects.e46-coupe]
    commons_categories = ["Category:BMW M3 (E46/2S)", "Category:BMW M3 CSL (E46)"]

    [subjects.e46-coupe-interior]
    commons_categories = ["Category:BMW M3 (E46/2CS)"]
    search_terms = ["E46 M3 interior", "BMW E46 interior"]

Recon on 2026-11-23 found 369 files in `Category:BMW M3 (E46/2S)` (coupe),
144 in `Category:BMW M3 (E46/2CS)` (convertible, useful for front-interior shots),
and 74 in `Category:BMW M3 CSL (E46)`. CSL can go in the coupe subject because the
classifier labels its trim and the standard-car filter drops it. Search terms
help fill thin interior coverage.

```sh
uv run pipeline refs commons --subject e46-coupe
```

At the 3 s default, a full category takes about 20 minutes. Commons answers 429
to fast clients: the tool backs off using `Retry-After` and stops with a message
after 3 retries. Rerun later to resume with progress retained. The default
`thumb_width` is 1920, a standard Wikimedia thumbnail step; 2560 is not one.
If a run stops on "thumbnail width rejected", set it to 1920 or 3840.

## Your own photos

```sh
uv run pipeline refs import /private/path/photos --subject e46-coupe --source-note "Collected by hand"
```

Use `--license` only when you can assert one; the default is `unknown`, including
for product photos. JPEG, PNG, WebP and AVIF work. Convert HEIC first with
`sips -s format jpeg input.heic --out output.jpg`. Bad files are reported and
skipped; originals remain untouched.

Product photos from sites behind bot checkpoints come in this way. For example,
apexwheels.com answered 429 with a Vercel Security Checkpoint during recon. Save
the images in a normal browser, then import them with `--subject product-<part-id>`:

```sh
uv run pipeline refs import /private/path/product-photos --subject product-wheel-a --source-note "Saved in a normal browser"
```

## Crawler

Put seed URLs in the TOML subject's `crawl_urls` or pass `--url`. It visits only
those URLs and their images, without following page links. It checks robots.txt
and respects the per-host delay, normally 3 seconds (never below the floor).
Use the local browser or an explicitly selected Browserbase backend:

```sh
uv run pipeline refs crawl --subject e46-coupe --backend local --url https://example.org/reference-page
uv run pipeline refs crawl --subject e46-coupe --backend browserbase
```

Browserbase needs a session-approved cap and a row in `docs/spend-ledger.md`
before use; record usage even when covered by an existing plan. A "blocked" line
means drop that source or import by hand in a normal browser. Never work around
it, retry aggressively or change the browser identity.

## Curation

```sh
uv run pipeline refs dedupe --subject e46-coupe
uv run pipeline refs classify export --subject e46-coupe
```

Point another model or harness with image access at
`<work_dir>/refs/classify/e46-coupe/CLASSIFY.md`. It opens the paths in the batch
files and produces `labels-001.jsonl`, one JSON object per image, without prose.
Import each completed labels file; the entire file must validate before any
labels change. Unknown facts stay `unknown`, never inferred from file names.

```sh
uv run pipeline refs classify import /private/work/refs/classify/e46-coupe/labels-001.jsonl
uv run pipeline refs cutouts --subject e46-coupe
uv run pipeline refs viewsets build --subject e46-coupe
uv run pipeline refs credits --subject e46-coupe
```

Cutouts require the optional `bg` group. Run the same commands with
`--subject e46-coupe-interior` for the cabin. Exterior and product sets contain up
to 5 views. `missing` names slots without a selected image. Interior sets collect
up to 5 views for each of six components: dash, gauges, steering wheel, seats,
door and console. A component with fewer than 3 views is reported missing.
Inspect the scores, rejection counts and license flags. An `all_cc_or_pd=False`
flag means at least one selected image has an unknown or unsupported license
(or the set is empty); it is not a license grant. Credits list Commons images
and count other images. Keep the generated manifests and sets unedited; rerun
the commands instead. Hand-written description notes belong in
`pipeline/descriptions/<subject>.md`; the `refs` stage appends them verbatim.

Many Commons interiors are UK right-hand-drive cars, including Flickr's
"The Car Spy" sets. Label `drive_side` honestly from visible cues. RHD steering,
gauge-cluster, console and seat photos are used as-is; an RHD whole dash or door
is used only mirrored and flagged `contains_text_risk` because text may reverse.
Steering and gauge images are never mirrored. Seat labels name the role
(driver, passenger or both), never the side. A whole dash or door with unknown
drive side is skipped.

## Sync

```sh
uv run pipeline refs sync push
uv run pipeline refs sync pull
```

Push uploads missing image hashes, including duplicate records' files, and
uploads the manifest last. Interrupted uploads can resume. If the remote
manifest has records missing locally, the guard says "pull first"; pull to merge
them before pushing. `--force` explicitly replaces the remote manifest with the
local one, so use it only when discarding those remote-only records is intended.
Pull downloads missing images, verifies hashes and merges records. Local records
win unless only the remote record has labels. Unreferenced remote objects are
ignored. Sync copies originals and the manifest; regenerate cutouts and view sets
on the receiving machine.

## Brief for another model or harness

Paste this brief, replacing the working directory and subject placeholders:

    Work from <repo>/pipeline/ on subject <subject>. The private store is M3_WORK_DIR,
    outside the repo. Allowed commands: uv run pipeline refs stats, commons, import,
    crawl, dedupe, classify export, classify import, cutouts, viewsets build, credits,
    sync push and sync pull. Read refs-sources.toml and the generated CLASSIFY.md.
    Credential names, supplied by the maintainer's environment only:
    M3_R2_ACCOUNT_ID, M3_R2_ACCESS_KEY_ID, M3_R2_SECRET_ACCESS_KEY,
    M3_BROWSERBASE_API_KEY, M3_BROWSERBASE_PROJECT_ID. Never reveal their values.
    M3_REFS_USER_AGENT may set a generic identifying UA; never spoof a browser UA.
    Respect robots.txt and host delays. No stealth, proxy rotation or captcha solving.
    No link-following. Keep unknown licenses unknown. Label drive_side honestly.
    Never commit photos, manifests or credentials. Do not enable Browserbase without
    a session-approved cap and spend-ledger row. Report the numbers; do not fix blocked sources.

## What the tool deliberately won't do

No stealth, proxy rotation, captcha solving or browser User-Agent spoofing.
No link-following, license guessing or HEIC decoding. No images or manifest in
the repo. robots.txt and the host delay are not switches to turn off. A blocked
source stays blocked; use another source or the normal-browser import fallback.
