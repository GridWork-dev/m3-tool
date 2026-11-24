import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'
import { loadDataSet } from '../../src/data/load.ts'
import {
  ALLOWED_LINK_HOSTS,
  CITATION_HOSTS,
  isAllowedHref,
  isCitationLinkable,
} from '../../src/lib/link-policy.ts'

test('relative, root and fragment links are allowed', () => {
  for (const h of ['/about', 'about', '#top', '/e46/mods/']) expect(isAllowedHref(h)).toBe(true)
})
test('https links to allowlisted hosts are allowed', () => {
  expect(isAllowedHref('https://github.com/GridWork-dev/m3-tool')).toBe(true)
  expect(isAllowedHref('https://creativecommons.org/licenses/by-sa/4.0/')).toBe(true)
})
test('flags an absolute link to a store host', () => {
  expect(isAllowedHref('https://www.example-store.com/p/123')).toBe(false)
})
test('flags protocol-relative links', () => {
  expect(isAllowedHref('//shop.example.com/wheels')).toBe(false)
})
test.each([
  'https://user:pw@github.com/x',
  'https://user@github.com/x',
  'https://:pw@github.com/x',
  'https://user:pw@archive.org/x',
  'https://user:pw@newsroom.bmwgroup.com/x',
])('refuses credentials in an allowed host: %s', (href) => {
  expect(isAllowedHref(href)).toBe(false)
})

test('a host that merely follows an @ is not the userinfo trick in reverse', () => {
  expect(isAllowedHref('https://github.com@evil.example/x')).toBe(false) // the host is evil.example
  expect(isAllowedHref('https://github.com/user@example')).toBe(true) // an @ in the path is fine
})

test('matches hosts exactly, not by suffix', () => {
  expect(isAllowedHref('https://evilgithub.com/x')).toBe(false)
  expect(isAllowedHref('https://gist.github.com/x')).toBe(false)
})
test('flags other schemes', () => {
  for (const h of ['mailto:a@b.c', 'http://github.com/x', 'javascript:void(0)'])
    expect(isAllowedHref(h)).toBe(false)
})
describe('citation hosts (spec 7.6, amended 2026-11-23)', () => {
  // A citation's url is linked only for a non-commercial reference on this reviewed list. Adding a
  // host means editing this test too, so a retailer cannot slip in with a one-line change.
  test('the list is the reviewed one', () => {
    expect([...CITATION_HOSTS]).toEqual([
      'archive.org',
      'web.archive.org',
      'newsroom.bmwgroup.com',
      'en.wikipedia.org',
      'commons.wikimedia.org',
    ])
  })

  test('it is separate from the list of hosts the site itself may link to', () => {
    expect(ALLOWED_LINK_HOSTS).not.toContain('archive.org')
    expect(ALLOWED_LINK_HOSTS).not.toContain('en.wikipedia.org')
  })

  test.each(CITATION_HOSTS)('%s is linkable over https, with any path', (host) => {
    expect(isCitationLinkable(`https://${host}/some/page?x=1#top`)).toBe(true)
    expect(isCitationLinkable(`https://${host}`)).toBe(true)
  })

  test.each(CITATION_HOSTS)('check:links accepts a link to %s', (host) => {
    expect(isAllowedHref(`https://${host}/some/page`)).toBe(true)
  })

  test('the hosts the site already allowed stay allowed', () => {
    for (const host of ALLOWED_LINK_HOSTS) expect(isAllowedHref(`https://${host}/x`)).toBe(true)
  })

  test.each([
    'http://archive.org/x',
    'ftp://archive.org/x',
    '//archive.org/x',
    '/archive.org/x',
    'archive.org/x',
    'javascript:alert(1)',
    '',
    'not a url',
  ])('%j is not linkable: only an absolute https url is', (url) => {
    expect(isCitationLinkable(url)).toBe(false)
  })

  test.each([
    'https://www.archive.org/x', // exact hosts only, as for the site allowlist
    'https://de.wikipedia.org/wiki/X',
    'https://wikipedia.org/wiki/X',
    'https://upload.wikimedia.org/x.jpg',
    'https://bmwgroup.com/x',
    'https://www.press.bmwgroup.com/x',
    'https://evilarchive.org/x',
    'https://archive.org.evil.example/x',
    'https://archive.org@evil.example/x',
    'https://user:pass@archive.org/x',
    'https://evil.example/archive.org',
    'https://evil.example/?next=https://archive.org/',
  ])('%s is not linkable', (url) => {
    expect(isCitationLinkable(url)).toBe(false)
  })

  test('the host is compared without regard to case', () => {
    expect(isCitationLinkable('HTTPS://Archive.ORG/x')).toBe(true)
    expect(isCitationLinkable('https://EN.Wikipedia.org/wiki/X')).toBe(true)
  })

  test.each([
    'https://koleso.ee/en/valuveljed/bmw/m3/263/e46-2000-2006/544',
    'https://www.hubcaphaven.com/p/3015/aly59367-bmw-m3-wheel-hyper-silver-36112229950.html',
    'https://www.bimmerworld.com/About-Us/Wheel-Info-Tech/',
    'https://www.example-store.com/p/123',
  ])('a Tier 2 retailer is never linked: %s', (url) => {
    expect(isCitationLinkable(url)).toBe(false)
    expect(isAllowedHref(url)).toBe(false)
  })

  // Every `sources[].url` anywhere in a data set, whatever the collection. A price's `url` is not a
  // source, so it is not here.
  const sourceUrls = (node: unknown): string[] => {
    if (Array.isArray(node)) return node.flatMap(sourceUrls)
    if (typeof node !== 'object' || node === null) return []
    return Object.entries(node).flatMap(([key, value]) =>
      key === 'sources' && Array.isArray(value)
        ? value.flatMap((source: { url?: string }) =>
            source.url === undefined ? [] : [source.url],
          )
        : sourceUrls(value),
    )
  }

  test('the real data: a source url is linkable exactly when its host is on the citation list', async () => {
    const { set } = await loadDataSet(fileURLToPath(new URL('../../data', import.meta.url)))
    const urls = sourceUrls(set)
    expect(urls.length).toBeGreaterThan(0)
    const hosts: readonly string[] = CITATION_HOSTS
    const onList = urls.filter((url) => hosts.includes(new URL(url).hostname))
    const offList = urls.filter((url) => !hosts.includes(new URL(url).hostname))
    expect(onList.filter((url) => !isCitationLinkable(url))).toEqual([])
    expect(offList.filter((url) => isCitationLinkable(url))).toEqual([])
    expect(onList.length + offList.length).toBe(urls.length)
  })
})

// The policy is shared with code that may reach the browser (a page that decides whether to link a
// citation), so it carries no dependencies. The HTML parser lives in html-links.ts.
test('the policy module imports nothing', () => {
  const source = readFileSync(new URL('../../src/lib/link-policy.ts', import.meta.url), 'utf8')
  expect(source).not.toMatch(/^\s*import\b/m)
  expect(source).not.toMatch(/\bimport\s*\(/)
  expect(source).not.toMatch(/\brequire\s*\(/)
})
