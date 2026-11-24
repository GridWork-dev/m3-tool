// Finds the links in a built page, the way a browser would read them, for `check:links`. It needs an
// HTML parser, so it lives apart from the pure policy in `link-policy.ts`, which it applies.
import { type DefaultTreeAdapterMap, parse } from 'parse5'
import { isAllowedHref } from './link-policy.ts'

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
