import { expect, test } from 'vitest'
import { findHrefs, isAllowedHref } from '../../src/lib/link-policy.ts'

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
