import { type DefaultTreeAdapterMap, parse } from 'parse5'

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

// ---------------------------------------------------------------------------------------------
// Finding the links in a page
// ---------------------------------------------------------------------------------------------

// The elements and attributes that send a visitor somewhere, or make the browser fetch a page.
// A <base href> is listed because it changes where every relative link goes: the policy refuses
// it outright.
const LINK_ATTRIBUTES = {
  a: 'href',
  area: 'href',
  form: 'action',
  iframe: 'src',
  base: 'href',
} as const

export type LinkElement = keyof typeof LINK_ATTRIBUTES

export interface PageLink {
  element: LinkElement
  attribute: (typeof LINK_ATTRIBUTES)[LinkElement]
  // The attribute's value after the parser has decoded its entities, exactly as a browser sees it.
  value: string
}

const isLinkElement = (name: string): name is LinkElement => Object.hasOwn(LINK_ATTRIBUTES, name)

// Parses `html` the way a browser does (parse5 implements the HTML standard), so entities are
// decoded (`&#104;ttps:` is `https:`), quoted `>` stays inside its value, tag and attribute names
// are case-insensitive, and with a repeated attribute the first one wins. `scriptingEnabled:
// false` parses <noscript> content as markup, because visitors without scripting get it.
// <template> content is checked too, since scripts clone it into the page.
export function findLinks(html: string): PageLink[] {
  const found: PageLink[] = []
  const visit = (node: DefaultTreeAdapterMap['node']): void => {
    if (isElement(node) && isLinkElement(node.tagName)) {
      const attribute = LINK_ATTRIBUTES[node.tagName]
      // An SVG <a> may also use `xlink:href`, which the parser names `href` with a prefix, so every
      // attribute of that name counts. An HTML element repeats none: the parser drops the later copy.
      for (const attr of node.attrs) {
        if (attr.name === attribute) {
          found.push({ element: node.tagName, attribute, value: attr.value })
        }
      }
    }
    if ('content' in node) visit(node.content)
    if ('childNodes' in node) for (const child of node.childNodes) visit(child)
  }
  visit(parse(html, { scriptingEnabled: false }))
  return found
}

const isElement = (node: DefaultTreeAdapterMap['node']): node is DefaultTreeAdapterMap['element'] =>
  'tagName' in node

// Every value in a page that must pass `isAllowedHref`: anchors, image-map areas, form actions and
// iframes, in document order. A <base href> is not here, because it is never allowed.
export function findHrefs(html: string): string[] {
  return findLinks(html)
    .filter((link) => link.element !== 'base')
    .map((link) => link.value)
}

// A <base href> is always a violation. Every other link must pass `isAllowedHref`.
export function isLinkAllowed(link: PageLink): boolean {
  return link.element !== 'base' && isAllowedHref(link.value)
}
