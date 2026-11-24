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

  describe('elements that load a page or send the form (R39 review, Codex P2 and M4)', () => {
    test.each([
      ['object', 'data', `<object data="${SHOP}/x"></object>`],
      ['embed', 'src', `<embed src="${SHOP}/x">`],
      ['frame', 'src', `<frameset><frame src="${SHOP}/x"></frameset>`],
      ['button', 'formaction', `<form><button formaction="${SHOP}/x">Buy</button></form>`],
      ['input', 'formaction', `<form><input type="submit" formaction="${SHOP}/x"></form>`],
    ] as const)('<%s %s> is found, and a shop in it is a violation', (element, attribute, html) => {
      const links = findLinks(html)
      expect(links).toContainEqual({ element, attribute, value: `${SHOP}/x` })
      const found = links.find((link) => link.element === element)
      expect(found && isLinkAllowed(found)).toBe(false)
    })

    test.each([
      `<object data="/model.glb"></object>`,
      `<embed src="/doc.pdf">`,
      `<frameset><frame src="/part.html"></frameset>`,
      `<form><button formaction="/search">Go</button></form>`,
      `<form><input type="submit" formaction="/search"></form>`,
    ])('a link that stays on the site is fine: %s', (html) => {
      const links = findLinks(html).filter((link) => link.element !== 'form')
      expect(links).toHaveLength(1)
      expect(links.every(isLinkAllowed)).toBe(true)
    })

    test('a button or input without formaction has no link', () => {
      expect(findLinks('<form><button>Go</button><input type="submit"></form>')).toEqual([])
    })

    test('attribute names are case-insensitive, and entities are decoded', () => {
      expect(hrefs(`<form><button FORMACTION="https&#58;//shop.example"></button></form>`)).toEqual(
        [SHOP],
      )
    })
  })

  describe('<meta http-equiv="refresh">', () => {
    const refresh = (content: string) =>
      findLinks(`<head><meta http-equiv="refresh" content="${content}"></head>`)

    test.each([
      ['a url after a semicolon', '0;url=https://shop.example', SHOP],
      ['an uppercase URL= and spaces', '5; URL = https://shop.example/p', `${SHOP}/p`],
      ['a single-quoted url', "0; url='https://shop.example'", SHOP],
      ['a double-quoted url', '0; url=&quot;https://shop.example&quot;', SHOP],
      ['a comma as the separator', '0,https://shop.example', SHOP],
      ['whitespace as the separator', '0 https://shop.example', SHOP],
      ['no url= prefix', '0;https://shop.example', SHOP],
      ['padding around everything', '  3 ;  url = https://shop.example  ', SHOP],
      ['a decimal delay', '0.5;url=https://shop.example', SHOP],
      ['an entity-encoded url', '0;url=https&#58;//shop.example', SHOP],
      ['a relative url', '0;url=/about', '/about'],
    ])('%s', (_label, content, target) => {
      expect(refresh(content)).toEqual([{ element: 'meta', attribute: 'content', value: target }])
    })

    test('a refresh to a shop is a violation, and one to the site is fine', () => {
      const [shop] = refresh(`0;url=${SHOP}`)
      const [home] = refresh('0;url=/')
      expect(shop && isLinkAllowed(shop)).toBe(false)
      expect(home && isLinkAllowed(home)).toBe(true)
    })

    test.each(['5', '', '0;', '0;url=', '  ', '0; url = '])(
      'a refresh with no target (%j) has no link',
      (content) => {
        expect(refresh(content)).toEqual([])
      },
    )

    test('http-equiv is matched without regard to case', () => {
      for (const value of ['Refresh', 'REFRESH', 'refresh']) {
        expect(
          findLinks(`<meta HTTP-EQUIV="${value}" content="0;url=${SHOP}">`),
          value,
        ).toHaveLength(1)
      }
    })

    test('other meta tags are not links', () => {
      expect(findLinks(`<meta http-equiv="content-type" content="0;url=${SHOP}">`)).toEqual([])
      expect(findLinks(`<meta name="refresh" content="0;url=${SHOP}">`)).toEqual([])
      expect(findLinks('<meta http-equiv="refresh">')).toEqual([])
      expect(findLinks(`<meta content="0;url=${SHOP}">`)).toEqual([])
    })

    test('a refresh inside <noscript> counts, as it does for a visitor without scripting', () => {
      expect(
        findLinks(
          `<head><noscript><meta http-equiv="refresh" content="0;url=${SHOP}"></noscript></head>`,
        ),
      ).toHaveLength(1)
    })
  })

  describe('<iframe srcdoc> is a page of its own', () => {
    test('the example from the review: an anchor in srcdoc is found and is a violation', () => {
      const html = `<iframe srcdoc="<a href='${SHOP}'>Shop</a>"></iframe>`
      const links = findLinks(html)
      expect(links).toEqual([
        { element: 'a', attribute: 'href', value: SHOP, via: 'iframe srcdoc' },
      ])
      expect(links.some((link) => !isLinkAllowed(link))).toBe(true)
      expect(hrefs(html)).toEqual([SHOP])
    })

    test('entity-encoded markup in srcdoc is decoded before it is parsed', () => {
      const html = `<iframe srcdoc="&lt;a href=&quot;${SHOP}&quot;&gt;Shop&lt;/a&gt;"></iframe>`
      expect(hrefs(html)).toEqual([SHOP])
    })

    test('an entity in the inner href is decoded too', () => {
      const html = `<iframe srcdoc="<a href='https&#58;//shop.example'>Shop</a>"></iframe>`
      expect(hrefs(html)).toEqual([SHOP])
    })

    test('srcdoc inside srcdoc is followed, at any depth, and the path is recorded', () => {
      const inner = `<iframe srcdoc="&lt;a href='${SHOP}'&gt;x&lt;/a&gt;"></iframe>`
      const outer = `<iframe srcdoc="${inner.replaceAll('&', '&amp;').replaceAll('"', '&quot;')}"></iframe>`
      expect(findLinks(outer)).toEqual([
        { element: 'a', attribute: 'href', value: SHOP, via: 'iframe srcdoc > iframe srcdoc' },
      ])
    })

    test('every kind of link inside srcdoc is checked: a form, a base, a refresh, an area', () => {
      const doc = [
        `<base href="${SHOP}/">`,
        `<form action="${SHOP}/f"></form>`,
        `<meta http-equiv="refresh" content="0;url=${SHOP}/m">`,
        `<map name="m"><area href="${SHOP}/a"></map>`,
      ].join('')
      const html = `<iframe srcdoc="${doc.replaceAll('"', '&quot;')}"></iframe>`
      const links = findLinks(html)
      expect(links.map((link) => link.element).sort()).toEqual(['area', 'base', 'form', 'meta'])
      expect(links.every((link) => link.via === 'iframe srcdoc')).toBe(true)
      expect(links.some(isLinkAllowed)).toBe(false)
    })

    test('the iframe keeps its own src check, beside the srcdoc', () => {
      const html = `<iframe src="${SHOP}/frame" srcdoc="<a href='/ok'>ok</a>"></iframe>`
      expect(findLinks(html)).toEqual([
        { element: 'iframe', attribute: 'src', value: `${SHOP}/frame` },
        { element: 'a', attribute: 'href', value: '/ok', via: 'iframe srcdoc' },
      ])
    })

    test('a srcdoc with only allowed links has no violation, and an empty one has no links', () => {
      const ok = findLinks(`<iframe srcdoc="<a href='/about'>About</a>"></iframe>`)
      expect(ok).toHaveLength(1)
      expect(ok.every(isLinkAllowed)).toBe(true)
      expect(findLinks('<iframe srcdoc=""></iframe>')).toEqual([])
      expect(findLinks('<iframe srcdoc="plain text"></iframe>')).toEqual([])
    })

    test('the srcdoc attribute is not itself a link value', () => {
      expect(hrefs(`<iframe srcdoc="${SHOP}"></iframe>`)).toEqual([])
    })

    test('a srcdoc inside a <template> or a <noscript> is followed too', () => {
      expect(
        hrefs(`<template><iframe srcdoc="<a href='${SHOP}'>x</a>"></iframe></template>`),
      ).toEqual([SHOP])
      expect(
        hrefs(`<noscript><iframe srcdoc="<a href='${SHOP}'>x</a>"></iframe></noscript>`),
      ).toEqual([SHOP])
    })

    test('findHrefs includes srcdoc links and still leaves <base> out', () => {
      const html = `<iframe srcdoc="<base href='${SHOP}'><a href='/a'>a</a>"></iframe>`
      expect(hrefs(html)).toEqual(['/a'])
      expect(findLinks(html).some((link) => link.element === 'base')).toBe(true)
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
