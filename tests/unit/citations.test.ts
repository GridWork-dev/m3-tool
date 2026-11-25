import { expect, test } from 'vitest'
import { loadDataSet } from '../../src/data/load.ts'
import { citationView, latestAccessed } from '../../src/lib/citations.ts'
import { isCitationLinkable } from '../../src/lib/link-policy.ts'

test('sources are linked exactly when citation policy allows', async () => {
  const { set } = await loadDataSet('data')
  for (const entries of Object.values(set))
    for (const { data } of entries)
      for (const s of data.sources) {
        const view = citationView(s)
        expect('href' in view).toBe(s.url !== undefined && isCitationLinkable(s.url))
        expect(view.accessed).toMatch(/^\d{4}-\d{2}-\d{2}$/)
      }
})
test.each([
  'https://archive.org.evil.test/x',
  'https://newsroom.bmwgroup.com@evil.test/x',
  'https://cdn.shopify.com/x',
])('never links %s', (url) =>
  expect(
    citationView({
      publisher: 'Test',
      title: 'Test',
      tier: 1,
      accessed: new Date('2026-11-23'),
      url,
    }),
  ).not.toHaveProperty('href'),
)
test('latest accessed handles empty lists and calendar ordering', () => {
  expect(latestAccessed([])).toBeUndefined()
  expect(
    latestAccessed(
      [new Date('2026-01-01'), new Date('2026-11-23')].map((accessed) => ({
        publisher: 'Test',
        title: 'Test',
        tier: 1 as const,
        accessed,
      })),
    ),
  ).toBe('2026-11-23')
})
