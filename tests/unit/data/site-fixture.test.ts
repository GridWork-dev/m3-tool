import { expect, test } from 'vitest'
import { loadDataSet } from '../../../src/data/load.ts'
import { checkDataSet } from '../../../src/data/quality.ts'

test('the site fixtures are valid and cover reading-page states', async () => {
  const { set, issues } = await loadDataSet('tests/fixtures/site-data')
  expect(issues).toEqual([])
  expect(checkDataSet(set)).toEqual([])
  expect(set.generations).toHaveLength(2)
  const entries = set.issues.map(({ data }) => data)
  expect(new Set(entries.flatMap((entry) => entry.markets))).toEqual(new Set(['us', 'euro']))
  expect(new Set(entries.map((entry) => entry.frequency))).toEqual(
    new Set(['very-common', 'common', 'rare']),
  )
  for (const predicate of [
    (entry: (typeof entries)[number]) => Boolean(entry.cost),
    (entry: (typeof entries)[number]) => entry.verified,
    (entry: (typeof entries)[number]) => entry.inspectWhenBuying,
  ]) {
    expect(entries.some(predicate)).toBe(true)
    expect(entries.some((entry) => !predicate(entry))).toBe(true)
  }
  const e46 = set.generations.find(({ data }) => data.id === 'e46')?.data
  expect(e46?.years).toEqual([2000, 2006])
  expect(e46?.engines.map((engine) => [engine.displacementCc, engine.cylinders])).toEqual([
    [3000, 6],
    [4000, 8],
  ])
  expect(e46?.dimensions.coupe).toMatchObject({ lengthMm: 4492, heightMm: 1372, wheelbaseMm: 2731 })
  expect(e46?.fitment.front.stock).toEqual({
    diameterIn: 18,
    widthIn: 8,
    offsetMm: 47,
    tire: '225/45ZR18',
  })
  expect(e46?.fitment.rear.stock).toEqual({
    diameterIn: 18,
    widthIn: 9,
    offsetMm: 26,
    tire: '255/40ZR18',
  })
  expect(e46?.fitment.front.envelopes).toEqual([])
  expect(e46?.fitment.rear.envelopes.length).toBeGreaterThan(0)
  expect(e46?.driverEyePoint.basis).toBe('estimated')
  expect(e46?.unverified).toEqual([
    'years.1',
    'engines.FIXTURE-ENGINE-2.displacementCc',
    'fitment.front.stock.widthIn',
    'fitment.front.stock.offsetMm',
    'fitment.rear.stock.offsetMm',
  ])
  const second = set.generations.find(({ data }) => data.id === 'fixture-gen2')?.data
  expect(second?.years).toEqual([2008, 2013])
  expect(second?.dimensions.coupe?.lengthMm).not.toBe(4492)
  expect(second?.driverEyePoint.basis).toBe('measured')
  expect(second?.driverEyePoint.sources).toHaveLength(1)
  expect(second?.unverified).toBeUndefined()
  expect(set.variants).toHaveLength(3)
  expect(set.variants.find(({ data }) => data.id === 'fixture-euro-csl')?.data.interiors).toEqual(
    [],
  )
  expect(
    entries.filter((entry) => entry.generation === 'fixture-gen2').map((entry) => entry.markets),
  ).toEqual([['us']])
  expect(set.maintenance).toEqual([])
})
