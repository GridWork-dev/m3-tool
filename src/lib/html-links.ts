// Finds the links in a built page, the way a browser would read them, for `check:links`. It needs an
// HTML parser, so it lives apart from the pure policy in `link-policy.ts`, which it applies.
import { type DefaultTreeAdapterMap, parse } from 'parse5'
import { isAllowedHref } from './link-policy.ts'

// The elements and attributes that send a visitor somewhere, or make the browser fetch a page.
// A <base href> is listed because it changes where every relative link goes: the policy refuses
// it outright. A <meta http-equiv="refresh"> and an <iframe srcdoc> need more than an attribute
// value, so they are handled below.
const LINK_ATTRIBUTES = {
  a: 'href',
  area: 'href',
  form: 'action',
  iframe: 'src',
  base: 'href',
  object: 'data',
  embed: 'src',
  frame: 'src',
  button: 'formaction',
  input: 'formaction',
} as const

type AttributeLink = keyof typeof LINK_ATTRIBUTES

export type LinkElement = AttributeLink | 'meta'

export interface PageLink {
  element: LinkElement
  attribute: (typeof LINK_ATTRIBUTES)[AttributeLink] | 'content'
  // The attribute's value after the parser has decoded its entities, exactly as a browser sees it.
  // For a refresh it is the target url.
  value: string
  // Set when the link is inside an `<iframe srcdoc>`: `iframe srcdoc`, or `iframe srcdoc > iframe
  // srcdoc` for one inside another.
  via?: string
}

const isAttributeLink = (name: string): name is AttributeLink =>
  Object.hasOwn(LINK_ATTRIBUTES, name)

const WHITESPACE = '[\\t\\n\\f\\r ]'
// `<delay>[;|,|whitespace][url=]<target>`, as the HTML standard's refresh steps read it. A
// target the standard would ignore (no delay, say) is still read, which is the safe side.
const REFRESH = new RegExp(
  `^${WHITESPACE}*[0-9.]*${WHITESPACE}*(?:[;,]${WHITESPACE}*)?(?:url${WHITESPACE}*=${WHITESPACE}*)?(.*)$`,
  'is',
)

// The url a `<meta http-equiv="refresh" content="...">` sends the visitor to, if it names one.
function refreshTarget(content: string): string | undefined {
  const rest = (REFRESH.exec(content)?.[1] ?? '').trim()
  const quote = rest[0]
  const target =
    quote === '"' || quote === "'"
      ? rest.slice(1, rest.indexOf(quote, 1) === -1 ? undefined : rest.indexOf(quote, 1))
      : rest
  return target.trim() === '' ? undefined : target.trim()
}

// Parses `html` the way a browser does (parse5 implements the HTML standard), so entities are
// decoded (`&#104;ttps:` is `https:`), quoted `>` stays inside its value, tag and attribute names
// are case-insensitive, and with a repeated attribute the first one wins. `scriptingEnabled:
// false` parses <noscript> content as markup, because visitors without scripting get it.
// <template> content is checked too, since scripts clone it into the page, and so is the
// document inside an `<iframe srcdoc>`, which is a page of its own.
export function findLinks(html: string): PageLink[] {
  const found: PageLink[] = []
  collect(html, [], found)
  return found
}

function collect(html: string, via: string[], found: PageLink[]): void {
  const path = via.length > 0 ? { via: via.join(' > ') } : {}
  const visit = (node: DefaultTreeAdapterMap['node']): void => {
    if (isElement(node)) {
      if (isAttributeLink(node.tagName)) {
        const attribute = LINK_ATTRIBUTES[node.tagName]
        // An SVG <a> may also use `xlink:href`, which the parser names `href` with a prefix, so
        // every attribute of that name counts. An HTML element repeats none: the parser drops the
        // later copy.
        for (const attr of node.attrs) {
          if (attr.name === attribute) {
            found.push({ element: node.tagName, attribute, value: attr.value, ...path })
          }
        }
      } else if (node.tagName === 'meta') {
        const refresh = node.attrs.some(
          (attr) => attr.name === 'http-equiv' && attr.value.toLowerCase() === 'refresh',
        )
        const content = node.attrs.find((attr) => attr.name === 'content')?.value
        const target = refresh && content !== undefined ? refreshTarget(content) : undefined
        if (target !== undefined) {
          found.push({ element: 'meta', attribute: 'content', value: target, ...path })
        }
      }
      if (node.tagName === 'iframe') {
        const srcdoc = node.attrs.find((attr) => attr.name === 'srcdoc')?.value
        if (srcdoc !== undefined) collect(srcdoc, [...via, 'iframe srcdoc'], found)
      }
    }
    if ('content' in node) visit(node.content)
    if ('childNodes' in node) for (const child of node.childNodes) visit(child)
  }
  visit(parse(html, { scriptingEnabled: false }))
}

const isElement = (node: DefaultTreeAdapterMap['node']): node is DefaultTreeAdapterMap['element'] =>
  'tagName' in node

// Every value in a page that must pass `isAllowedHref`: anchors, image-map areas, forms, buttons,
// objects, embeds, iframes and refreshes, in document order, with the ones inside an `iframe
// srcdoc` included. A <base href> is not here, because it is never allowed.
export function findHrefs(html: string): string[] {
  return findLinks(html)
    .filter((link) => link.element !== 'base')
    .map((link) => link.value)
}

// A <base href> is always a violation. Every other link must pass `isAllowedHref`.
export function isLinkAllowed(link: PageLink): boolean {
  return link.element !== 'base' && isAllowedHref(link.value)
}

// How a violation got there, for the report: `form action`, `meta refresh`, `a href in iframe
// srcdoc`. Undefined for a plain anchor, which the report shows as its href alone.
export function describeLink(link: PageLink): string | undefined {
  if (link.element === 'a' && link.via === undefined) return undefined
  const what = link.element === 'meta' ? 'meta refresh' : `${link.element} ${link.attribute}`
  return link.via === undefined ? what : `${what} in ${link.via}`
}
