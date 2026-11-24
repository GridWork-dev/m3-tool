import { describe, expect, test } from 'vitest'
import { findHrefs, findLinks, isLinkAllowed } from '../../src/lib/html-links.ts'
import { isAllowedHref } from '../../src/lib/link-policy.ts'

test('findHrefs returns every anchor href in order', () => {
  expect(findHrefs('<a href="/a">x</a><a class=y href=\'https://github.com\'>z</a>')).toEqual([
    '/a',
    'https://github.com',
  ])
})

describe('finding links with an HTML parser (R33)', () => {
  const hrefs = findHrefs
  const SHOP = 'https://shop.example'

  describe('entities are decoded before the policy sees the value', () => {
    test.each([
      ['a decimal character reference in the scheme', '&#104;ttps://shop.example', SHOP],
      ['a hex character reference in the scheme', '&#x68;ttps://shop.example', SHOP],
      ['an encoded colon', 'https&#58;//shop.example/p', `${SHOP}/p`],
      ['a named colon', 'https&colon;//shop.example/p', `${SHOP}/p`],
      ['an encoded slash', 'https:&sol;&sol;shop.example', SHOP],
      [
        'a tab and a newline inside the scheme',
        'ht&Tab;tp&NewLine;s://shop.example',
        `ht\ttp\ns://shop.example`,
      ],
      ['an ampersand in a query string', '/p?a=1&amp;b=2', '/p?a=1&b=2'],
    ])('%s', (_label, raw, decoded) => {
      expect(hrefs(`<a href="${raw}">x</a>`)).toEqual([decoded])
    })

    test.each([
      '&#104;ttps://shop.example',
      'https&#58;//shop.example/p',
      'https&colon;//shop.example/p',
      'ht&Tab;tps://shop.example',
      '&#x68;&#x74;&#x74;&#x70;&#x73;&#x3a;//shop.example',
    ])('an obfuscated link to a shop is a violation: %s', (raw) => {
      const found = hrefs(`<a href="${raw}">x</a>`)
      expect(found).toHaveLength(1)
      expect(isAllowedHref(found[0] ?? '')).toBe(false)
    })

    test('an obfuscated link to an allowed host stays allowed', () => {
      const found = hrefs('<a href="https&#58;//github.com/GridWork-dev">x</a>')
      expect(found).toEqual(['https://github.com/GridWork-dev'])
      expect(isAllowedHref(found[0] ?? '')).toBe(true)
    })

    test('an entity in unquoted and single-quoted values is decoded too', () => {
      expect(hrefs('<a href=https&#58;//shop.example>x</a>')).toEqual([SHOP])
      expect(hrefs("<a href='https&#58;//shop.example'>x</a>")).toEqual([SHOP])
    })
  })

  describe('which elements and attributes are checked', () => {
    test('a[href], area[href], form[action] and iframe[src], in document order', () => {
      const html = [
        '<a href="/a">a</a>',
        `<map name="m"><area href="${SHOP}/area" alt="x"></map>`,
        `<form action="${SHOP}/form"><button>go</button></form>`,
        `<iframe src="${SHOP}/frame"></iframe>`,
      ].join('')
      expect(findLinks(html)).toEqual([
        { element: 'a', attribute: 'href', value: '/a' },
        { element: 'area', attribute: 'href', value: `${SHOP}/area` },
        { element: 'form', attribute: 'action', value: `${SHOP}/form` },
        { element: 'iframe', attribute: 'src', value: `${SHOP}/frame` },
      ])
      expect(hrefs(html)).toEqual(['/a', `${SHOP}/area`, `${SHOP}/form`, `${SHOP}/frame`])
    })

    test('an <area> that points off-site is a violation', () => {
      const [link] = findLinks(`<map name="m"><area href="${SHOP}" alt="x"></map>`)
      expect(link && isLinkAllowed(link)).toBe(false)
    })

    test('a form posting to a shop, and an iframe of a shop, are violations', () => {
      for (const html of [
        `<form action="${SHOP}/cart"></form>`,
        `<iframe src="${SHOP}"></iframe>`,
      ]) {
        const [link] = findLinks(html)
        expect(link && isLinkAllowed(link), html).toBe(false)
      }
    })

    test('a form or iframe that stays on the site is fine', () => {
      for (const html of ['<form action="/search"></form>', '<iframe src="/lab/frame"></iframe>']) {
        const [link] = findLinks(html)
        expect(link && isLinkAllowed(link), html).toBe(true)
      }
    })

    test('an element without the attribute has no link', () => {
      expect(findLinks('<a name="top">x</a><form></form><iframe></iframe><area alt="x">')).toEqual(
        [],
      )
    })

    test('data-href is not an href', () => {
      expect(hrefs(`<a data-href="${SHOP}">x</a>`)).toEqual([])
      expect(hrefs(`<a data-href="${SHOP}" href="/ok">x</a>`)).toEqual(['/ok'])
    })

    test('attribute names are case-insensitive, and so are tag names', () => {
      expect(hrefs(`<A HREF="${SHOP}">x</A>`)).toEqual([SHOP])
      expect(hrefs(`<FORM ACTION="${SHOP}"></FORM>`)).toEqual([SHOP])
    })

    test('a link in an SVG, in a <noscript> and in a <template> is found', () => {
      expect(hrefs(`<svg><a href="${SHOP}/svg"><text>x</text></a></svg>`)).toEqual([`${SHOP}/svg`])
      // Visitors without scripting get the <noscript> content, so it counts.
      expect(hrefs(`<noscript><a href="${SHOP}/ns">x</a></noscript>`)).toEqual([`${SHOP}/ns`])
      expect(hrefs(`<template><a href="${SHOP}/t">x</a></template>`)).toEqual([`${SHOP}/t`])
    })

    test('an SVG link written as xlink:href is found, and so is one that has both forms', () => {
      expect(hrefs(`<svg><a xlink:href="${SHOP}"><text>x</text></a></svg>`)).toEqual([SHOP])
      expect(hrefs(`<svg><a href="/ok" xlink:href="${SHOP}"><text>x</text></a></svg>`)).toEqual([
        '/ok',
        SHOP,
      ])
    })

    test('a link that only appears inside a comment, a script or a textarea is not a link', () => {
      expect(hrefs(`<!-- <a href="${SHOP}">x</a> -->`)).toEqual([])
      expect(hrefs(`<script>document.write('<a href="${SHOP}">x</a>')</script>`)).toEqual([])
      expect(hrefs(`<textarea><a href="${SHOP}">x</a></textarea>`)).toEqual([])
    })
  })

  describe('<base href>', () => {
    test('any <base href> is a violation, even one that points at the site itself', () => {
      for (const value of ['/', 'https://github.com/', `${SHOP}/`, 'https://x.example']) {
        const [link] = findLinks(`<head><base href="${value}"></head>`)
        expect(link).toEqual({ element: 'base', attribute: 'href', value })
        expect(link && isLinkAllowed(link), value).toBe(false)
      }
    })

    test('a <base> in the body, or with an entity-encoded href, is found too', () => {
      expect(findLinks('<body><base href="https&#58;//x.example"></body>')).toEqual([
        { element: 'base', attribute: 'href', value: 'https://x.example' },
      ])
    })

    test('a <base> with only a target has no href to flag', () => {
      expect(findLinks('<head><base target="_blank"></head>')).toEqual([])
    })

    test('findHrefs leaves <base> out: it is not an href the policy can allow', () => {
      expect(hrefs('<head><base href="https://x.example"></head><a href="/a">a</a>')).toEqual([
        '/a',
      ])
    })
  })

  describe('edge cases the policy has to survive', () => {
    test.each([
      ['a backslash after the slash', '/\\shop.example.com'],
      ['an uppercase scheme on a shop', 'HTTPS://SHOP.EXAMPLE/p'],
      ['an uppercase javascript scheme', 'JaVaScRiPt:alert(1)'],
      ['leading whitespace', '  https://shop.example'],
      ['trailing whitespace', 'https://shop.example  '],
      ['a leading tab and newline', '\t\nhttps://shop.example'],
      ['a tab inside the scheme', 'ht\ttps://shop.example'],
      ['a protocol-relative url with whitespace', ' //shop.example'],
      ['an uppercase http scheme on an allowed host', 'HTTP://github.com/x'],
    ])('%s is refused by the policy', (_label, value) => {
      expect(isAllowedHref(value)).toBe(false)
    })

    test('an uppercase scheme on an allowed host is allowed, because browsers lowercase it', () => {
      expect(isAllowedHref('HTTPS://GITHUB.COM/GridWork-dev')).toBe(true)
    })

    test('a literal backslash link survives the parser and is flagged', () => {
      const found = hrefs('<a href="/\\shop.example.com">x</a>')
      expect(found).toEqual(['/\\shop.example.com'])
      expect(isAllowedHref(found[0] ?? '')).toBe(false)
    })

    test('whitespace around the value is kept for the policy, which trims it as browsers do', () => {
      const found = hrefs('<a href=" https://shop.example ">x</a>')
      expect(found).toEqual([' https://shop.example '])
      expect(isAllowedHref(found[0] ?? '')).toBe(false)
    })

    test('a quoted > inside an attribute does not end the tag', () => {
      expect(hrefs(`<a title=">" href="${SHOP}">x</a>`)).toEqual([SHOP])
      expect(hrefs(`<a data-x='>' href='${SHOP}'>x</a>`)).toEqual([SHOP])
      expect(hrefs(`<a title="a > b" class=y href=${SHOP}>x</a>`)).toEqual([SHOP])
    })

    test('with a duplicate href, the first one wins, as it does in a browser', () => {
      expect(hrefs(`<a href="/ok" href="${SHOP}">x</a>`)).toEqual(['/ok'])
      expect(hrefs(`<a href="${SHOP}" href="/ok">x</a>`)).toEqual([SHOP])
    })

    test('an unclosed tag, a stray < and a missing quote do not throw', () => {
      expect(() => findLinks('<a href="/a"')).not.toThrow()
      expect(() => findLinks('<<a href=>')).not.toThrow()
      expect(() => findLinks('')).not.toThrow()
      expect(findLinks('')).toEqual([])
    })

    test('an empty href is the current page', () => {
      expect(hrefs('<a href="">x</a>')).toEqual([''])
      expect(isAllowedHref('')).toBe(true)
    })
  })
})
