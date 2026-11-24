import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'
import { loadDataSet } from '../../src/data/load.ts'
import {
  ALLOWED_LINK_HOSTS,
  CITATION_HOSTS,
  findHrefs,
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
test('matches hosts exactly, not by suffix', () => {
  expect(isAllowedHref('https://evilgithub.com/x')).toBe(false)
  expect(isAllowedHref('https://gist.github.com/x')).toBe(false)
})
test('flags other schemes', () => {
  for (const h of ['mailto:a@b.c', 'http://github.com/x', 'javascript:void(0)'])
    expect(isAllowedHref(h)).toBe(false)
})
test('findHrefs returns every anchor href in order', () => {
  expect(findHrefs('<a href="/a">x</a><a class=y href=\'https://github.com\'>z</a>')).toEqual([
    '/a',
    'https://github.com',
  ])
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

  test('the real data: its retailer sources are not linkable and its BMW sources are', async () => {
    const root = fileURLToPath(new URL('../../data', import.meta.url))
    const { set } = await loadDataSet(root)
    const urls = [
      ...set.generations.flatMap(({ data }) => [
        ...data.sources,
        ...data.fitment.sources,
        ...Object.values(data.dimensions).flatMap((dimensions) => dimensions.sources),
      ]),
      ...set.parts.flatMap(({ data }) => data.sources),
    ].flatMap((source) =>
      source.url === undefined ? [] : [{ tier: source.tier, url: source.url }],
    )
    expect(urls.length).toBeGreaterThan(0)
    for (const { url } of urls) {
      const { hostname } = new URL(url)
      const retailer = ['koleso.ee', 'www.hubcaphaven.com', 'www.bimmerworld.com'].includes(
        hostname,
      )
      if (retailer) expect(isCitationLinkable(url), url).toBe(false)
      if (hostname.endsWith('bmwgroup.com')) expect(isCitationLinkable(url), url).toBe(true)
    }
    // Every host in CITATION_HOSTS that the data uses is on the list because the data uses it.
    const hosts = new Set(urls.map(({ url }) => new URL(url).hostname))
    expect(hosts.has('newsroom.bmwgroup.com')).toBe(true)
    expect(hosts.has('archive.org')).toBe(true)
  })
})
