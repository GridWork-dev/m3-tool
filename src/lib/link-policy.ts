// The site carries no affiliate, ad or store links. Every link in the built HTML must be
// site-relative or an https link to one of these hosts (exact match, no subdomains).
export const ALLOWED_LINK_HOSTS = [
  'github.com',
  'creativecommons.org',
  'opensource.org',
  'commons.wikimedia.org',
] as const

// Non-commercial references that a citation's `url` may link to (spec section 7.6, amended
// 2026-11-23). A citation always shows its publisher, title and accessed date as text; its url
// becomes a link only when its host is on this list, so a Tier 2 retailer is never linked and a
// reader searches for the source instead. The BMW host is the one `data/generations/e46.yaml`
// cites. Adding a host is a review decision: `tests/unit/link-policy.test.ts` pins the list.
export const CITATION_HOSTS = [
  'archive.org',
  'web.archive.org',
  'newsroom.bmwgroup.com',
  'en.wikipedia.org',
  'commons.wikimedia.org',
] as const

const SITE_BASE = new URL('https://site.invalid/')
const CITATION_HOST_LIST: readonly string[] = CITATION_HOSTS
// check:links accepts both lists: a built page may contain a link the policy lets a citation have.
const ALLOWED_HOSTS: readonly string[] = [...ALLOWED_LINK_HOSTS, ...CITATION_HOSTS]

// Whether a citation's `url` may be rendered as a link: an absolute https URL, with no
// credentials, whose host is exactly one of CITATION_HOSTS. Everything else is shown as text.
export function isCitationLinkable(url: string): boolean {
  if (!URL.canParse(url)) return false
  const parsed = new URL(url)
  return (
    parsed.protocol === 'https:' &&
    parsed.username === '' &&
    parsed.password === '' &&
    CITATION_HOST_LIST.includes(parsed.hostname)
  )
}

export function isAllowedHref(href: string): boolean {
  // A string with a scheme parses on its own: only https to an allowlisted host passes.
  if (URL.canParse(href)) {
    const url = new URL(href)
    return url.protocol === 'https:' && ALLOWED_HOSTS.includes(url.hostname)
  }
  // Without a scheme it resolves against the site. If the host moved, the href was
  // protocol-relative (`//shop.example.com`, or `/\shop.example.com`, which browsers
  // treat the same way), so it points off-site.
  try {
    return new URL(href, SITE_BASE).host === SITE_BASE.host
  } catch {
    return false
  }
}

// An `<a ...>` start tag, skipping over quoted values so a `>` inside one doesn't end it.
const ANCHOR_TAG = /<a(?=[\s/>])((?:[^>"']|"[^"]*"|'[^']*')*)>/gi
const ATTRIBUTE = /([^\s"'<>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g

export function findHrefs(html: string): string[] {
  const hrefs: string[] = []
  for (const tag of html.matchAll(ANCHOR_TAG)) {
    for (const attr of (tag[1] ?? '').matchAll(ATTRIBUTE)) {
      if (attr[1]?.toLowerCase() === 'href') {
        hrefs.push(attr[2] ?? attr[3] ?? attr[4] ?? '')
        break // browsers use the first href when an element repeats it
      }
    }
  }
  return hrefs
}
