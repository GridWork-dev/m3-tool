import { expect, test } from 'vitest'
import { pageTitle, SITE_NAME } from '../../src/lib/site.ts'

test('SITE_NAME is m3-tool', () => {
  expect(SITE_NAME).toBe('m3-tool')
})

test('pageTitle puts the page first and the site name last', () => {
  expect(pageTitle()).toBe('m3-tool')
  expect(pageTitle('About')).toBe('About · m3-tool')
})

test('pageTitle treats a blank title as no title', () => {
  expect(pageTitle('   ')).toBe('m3-tool')
  expect(pageTitle('')).toBe('m3-tool')
})
