# Legal standard

The rules that keep a free fan project on the right side of trademark, copyright and license terms. This is a working standard, not legal advice. The 3D models show real cars and products that look like real products, including wheel designs that may be protected. That is lower risk for a free tool that sells nothing, but not zero, so follow every rule here.

## Trademarks

- **Use "BMW" and "M3" only to describe the car.** They're BMW AG's trademarks. Write "BMW M3 (E46)" to say what the page covers. The public name and domain will avoid both words. `m3-tool` is a placeholder repo and working name until the public beta.
- **Show no BMW marks.** Not in the UI, not in a model, not in a texture.
- **Name a real product in text only.** A part page says "Brand Product" to identify it. Its logo is as forbidden as BMW's.

### Forbidden marks

None of these appears anywhere: UI, models, textures or screenshots.

- The BMW roundel, including the one on the steering wheel and the gauges.
- The M logo.
- Badges, including those on the grille, wheel caps and trunk.
- Logos on wheel center caps. A plain cap, or none, replaces them.

The asset validator can't see a logo. The vision critic and the human review in `/lab` check for them, and a PR that adds a model says so in its description.

## The notice

This text appears in the site footer and on `/about`, word for word:

```
Independent fan project. Not affiliated with, endorsed by, or sponsored by BMW AG. BMW and M3 are trademarks of BMW AG, used here only to describe the cars.
```

The e2e tests check for it. Don't paraphrase it, shorten it or move it behind a click.

## No store links

The site has no affiliate, ad, sponsored or store links of any kind. A price observation's `url` is stored so the updater can check the price again, and it is never rendered as a link. `pnpm check:links` fails the build on any external link outside a short allowlist (`src/lib/link-policy.ts`): `github.com`, `creativecommons.org`, `opensource.org` and `commons.wikimedia.org`. A source's citation shows its publisher, title and accessed date as text, and links its `url` only for the non-commercial hosts in `CITATION_HOSTS` (`archive.org`, `web.archive.org`, `newsroom.bmwgroup.com`, `en.wikipedia.org` and `commons.wikimedia.org`), which `check:links` accepts too. A Tier 2 retailer's page is never linked. Adding a host to either list is a change to the policy, so it needs its own PR and a reason ([ADR 0009](../decisions/0009-citations-and-link-policy.md)).

## Reference photos

Reference photos are copyrighted images by other people. Handle them as follows.

- **They never enter the public repo.** They live in the private `m3-tool-refs` bucket and a local cache. `tests/unit/repo-hygiene.test.ts` fails if an image or GLB is tracked outside `public/` and `tests/fixtures/`.
- **Agents build the collection tooling. The user runs the collection and chooses the sources.** The user may run it with another model or harness.
- **The tooling's defaults:**
  - Respect `robots.txt`.
  - Rate-limit requests.
  - Use a generic user agent.
  - Record the source URL, author, license and date for every image.
- **No bot-blocking workarounds.** The tooling has no feature for getting past a block. A blocked page is logged and skipped.
- **Prefer licensed images.** Wikimedia Commons is the main source, because its license metadata is machine-readable. A Creative Commons share-alike photo that fed a model is credited on `/about`.
- **A seller whose terms forbid automated access is skipped for reference photos.** Prices and product pages may instead retry through an unblocking service; that exception is [ADR 0009](../decisions/0009-price-scraping-unblock.md), and it never extends to photo collection.

## Generator license gates

Each 3D generator's terms decide whether its outputs can be published. Check them before any output reaches `public/` or the models bucket.

- **Hunyuan3D 2.x is experiment-only.** Its community license excludes the EU, UK and South Korea. Nothing it makes is published until that's cleared.
- **Rodin (Hyper3D):** read the terms at developer.hyper3d.ai before publishing any output.
- **Any other generator:** read the terms first, and record what you found in the PR.
- **Record the license in the manifest.** The `license` field of each `src/assets/manifest.json` entry names the license the published GLB carries, derived from every reference it was built from.

If a generator's terms don't allow publishing, the asset stays private. Bringing the user options, such as licensed marketplace models, is a user decision: don't switch on your own.

## Licenses and credits

| What | License | File |
|---|---|---|
| Code | MIT | `LICENSE` |
| Data under `data/` | CC BY-SA 4.0 | `DATA_LICENSE` |
| Published 3D models | CC BY-SA 4.0, proposed | final only after the generator terms are checked |

- **Share-alike stays compatible** if Creative Commons share-alike photos fed a model. Every such photo is credited on `/about`, and the model license is final only after the generator terms are checked.
- **Credit what you use.** `/about` lists the licenses, the data sources and the credits for reference photos. A credit links only to an allowlisted host, such as `commons.wikimedia.org`.
